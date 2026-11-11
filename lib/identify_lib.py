#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""identify_lib.py —— 用网易云歌词库识别一段转写属于哪首歌（本地计算，不耗 LLM）"""
import json, re, urllib.request, urllib.parse
from pathlib import Path
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


UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com'}
CRED = re.compile(r'[:：]|作词|作曲|编曲|和声|吉他|贝斯|鼓|录音|混音|母带|制作|监制|总监|出品|发行|企划|统筹|OP|SP|剪辑|ISRC|未经许可')

try:
    import zhconv
except Exception:
    zhconv = None
try:
    from pypinyin import lazy_pinyin
except Exception:
    lazy_pinyin = None


def norm(s):
    s = re.sub(r'[^\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z]', '', s)
    if zhconv:
        try:
            s = zhconv.convert(s, 'zh-cn')
        except Exception:
            pass
    return s


def py(s):
    if not lazy_pinyin:
        return norm(s)
    out = []
    for run in re.findall(r'[\u4e00-\u9fff]+|[A-Za-z]+|[\u3040-\u30ff]+|[\uac00-\ud7af]+', norm(s)):
        if re.match(r'[\u4e00-\u9fff]', run):
            out.extend(lazy_pinyin(run))
        elif re.match(r'[A-Za-z]', run):
            out.append(run.lower())
        else:
            out.extend(list(run))
    return ''.join(out)


CACHE = Path(f'{ROOT}/queue/lyric_cache.json')
_cache = None


def _cache_load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE.read_text(encoding='utf-8'))
        except Exception:
            _cache = {}
    return _cache


def _cache_save():
    try:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(_cache, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _post(u, d):
    r = urllib.request.Request(u, data=urllib.parse.urlencode(d).encode(), headers=UA)
    return json.loads(urllib.request.urlopen(r, timeout=8).read().decode('utf-8', 'ignore'))


def _get(u):
    r = urllib.request.Request(u, headers=UA)
    return json.loads(urllib.request.urlopen(r, timeout=8).read().decode('utf-8', 'ignore'))


def lyric_of(sid):
    c = _cache_load()
    key = str(sid)
    if key in c:
        return c[key]
    d = _get(f'https://music.163.com/api/song/lyric?id={sid}&lv=-1&kv=-1&tv=-1')
    raw = (d.get('lrc') or {}).get('lyric') or ''
    lines = [re.sub(r'\[.*?\]', '', l).strip() for l in raw.split('\n')]
    lines = [l for l in lines if l and not CRED.search(l)]
    c[key] = lines
    _cache_save()
    return lines


def dice(a, b, n=3):
    A = {a[i:i + n] for i in range(max(0, len(a) - n + 1))}
    B = {b[i:i + n] for i in range(max(0, len(b) - n + 1))}
    return 2 * len(A & B) / max(1, len(A) + len(B))


def lang_of(lines):
    txt = ''.join(lines)
    kana = len(re.findall(r'[\u3040-\u30ff]', txt))
    han = len(re.findall(r'[\u4e00-\u9fff]', txt))
    kor = len(re.findall(r'[\uac00-\ud7af]', txt))
    lat = len(re.findall(r'[A-Za-z]', txt))
    m = max(kana, han, kor, lat)
    return ('日语' if m == kana else '韩语' if m == kor else '英文' if m == lat else '国语')


def snippet(text, n=16):
    best = ''
    for m in re.finditer(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{8,}', text):
        if len(m.group()) > len(best):
            best = m.group()
    return (best or text)[:n]


def identify_region(text):
    """返回 {title, artist, score, lang}；识别不到返回 {}"""
    q = snippet(text)
    if len(q) < 6:
        return {}
    try:
        d = _post('https://music.163.com/api/search/get', {'s': q, 'type': 1, 'limit': 8})
    except Exception:
        return {}
    rt = py(text)
    best = None
    cands = ((d.get('result') or {}).get('songs') or [])[:3]
    from concurrent.futures import ThreadPoolExecutor
    def fetch(sid):
        try:
            return lyric_of(sid)
        except Exception:
            return []
    with ThreadPoolExecutor(max_workers=3) as ex:
        lyr = list(ex.map(fetch, [c['id'] for c in cands]))
    for s, lines in zip(cands, lyr):
        if len(lines) < 5:
            continue
        lp = py(''.join(lines))
        sc = dice(rt, lp, 3)
        if best is None or sc > best['score']:
            best = {'title': s['name'],
                    'artist': '/'.join(a['name'] for a in s['artists']),
                    'score': round(sc, 3), 'lang': lang_of(lines)}
    return best or {}