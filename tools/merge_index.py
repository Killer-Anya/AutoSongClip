#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_index.py —— 把旧版曲库索引合并进当前 songs_index.json（按 file 去重，不动已有 v3 条目）

用法: python3 tools/merge_index.py [旧索引.json]
默认取 queue/backups/songs_index_v2_20261108-0137.json
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


CUR = ROOT / 'queue' / 'songs_index.json'
OLD = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'queue' / 'backups' / 'songs_index_v2_20261108-0137.json'


def load(p):
    if not Path(p).exists():
        return []
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return []


def main():
    cur = load(CUR)
    old = load(OLD)
    have = {x.get('file') for x in cur}
    added = 0
    for x in old:
        if x.get('file') in have:
            continue
        x['legacy'] = True
        x.setdefault('lang', '国语')
        x.setdefault('style', '未分类')
        x.setdefault('date', '')
        cur.append(x)
        have.add(x.get('file'))
        added += 1
    # 排序：有日期的按日期，老歌（无日期）排在前面
    cur.sort(key=lambda x: (x.get('date') or '0000-00-00', x.get('no') or ''))
    CUR.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'合并完成：新增 {added} 首，当前共 {len(cur)} 首')


if __name__ == '__main__':
    main()