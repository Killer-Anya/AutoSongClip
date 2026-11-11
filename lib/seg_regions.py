#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seg_regions.py —— 用逐句标签合并歌唱区间"""
import json, sys
from pathlib import Path


def main():
    recs = [json.loads(l) for l in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines() if l.strip()]
    recs = [r for r in recs if r['text'].strip()]
    for i, r in enumerate(recs, 1):
        r['i'] = i
    lab = {x['i']: x['k'] for x in json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))}
    MIN_S = float(sys.argv[4]) if len(sys.argv) > 4 else 90.0
    TOL_S = float(sys.argv[5]) if len(sys.argv) > 5 else 6.0
    out = Path(sys.argv[3])

    runs, cur = [], []
    gap = 0.0
    for r in recs:
        k = lab.get(r['i'], '?')
        if k == 's':
            if cur and r['start'] - cur[-1]['end'] > TOL_S:
                runs.append(cur); cur = []
            cur.append(r)
        elif k == '?':
            continue
        else:
            if cur: runs.append(cur); cur = []
    if cur: runs.append(cur)

    regions = []
    for run in runs:
        a, b = run[0]['start'], run[-1]['end']
        if b - a < MIN_S:
            continue
        txt = ''.join(x['text'] for x in run)
        regions.append({'start': round(a, 1), 'end': round(b, 1), 'dur': round(b - a, 1),
                        'n': len(run), 'text': txt.strip()})
    out.write_text(json.dumps(regions, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{len(runs)} 段 -> {len(regions)} 个候选(≥{MIN_S:.0f}s)')
    for i, r in enumerate(regions, 1):
        print(f"{i:>2} {int(r['start'])//60:>2}:{int(r['start'])%60:02d}-{int(r['end'])//60:>2}:{int(r['end'])%60:02d} {r['dur']:>6.1f}s n={r['n']:>3} | {r['text'][:44]}")


if __name__ == "__main__":
    main()
