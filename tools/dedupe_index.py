#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dedupe_index.py —— 清理索引里的重复条目（同一场同一首歌、起点相差 <60s 视为重跑产生的重复）"""
import json
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




def dedupe(entries):
    out = []
    for x in entries:
        dup = None
        for y in out:
            if (x.get('bvid') == y.get('bvid') and x.get('title') == y.get('title')
                    and x.get('artist') == y.get('artist')
                    and abs(float(x.get('na') or 0) - float(y.get('na') or 0)) < 60):
                dup = y
                break
        if dup is None:
            out.append(x)
        elif float(x.get('dur') or 0) > float(dup.get('dur') or 0):
            out[out.index(dup)] = x
    for i, x in enumerate(out, 1):
        x['no'] = str(i).zfill(3)
    return out


if __name__ == '__main__':
    p = ROOT / 'queue' / 'songs_index_new.json'
    d = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    n = len(d)
    d = dedupe(d)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'去重：{n} → {len(d)}')