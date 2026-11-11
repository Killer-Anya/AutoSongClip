#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_published.py —— 抽查已入库成品：用缓存转写独立重算关键指标

用法: python3 tools/audit_published.py [数量]
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get('SONG_CUT_HOME') or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))

import qc as QC          # noqa: E402
import dtw_align as D    # noqa: E402
import align_qwen as AQ  # noqa: E402


def to_sec(st):
    if not st:
        return None
    parts = str(st).split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 6
    idxf = ROOT / 'queue' / 'songs_index_new.json'
    idx = json.loads(idxf.read_text(encoding='utf-8')) if idxf.exists() else []
    bad = []
    print(f'{"歌名":<18}{"锚定":>6}{"召回":>6}{"同步":>6}{"中位":>7}{"首行":>7}{"末行":>7}{"时长":>7}')
    for x in idx[:limit]:
        bvid = x.get('bvid')
        na = x.get('na') if x.get('na') is not None else to_sec(x.get('stream_time'))
        page = int(x.get('page') or 1)
        segf = ROOT / 'queue' / 'asr_v3' / (f'{bvid}_p{page}.jsonl' if page > 1 else f'{bvid}.jsonl')
        if not (segf.exists() and na is not None):
            print(f"{x['title'][:16]:<18} 无缓存转写，跳过")
            continue
        recs = [json.loads(l) for l in segf.read_text(encoding='utf-8').splitlines() if l.strip()]
        dur = float(x.get('dur') or 0)
        segs = [{'start': s['start'] - na, 'end': s['end'] - na, 'text': s['text'],
                 'words': [[w[0] - na, w[1] - na, w[2]] for w in (s.get('words') or [])]}
                for s in recs if s['end'] > na - 1 and s['start'] < na + dur + 1]
        lines = (AQ.official(x['title'], x['artist']) or [[], ''])[0]
        rows = QC.parse(x.get('lrc') or '')
        amap = D.dtw_map(lines, segs) if lines else {}
        ok, why, m = QC.check(x.get('lrc') or '', lines, amap, segs, dur)
        print(f"{x['title'][:16]:<18}{m['anchor']:>6.0%}{m['recall']:>6.0%}"
              f"{m['err_rate']:>6.0%}{(m['err_med'] or 0):>7.2f}{m['first']:>7.1f}{m['last']:>7.1f}{m['cut']:>7.0f}"
              + ('' if ok else '  ⚠' + '；'.join(why)[:40]))
        if not ok:
            bad.append((x['title'], why))
    print(f'\n抽查 {min(limit, len(idx))} 首，不合格 {len(bad)} 首')
    for t, w in bad:
        print('  ✗', t, '：', '；'.join(w)[:70])


if __name__ == '__main__':
    main()
