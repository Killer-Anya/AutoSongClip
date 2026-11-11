#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""text_sweep.py —— 纯文本扫场：不用大模型，靠网易云歌词核验在整场转写里找歌

做法：把整场转写按 120 秒窗口（步长 60 秒）切片，每片取若干中文片段去网易云搜歌，
      再把候选歌词与窗口文本做拼音/字面核验；命中就记录 (起止, 歌名, 艺人, 命中率)。
      相邻命中同一首歌的窗口合并成一个区间。

优点：不依赖 GLM，网易云可用即可；缺点：只认得出网易云能搜到的歌。

用法: python3 lib/text_sweep.py <bvid> [page]
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get('SONG_CUT_HOME') or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))

import identify2 as I2  # noqa: E402


WIN = 120.0
STEP = 60.0
MIN_RATIO = 0.42      # 歌词文字召回（窗口内）
MIN_WIN_HIT = 1       # 至少 1 个窗口命中即算候选


def load(tag):
    f = ROOT / 'queue' / 'asr_v3' / f'{tag}.jsonl'
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]


def sweep(recs):
    if not recs:
        return []
    dur = recs[-1]['end']
    hits = []
    t = 0.0
    while t < dur:
        segs = [r for r in recs if r['end'] > t and r['start'] < t + WIN]
        txt = ' '.join(r['text'] for r in segs)
        if len(I2._zh_only(txt)) >= 12:
            info = I2.identify_region(txt)
            if info.get('title') and (info.get('recall') or 0) >= MIN_RATIO:
                hits.append({'start': t, 'dur': WIN, 'title': info['title'],
                             'artist': info.get('artist', ''), 'ratio': info.get('recall') or 0})
        t += STEP
    plan = []
    for h in sorted(hits, key=lambda x: (x['title'], x['start'])):
        if plan and plan[-1]['title'] == h['title'] and h['start'] <= plan[-1]['start'] + plan[-1]['dur'] + 40:
            plan[-1]['dur'] = round(max(plan[-1]['start'] + plan[-1]['dur'],
                                       h['start'] + h['dur']) - plan[-1]['start'], 1)
            plan[-1]['ratio'] = max(plan[-1]['ratio'], h['ratio'])
        else:
            plan.append(dict(h))
    # 同一时间段只留命中率最高的一首
    plan.sort(key=lambda r: -r['ratio'])
    keep = []
    for r in plan:
        if any(not (r['start'] + r['dur'] <= k['start'] or k['start'] + k['dur'] <= r['start'] + 20)
               for k in keep):
            continue
        keep.append(r)
    keep.sort(key=lambda r: r['start'])
    return [k for k in keep if k['dur'] >= 60]


def main():
    bvid = sys.argv[1]
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    tag = f'{bvid}_p{page}' if page > 1 else bvid
    res = sweep(load(tag))
    for r in res:
        print(f"{r['start']:7.0f}s +{r['dur']:5.0f}s  {r['title'][:18]:<20}{r['artist'][:12]:<14}{r['ratio']:.0%}")
    print(f'共 {len(res)} 段')


if __name__ == '__main__':
    main()