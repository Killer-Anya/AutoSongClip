#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""corpus_detect.py —— 不依赖大模型的"检歌"：用本地歌词语料在整场转写里找歌

原理：
  1. 语料 = queue/official_cache.json（已抓过的网易云歌词）+ 旧版曲库 lrc + 新版条目 lrc
  2. 每首歌取"2 字片段集合"（对 ASR 错字鲁棒），统计它在某时间窗里被命中的比例
  3. 在整场转写上滑动窗口（默认 45 秒步长、120 秒窗），命中比例够高就认为这段在唱这首歌
  4. 连续命中同一首歌的窗口合并成区间，交给后续的边界校正/排轴/质检

用法（独立运行，仅本地计算）：
  python3 lib/corpus_detect.py <bvid> [--json out.json]
"""
import json
import sys
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


MIN_LEN = 6          # 歌词至少 6 个汉字
WIN = 120.0          # 窗口长度（秒）
STEP = 30.0          # 步长
MIN_RATIO = 0.35     # 窗口内命中的 2 字片段比例
MIN_SENT = 4         # 窗口内至少几句


def _zh(s):
    import re
    return ''.join(re.findall(r'[\u4e00-\u9fff]', s or ''))


def _pairs(s):
    z = _zh(s)
    return {z[i:i + 2] for i in range(len(z) - 1)} if len(z) >= 2 else set()


def load_corpus():
    """返回 {title: {'artist':..,'lines':[..],'pairs':set}}"""
    out = {}

    def add(title, artist, lines):
        z = _zh(''.join(lines))
        if len(z) < MIN_LEN:
            return
        key = (title or '').strip()
        if not key:
            return
        rec = out.setdefault(key, {'artist': artist, 'lines': [], 'pairs': set()})
        rec['artist'] = rec['artist'] or artist
        rec['lines'].extend(lines)
        rec['pairs'] |= _pairs(''.join(lines))

    oc = ROOT / 'queue' / 'official_cache.json'
    if oc.exists():
        for k, v in json.loads(oc.read_text(encoding='utf-8')).items():
            title, _, artist = k.partition('|')
            lines = v[0] if isinstance(v, (list, tuple)) and v else v
            add(title, artist, lines or [])
    for f in ('songs_index.json', 'songs_index_new.json'):
        p = ROOT / 'queue' / f
        if not p.exists():
            continue
        for x in json.loads(p.read_text(encoding='utf-8')):
            lines = [ln.split(']', 1)[-1] for ln in (x.get('lrc') or '').splitlines()]
            add(x.get('title'), x.get('artist'), lines)
    return {k: v for k, v in out.items() if len(v['pairs']) >= 8}


def detect(bvid, page=1):
    tag = f'{bvid}_p{page}' if page > 1 else bvid
    asr = ROOT / 'queue' / 'asr_v3' / f'{tag}.jsonl'
    if not asr.exists():
        return []
    recs = [json.loads(l) for l in asr.read_text(encoding='utf-8').splitlines() if l.strip()]
    corpus = load_corpus()
    if not recs or not corpus:
        return []
    dur = recs[-1]['end']
    hits = []
    t = 0.0
    while t + WIN <= dur + STEP:
        segs = [r for r in recs if r['end'] > t and r['start'] < t + WIN]
        if len(segs) >= MIN_SENT:
            win_pairs = set()
            for r in segs:
                win_pairs |= _pairs(r['text'])
            if win_pairs:
                for title, rec in corpus.items():
                    if not rec['pairs']:
                        continue
                    ratio = len(win_pairs & rec['pairs']) / len(rec['pairs'])
                    if ratio >= MIN_RATIO:
                        hits.append((t, title, round(ratio, 3), rec['artist']))
        t += STEP
    # 同一首歌的连续窗口合并
    merged = []
    for t, title, ratio, artist in sorted(hits):
        if merged and merged[-1][1] == title and t - merged[-1][2] <= STEP * 1.5:
            merged[-1][2] = t + WIN
            merged[-1][3] = max(merged[-1][3], ratio)
        else:
            merged.append([t, title, t + WIN, ratio, artist])
    out = [{'start': round(a, 1), 'dur': round(c - a, 1), 'title': b, 'artist': e,
            'ratio': d, 'src': 'corpus'} for a, b, c, d, e in merged]
    # 后处理：同歌名且时间重叠/相邻的段合并，只保留最长的一条
    out.sort(key=lambda r: (r['title'], r['start']))
    plan = []
    for r in out:
        if plan and plan[-1]['title'] == r['title'] and \
                r['start'] <= plan[-1]['start'] + plan[-1]['dur'] + 30:
            a = plan[-1]['start']
            b = max(plan[-1]['start'] + plan[-1]['dur'], r['start'] + r['dur'])
            if ('live' in plan[-1]['title'].lower()) and ('live' not in r['title'].lower()):
                plan[-1]['title'], plan[-1]['artist'] = r['title'], r['artist']
            plan[-1]['dur'] = round(b - a, 1)
            plan[-1]['ratio'] = max(plan[-1]['ratio'], r['ratio'])
        else:
            plan.append(dict(r))
    # 同一时间段只要一首：按命中率保留最优（防止 R&B/Live 等同曲异名重复出片）
    plan.sort(key=lambda r: -r['ratio'])
    keep = []
    for r in plan:
        if any(not (r['start'] + r['dur'] <= k['start'] or k['start'] + k['dur'] <= r['start'] + 20)
               for k in keep):
            continue
        keep.append(r)
    keep.sort(key=lambda r: r['start'])
    return keep


if __name__ == '__main__':
    bvid = sys.argv[1] if len(sys.argv) > 1 else 'BV16j411Y7sS'
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    res = detect(bvid, page)
    for r in res:
        print(f"{r['start']:7.0f}s +{r['dur']:5.0f}s  {r['title'][:18]:<20}{r['artist'][:12]:<14}命中{r['ratio']:.0%}")
    print(f'共 {len(res)} 段')