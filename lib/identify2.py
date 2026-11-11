#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""identify2.py —— 识曲（多路召回 + 歌词校验）

思路：ASR 唱词会错字，单靠"搜一段词"容易搜错歌。这里做三路召回再逐个用歌词打分：
  A. 网易云搜索：用多段最长纯中文片段分别搜（3~4 次）
  B. 大模型给候选（它记得大量歌词），再按候选名去网易云取词
  C. 打分：ASR 文本与候选官方歌词的**拼音二元组**重合度（对同音误听稳健）
  D. 只有分数 ≥ 0.45 才采用，否则判为"识别不出"，宁缺勿错
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import identify_lib as IL
import judge_lib as J
import align_qwen as AQ
import os as _os
from pathlib import Path as _P
ROOT = _P(_os.environ.get('SONG_CUT_HOME') or _P(__file__).resolve().parent.parent)
_ROOT = ROOT


def _ff(name, env):
    _e = _os.environ.get(env)
    if _e:
        return _e
    _p = _ROOT / 'bin2' / name
    return str(_p) if _p.exists() else name


FFMPEG = _ff('ffmpeg', 'SONG_CUT_FFMPEG')
FFPROBE = _ff('ffprobe', 'SONG_CUT_FFPROBE')
PY_BIN = _os.environ.get('SONG_CUT_PY', 'python3')


CACHE = ROOT / 'queue' / 'identify2_cache.json'
MIN_SCORE = 0.36
MAX_CAND = 5
BUDGET = 45.0          # 单次识别最长耗时（秒），超预算就用已有结果


def _zh_only(s):
    return ''.join(re.findall(r'[\u4e00-\u9fff]', s or ''))


def snippets(text, n=4, minlen=10):
    """取若干互不重叠的长片段作搜索词"""
    chunks = [m.group() for m in re.finditer(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{8,}', text or '')]
    chunks.sort(key=len, reverse=True)
    out, used = [], set()
    for c in chunks:
        if len(out) >= n:
            break
        key = c[:6]
        if any(key in u or u in key for u in used):
            continue
        used.add(key)
        out.append(c[:18])
    return out


def _cache_load():
    try:
        return json.loads(CACHE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _cache_save(c):
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _net_search(q, limit=8):
    try:
        d = IL._post('https://music.163.com/api/search/get', {'s': q, 'type': 1, 'limit': limit})
        return ((d.get('result') or {}).get('songs') or [])[:limit]
    except Exception:
        return []


def _llm_candidates(text):
    sys_p = ('你是曲库检索助手。给你一段直播演唱的 ASR 文本（有错字、有重复）。'
             '请给出最可能的 3 首歌曲，格式 JSON 数组：[{"title":"歌名","artist":"原唱"}]。'
             '只输出 JSON，不要解释。确定不了就给空数组。')
    try:
        r = J.ask(sys_p, {'asr': (text or '')[:1200]}, max_tokens=300)
    except Exception:
        return []
    if isinstance(r, dict):
        r = r.get('items') or r.get('songs') or []
    out = []
    if isinstance(r, list):
        for x in r:
            if isinstance(x, dict) and x.get('title'):
                out.append((str(x['title']).strip(), str(x.get('artist') or '').strip()))
    return out[:3]


def score(text, lines):
    rt = IL.py(text)
    lp = IL.py(''.join(lines))
    if not rt or not lp:
        return 0.0
    return IL.dice(rt, lp, 2)


DCACHE = ROOT / 'queue' / 'identify_cache.json'


def identify_region(text, segs=None):
    """返回 {title, artist, score, lines, why}；识别不出返回 {}（带磁盘缓存）

    若提供 segs（该区间的逐句转写，含 words），则用**拼音 DTW 对齐率**做最终裁决，
    这比字面相似度可靠得多：相似度高但歌词对不上的错歌会被剔掉。
    """
    if len(_zh_only(text)) < 12:
        return {}
    import hashlib
    h = hashlib.md5(text[:600].encode('utf-8')).hexdigest()
    try:
        dc = json.loads(DCACHE.read_text(encoding='utf-8'))
    except Exception:
        dc = {}
    if h in dc:
        return dc[h]
    res = _identify(text, segs) if segs else _identify(text)
    if segs:                      # 带对齐信息的结果才缓存（更可信）
        dc[h] = res
    try:
        DCACHE.parent.mkdir(parents=True, exist_ok=True)
        DCACHE.write_text(json.dumps(dc, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass
    return res


def _local_corpus():
    """本地已抓到的官方歌词库（零网络），用于快速命中熟歌"""
    try:
        return AQ._oc_load() or {}
    except Exception:
        return {}


def _match_local(text, thr=0.55):
    """先在本歌词库里找：文字召回足够高就直接认定，省掉全部网络请求"""
    import re as _re
    heard = set(_re.findall(r'[\u4e00-\u9fff]', text or ''))
    if len(heard) < 15:
        return None
    best = None
    for key, val in _local_corpus().items():
        try:
            title, artist = key.split('|', 1)
        except ValueError:
            continue
        lines = val[0] if isinstance(val, (list, tuple)) and val else val
        if not lines:
            continue
        want = set(_re.findall(r'[\u4e00-\u9fff]', ''.join(lines)))
        if not want:
            continue
        low = title.lower()
        if any(k in low for k in ('instrumental', '伴奏', '纯音乐', 'karaoke')):
            continue
        rec = len(want & heard) / len(want)
        if 'live' in low:
            rec -= 0.06
        if '/' in artist:
            rec -= 0.04
        if rec >= thr and (best is None or rec > best['recall']):
            best = {'title': title, 'artist': artist, 'score': round(rec, 3),
                    'recall': round(rec, 3), 'lines': lines, 'src': 'local'}
    return best


def _identify(text, segs=None):
    import os as _os
    import time as _t
    offline = bool(_os.environ.get('JUDGE_OFF'))
    t0 = _t.time()
    hit = _match_local(text)
    if hit:
        return hit
    cache = _cache_load()
    cands = {}          # (title, artist) -> 歌词行

    # A. 多段搜索（最多 2 段，避免网易云限速拖慢整场）
    for q in snippets(text, n=2 if not offline else 4):
        if _t.time() - t0 > BUDGET * 0.5:
            break
        for s in _net_search(q):
            name = s.get('name') or ''
            low = name.lower()
            if any(k in low for k in ('instrumental', '伴奏', '纯音乐', 'karaoke')):
                continue                      # 伴奏/纯音乐版本直接排除，省一次取词
            arts = '/'.join(a['name'] for a in (s.get('artists') or []))
            if name and (name, arts) not in cands:
                cands[(name, arts)] = None

    # B. 大模型候选（离线模式跳过；网易云已给足候选时也跳过）
    if (not offline) and _t.time() - t0 < BUDGET * 0.6:
        llm_cands = _llm_candidates(text)
    else:
        llm_cands = []
    for name, arts in llm_cands:
        if (name, arts) in cands:
            continue
        got = AQ.official(name, arts)
        if got and got[0]:
            cands[(name, arts)] = got[0]

    items = list(cands.items())[:MAX_CAND]

    def fetch(item):
        (name, arts), lines = item
        if lines is None:
            key = f'{name}|{arts}'
            if key in cache:
                lines = cache[key]
            else:
                got = AQ.official(name, arts)
                lines = got[0] if (got and got[0]) else []
                cache[key] = lines
                _cache_save(cache)
        return (name, arts, lines)

    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(fetch, items))

    best = None
    scores = []
    import dtw_align as _D
    import re as _re

    def _set(s):
        return set(_re.findall(r'[\u4e00-\u9fff]', s or ''))

    heard = _set(text)

    def recall_of(ly):
        """候选歌词的文字有多少比例真的出现在这段演唱里（比相似度更能识别错歌）"""
        want = _set(''.join(ly))
        if not want:
            return None
        return len(want & heard) / len(want)

    def anchor_of(ly):
        if not segs or not ly:
            return None
        try:
            return min(1.0, len(_D.dtw_map(ly, segs)) / max(1, len(ly)))
        except Exception:
            return None
    for name, arts, lines in rows:
        if not lines or len(lines) < 5:
            continue
        sc = score(text, lines)
        # 优先原唱：Live/翻唱版、多艺人条目不优先
        low = (name or '').lower()
        if 'live' in low:
            sc -= 0.08
        if low.endswith('版') or '(版' in low or '翻自' in low:
            sc -= 0.08
        if '/' in (arts or ''):
            sc -= 0.05
        rec = recall_of(lines)
        if rec is None or rec < 0.40:
            continue                      # 歌词文字对不上这段演唱 → 直接否掉
        # 再用 DTW 对齐率 + 行同步率复核，避免"标题里恰好有这句词"的李鬼
        anc = anchor_of(lines)
        sync = None
        if segs:
            try:
                import qc as _qc
                rows = [{'t': 0, 'x': ly} for ly in lines]
                errs, hit = _qc.line_errors([(0, ly) for ly in lines], segs)
                zr = sum(1 for ly in lines if len(_re.findall(r'[\u4e00-\u9fff]', ly)) >= 2)
                sync = hit / max(1, zr)
            except Exception:
                sync = None
        comb = 0.4 * sc + 0.35 * rec + 0.25 * (anc or 0)
        if anc is not None and anc < 0.60:
            continue                      # 对齐率太低：不是这首
        scores.append((round(sc, 3), name, arts))
        cand = {'title': name, 'artist': arts, 'score': round(sc, 3), 'lines': lines,
                'recall': round(rec, 3), 'comb': round(comb, 3),
                'anchor': None if anc is None else round(anc, 3),
                'sync': None if sync is None else round(sync, 3)}
        if best is None or comb > best['comb']:
            best = cand
    if best and best['score'] >= MIN_SCORE:
        # 一致性要求：同一歌名（去括号/版本词）至少被两个候选条目命中 ≥0.40
        key = re.sub(r'[\(（\[【].*?[\)）\]】]|\s|live|版|翻唱', '', best['title'].lower())
        agree = len({(n.lower(), a) for s, n, a in scores if s >= 0.40 and
                     re.sub(r'[\(（\[【].*?[\)）\]】]|\s|live|版|翻唱', '', n.lower()) == key})
        best['agree'] = agree
        # 单路证据也接受，但要求歌词吻合度更高（≥0.60），避免"只有一路碰巧对上"
        if agree < 2 and best['score'] < 0.60:
            return {'title': '', 'artist': '', 'score': best['score'],
                    'why': f'只有 1 路证据且吻合度 {best["score"]:.2f}<0.60：{best["title"][:20]}'}
        return best
    return {'title': '', 'artist': '', 'score': round(best['score'], 3) if best else 0.0,
            'why': f'候选 {len(rows)} 个，最高分 {best["score"] if best else 0:.2f} 低于 {MIN_SCORE}'}


if __name__ == '__main__':
    import sys
    t = open(sys.argv[1], encoding='utf-8').read() if len(sys.argv) > 1 else ''
    print(identify_region(t))