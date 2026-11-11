#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""align_qwen.py —— 歌词排轴：官方歌词 × 词级/句级 ASR（同济 Qwen 配对 + DP 兜底）

思路：
  1. 取审核过的官方歌词（按 曲名+原唱 反查，绝不用翻唱）；
  2. 取本机 ASR 的句子/词时间戳；
  3. 让 Qwen 把「歌词第 i 行」配到「ASR 第 j 句」（容忍错字、重复副歌）；
  4. 用 DP 做一次独立配对，两路取信噪比高的那一路；
  5. 时间点单调化；没有锚点的行只在左右相邻锚点之间插值，绝不整体线性铺开。

用法：python3 align_qwen.py <song_no> [<song_no> ...]
输出：<项目根>/align2/<no>.lrc + <no>.align.json
"""
import json, re, sys, time, urllib.request, urllib.parse
from pathlib import Path
import dtw_align as _D

import llmcfg as _C
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

API = _C.API
KEY = _C.KEY
MODEL = _C.MODEL
AUD = ROOT / 'site' / 'audio'
ASR = Path(f'{ROOT}/audit2')
OUT = Path(f'{ROOT}/align2'); OUT.mkdir(exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com'}
CRED = re.compile(r'[:：]|作词|作曲|编曲|和声|吉他|贝斯|鼓|录音|混音|母带|制作|监制|总监|出品|发行|企划|统筹|OP|SP|剪辑|人声|后期|ISRC|未经许可|不得翻唱|纯音乐|原唱|翻自|语种|流派|厂牌|版权')

SYS = ('任务：给一首歌的歌词排时间轴。用户给你两组数据：'
       '「歌词」是按顺序排列的歌词行（编号从1开始），「转写」是这首歌音频的机器转写句（带编号i、起始秒s、文本）。'
       '转写错字极多，请按语义/音近容错匹配。请对每行歌词，给出它在转写中对应的句子编号（取该行开始唱的那一句）。'
       '注意：副歌可能重复多遍，必须按歌词顺序依次向后配，不要都配到第一遍。'
       '找不到对应句子的歌词行，j 填 null。'
       '输出严格 JSON 数组：[{"k":歌词行号,"j":转写句号或null}]，不要输出任何解释。')


try:
    import zhconv as _zc
except Exception:
    _zc = None
try:
    from pypinyin import lazy_pinyin as _py
except Exception:
    _py = None


def norm(s):
    s = re.sub(r'[^\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z]', '', s)
    if _zc is not None and s:
        try:
            s = _zc.convert(s, 'zh-cn')
        except Exception:
            pass
    return s


def pinyin(s):
    if _py is None:
        return ''
    try:
        return ''.join(_py(norm(s)))
    except Exception:
        return ''


def post(u, d):
    r = urllib.request.Request(u, data=urllib.parse.urlencode(d).encode(), headers=UA)
    return json.loads(urllib.request.urlopen(r, timeout=10).read().decode('utf-8', 'ignore'))


def get(u):
    r = urllib.request.Request(u, headers=UA)
    return json.loads(urllib.request.urlopen(r, timeout=10).read().decode('utf-8', 'ignore'))


def _simp(x):
    try:
        import zhconv
        return zhconv.convert(x, 'zh-cn')
    except Exception:
        return x


_OFF_CACHE = Path(f'{ROOT}/queue/official_cache.json')
_off_cache = None


def _oc_load():
    global _off_cache
    if _off_cache is None:
        try:
            _off_cache = json.loads(_OFF_CACHE.read_text(encoding='utf-8'))
        except Exception:
            _off_cache = {}
    return _off_cache


def official(title, artist):
    key = f'{title}|{artist}'
    c = _oc_load()
    if key in c:
        return c[key]
    r = _official_net(title, artist)
    if r:
        c[key] = r
        try:
            _OFF_CACHE.parent.mkdir(exist_ok=True)
            _OFF_CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
    return r


def _official_net(title, artist):
    artist = artist or ''
    q = f'{_simp(title)} {_simp(artist)}'.strip()
    d = post('https://music.163.com/api/search/get',
             {'s': q, 'type': 1, 'limit': 10})
    exact, cover = None, None
    for s in ((d.get('result') or {}).get('songs') or [])[:10]:
        if _simp(title) not in _simp(s['name']):
            continue
        arts = [a['name'] for a in s['artists']]
        x = get(f"https://music.163.com/api/song/lyric?id={s['id']}&lv=-1&kv=-1&tv=-1")
        raw = (x.get('lrc') or {}).get('lyric') or ''
        lines = [re.sub(r'\[.*?\]', '', l).strip() for l in raw.split('\n')]
        lines = [l for l in lines if len(norm(l)) >= 4 and not CRED.search(l)]
        # 去掉旁白/念白行（过长或整句以句号结尾的叙述），它们不会被唱
        def ok_len(l):
            n = len(norm(l))
            ascii_ratio = sum(1 for c in norm(l) if ord(c) < 128) / max(1, n)
            if ascii_ratio > 0.5:      # 英文/罗马音行可以更长
                return n <= 48
            return n <= 20 and not (n > 12 and l.endswith('。'))
        lines = [l for l in lines if ok_len(l)]
        if not lines:
            continue
        rec = (lines, f"{s['name']}/{arts[0] if arts else ''}")
        if not artist or any(artist[:2] in a for a in arts):
            return rec
        if cover is None:
            cover = rec
    return cover


SKIP_QWEN = bool(__import__('os').environ.get('SKIP_QWEN'))


def qwen_map(lines, segs):
    if SKIP_QWEN:
        return {}
    payload = {'歌词': [{'k': i + 1, 't': l} for i, l in enumerate(lines)],
               '转写': [{'i': i + 1, 's': round(s['start'], 1), 't': s['text'][:60]} for i, s in enumerate(segs)]}
    body = {'model': MODEL, 'temperature': 0.0, 'max_tokens': 4000,
            **_C.EXTRA,
            'messages': [{'role': 'system', 'content': SYS},
                         {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
    data = json.dumps(body).encode()
    for k in range(3):
        try:
            req = urllib.request.Request(API, data=data,
                                         headers={'Authorization': 'Bearer ' + KEY,
                                                  'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.loads(r.read().decode())
            c = j['choices'][0]['message'].get('content') or ''
            a, b = c.find('['), c.rfind(']')
            if a < 0:
                raise ValueError('nojson')
            arr = json.loads(c[a:b + 1])
            m = {}
            for x in arr:
                if isinstance(x, dict) and isinstance(x.get('k'), int):
                    m[x['k']] = x.get('j') if isinstance(x.get('j'), int) else None
            return m
        except Exception as ex:
            print(f'    qwen 重试{k+1} {type(ex).__name__} {str(ex)[:60]}', flush=True)
            time.sleep(2 + 2 * k)
    return {}


def cov(rt, line, k=4):
    """歌词行与转写句的相似度：整串相似度 + 包含度，取最大"""
    import difflib as _d
    n = norm(line)
    if not n or not rt:
        return 0.0
    if n in rt:
        return 1.0
    pn, pr = pinyin(line), pinyin(rt)
    if pn:
        import difflib as _d2
        rp = _d2.SequenceMatcher(None, pn, pr).ratio() if pr else 0.0
    else:
        rp = 0.0
    r = _d.SequenceMatcher(None, n, rt).ratio()
    # 短行被长句吞掉时，整串 ratio 会偏低，用最优窗口补一次
    if len(rt) > len(n) + 2:
        best = 0.0
        for i in range(0, len(rt) - len(n) + 1):
            w = rt[i:i + len(n)]
            q = _d.SequenceMatcher(None, n, w).ratio()
            if q > best:
                best = q
                if best > 0.8:
                    break
        r = max(r, best)
    return max(r, rp * 0.95)


def dp_map(lines, segs, win=6, thr=0.3):
    """顺序贪心：每行歌词从上次命中位置往后 win 句内找最佳匹配（保证单调）"""
    out, cur = {}, 0
    for i, l in enumerate(lines, 1):
        best, bj = 0.0, None
        for j in range(cur, min(len(segs), cur + win)):
            cv = cov(norm(segs[j]['text']), l)
            if cv > best:
                best, bj = cv, j
        if bj is not None and best >= thr:
            out[i] = bj + 1
            cur = bj + 1
    return out


def score_map(lines, segs, mp):
    got = 0
    for i, l in enumerate(lines, 1):
        j = mp.get(i)
        if isinstance(j, int) and 1 <= j <= len(segs) and cov(norm(segs[j - 1]['text']), l) >= 0.4:
            got += 1
    return got / max(1, len(lines)), got


def monotonic_fill(lines, segs, mp, dur, times_map=None, offset=1):
    times = [None] * len(lines)
    for idx, l in enumerate(lines, 1):
        i = idx + offset - 1
        if times_map and isinstance(times_map.get(i), (int, float)):
            times[idx - 1] = float(times_map[i])   # 用音节级时间（开头大段更准）
            continue
        j = mp.get(i)
        if isinstance(j, int) and 1 <= j <= len(segs):
            times[idx - 1] = segs[j - 1]['start']
    known = [(i, t) for i, t in enumerate(times) if t is not None]
    if not known:
        # 完全没锚点：整首按行数均匀铺，别硬编 2.5 秒
        n = max(1, len(lines))
        step = max(1.0, (max(1.0, dur - 3.0)) / n)
        times = [round(1.0 + step * i, 2) for i in range(n)]
        known = [(i, t) for i, t in enumerate(times)]
    for i, t in enumerate(times):
        if t is not None:
            continue
        prev = [x for x in known if x[0] < i]
        nxt = [x for x in known if x[0] > i]
        if prev and nxt:
            (ia, ta), (ib, tb) = prev[-1], nxt[0]
            # 按字符数加权插值（长句占更多时间）
            seg_len = [max(1, len(lines[k-1])) for k in range(ia, ib)]
            total = sum(seg_len) or 1
            acc = sum(max(1, len(lines[k-1])) for k in range(ia, i-1))
            times[i] = ta + (tb - ta) * acc / total
        elif prev:
            # 尾部无锚点：均匀铺到接近歌曲结尾，避免整体被压缩
            ia, ta = prev[-1]
            end_t = max(ta + 1.0, dur - 2.0)
            span = max(1, len(lines) - 1 - ia)
            times[i] = ta + (end_t - ta) * (i - ia) / span
        elif nxt:
            ib, tb = nxt[0]
            start_t = max(0.3, tb - 3.0 * ib)
            span = max(1, ib)
            times[i] = max(0.3, tb - (tb - start_t) * (ib - i) / span)
        else:
            times[i] = 0.3 + 3.0 * i
    # 歌词不该早于第一句转写（那段之前没有演唱）
    floor = min((x['start'] for x in segs), default=0.0)
    out, last = [], floor
    for t, l in zip(times, lines):
        t = max(t, last + 0.5)
        t = min(t, max(0.5, dur - 0.6))
        out.append((round(t, 2), last := t, l))
    return [(t, l) for t, _, l in out]


def main(plan_path, only=None):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    report = []
    for p in plan:
        no = str(p['no']).zfill(2)
        if only and no not in only:
            continue
        f = AUD / p['file']
        asr_f = ASR / (f.stem + '.jsonl')
        alt = Path(f'{ROOT}/audit3') / (f.stem + '.jsonl')
        if alt.exists() and alt.stat().st_size > 100:
            asr_f = alt
        if not asr_f.exists():
            print(f'{no} {p["title"]}: 缺词级 ASR，跳过'); continue
        segs = [json.loads(l) for l in asr_f.read_text(encoding='utf-8').splitlines() if l.strip()]
        BAD = ('Zither', 'Harp', '字幕', '索兰娅', 'MING PAO')
        segs = [s for s in segs if norm(s['text']) and not any(b in s['text'] for b in BAD)]
        pf = Path(f'{ROOT}/audit_prefix') / f"{no}.json"
        if pf.exists() and __import__('os').environ.get('USE_PREFIX') == '1':
            try:
                pre = json.loads(pf.read_text(encoding='utf-8'))
                pre = [s for s in pre if norm(s['text']) and not any(b in s['text'] for b in BAD)]
                if pre:
                    cut = max(s['end'] for s in pre)
                    segs = pre + [s for s in segs if s['start'] > cut]
                    segs.sort(key=lambda z: z['start'])
            except Exception as e:
                print('  前缀合并失败', e)
        if not segs:
            print(f'{no} {p["title"]}: ASR 为空'); continue
        off = official(p['title'], p['artist'])
        if not off:
            print(f'{no} {p["title"]}: 取不到官方歌词'); continue
        lines, src = off
        dur = segs[-1]['end']
        mq = qwen_map(lines, segs)
        md = dp_map(lines, segs)
        raw = _D.dtw_map(lines, segs)
        mt = {k: v[0] for k, v in raw.items()}

        def quality(mp):
            """覆盖率 + 时间单调性 联合评分"""
            pairs = sorted((i, val) for i, val in mp.items()
                           if isinstance(val, int) and 1 <= val <= len(segs))
            if not pairs:
                return 0.0, 0, 0
            cov = len(pairs) / max(1, len(lines))
            mono = sum(1 for a, b in zip(pairs, pairs[1:])
                       if segs[b[1] - 1]['start'] >= segs[a[1] - 1]['start'])
            mono = mono / max(1, len(pairs) - 1)
            return round(cov * (0.55 + 0.45 * mono), 3), len(pairs), round(cov, 3)

        scored = []
        for tg, mp in (('qwen', mq), ('dp', md), ('dtw', mt)):
            q, n, cv = quality(mp)
            scored.append((tg, mp, q * (1.15 if tg == 'dtw' else 1.0), q, n, cv))
        tag, use, _w, _q, _n, _c = max(scored, key=lambda x: x[2])
        by = {t: (q, n, cv) for t, _m, _w2, q, n, cv in scored}
        sq, gq, _ = by['qwen']
        sd, gd, _ = by['dp']
        st, gt, _ = by['dtw']
        tmap = {k: v[1] for k, v in raw.items()} if tag == 'dtw' else None
        final = monotonic_fill(lines, segs, use, dur, tmap)
        lrc = '\n'.join(f'[{int(t)//60:02d}:{t%60:05.2f}]{l}' for t, l in final)
        (OUT / f'{no}.lrc').write_text(lrc, encoding='utf-8')
        rec = {'no': no, 'title': p['title'], 'artist': p['artist'], 'src': src,
               'lines': len(lines), 'dur': round(dur, 1), 'method': tag,
               'qwen_score': round(sq, 3), 'qwen_hits': gq,
               'dp_score': round(sd, 3), 'dp_hits': gd,
               'dtw_score': round(st, 3), 'dtw_hits': gt}
        report.append(rec)
        print(f"{no} {p['title'][:12]:<14} 行{len(lines):>3} qwen {sq:.2f}({gq}) dp {sd:.2f}({gd}) dtw {st:.2f}({gt}) -> 用{tag}", flush=True)
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('done', flush=True)


if __name__ == '__main__':
    only = set(sys.argv[2:]) if len(sys.argv) > 2 else None
    main(sys.argv[1], only)