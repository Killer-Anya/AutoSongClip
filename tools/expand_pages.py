#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expand_pages.py —— 检查每场录播是否有多 P（P1/P2…），把多出来的分P也排进队列

用法:
  python3 tools/expand_pages.py --report    只报告
  python3 tools/expand_pages.py --apply     写入队列（新增分P作为独立场次）
"""
import json
import sys
import time
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


sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))
Q = ROOT / 'queue' / 'streams_v3.json'
REPORT = ROOT / 'queue' / 'multipage_report.json'


def main():
    apply = '--apply' in sys.argv
    import bili
    cookie = bili.get_buvid()
    q = json.loads(Q.read_text(encoding='utf-8'))
    have = {(it['bvid'], int(it.get('page') or 1)) for it in q}
    report, added = [], 0
    for it in q:
        if it.get('page') and int(it.get('page')) > 1:
            continue
        try:
            info = bili.video_info(it['bvid'], cookie)
        except Exception as e:
            print(f"  {it['bvid']} 查询失败 {type(e).__name__}: {e}", flush=True)
            continue
        pages = info['pages']
        if len(pages) <= 1:
            continue
        report.append({'bvid': it['bvid'], 'title': it['title'],
                       'pages': [{'page': p['page'], 'part': p['part'], 'dur': p['duration']} for p in pages]})
        print(f"  {it['bvid']} 共 {len(pages)}P: " + ' | '.join(f"P{p['page']} {p['duration']//60}分" for p in pages), flush=True)
        if not apply:
            continue
        base_idx = int(it.get('idx') or 0)
        for p in pages[1:]:
            key = (it['bvid'], int(p['page']))
            if key in have:
                continue
            nidx = base_idx + p['page'] - 1
            while any(int(x.get('idx') or 0) == nidx and x['bvid'] != it['bvid'] for x in q):
                nidx += 1000
            q.append({'idx': nidx, 'bvid': it['bvid'], 'page': p['page'],
                      'title': f"{it['title'][:40]} P{p['page']} {p['part']}"[:80],
                      'status': 'pending', 'tries': 0})
            have.add(key)
            added += 1
            print(f"    + 排入 P{p['page']}（{p['duration']//60} 分钟）", flush=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'多P场次 {len(report)} 个，新增分P {added} 个')
    if apply:
        Q.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()