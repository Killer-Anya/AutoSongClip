#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_new.py —— 把新版精切（queue/songs_index_new.json）合并上架到网站

用法:
  python3 tools/publish_new.py --dry     只报告将要上架多少首
  python3 tools/publish_new.py           合并进 queue/songs_index.json 并重建页面

规则：
  * 旧版（235 首）保留在索引里，标记 batch='旧版'
  * 新版标 batch='精切版'
  * 同一成品文件不重复；新版优先（同名旧条目会被保留但分属不同批次）
"""
import json
import subprocess
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
NEW = ROOT / 'queue' / 'songs_index_new.json'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8')) if Path(p).exists() else []


def main():
    dry = '--dry' in sys.argv
    cur = load(CUR)
    new = load(NEW)
    for x in cur:
        x.setdefault('batch', '旧版')
    for x in new:
        x['batch'] = '精切版'
    by_file = {x['file']: x for x in cur}
    added = 0
    for x in new:
        if x['file'] not in by_file:
            added += 1
        by_file[x['file']] = x
    merged = list(by_file.values())
    merged.sort(key=lambda x: (x.get('batch') != '精切版', x.get('date') or '', str(x.get('no') or '')))
    print(f'旧版 {len(cur)} 首，新版 {len(new)} 首，合并后 {len(merged)} 首（新增 {added}）')
    if dry:
        return
    CUR.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding='utf-8')
    result = subprocess.run(
        [PY_BIN, ROOT / 'lib/build_site.py'], capture_output=True, text=True,
    )
    print(result.stdout.strip() or result.stderr.strip())
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
