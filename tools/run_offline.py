#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_offline.py —— 限流期间的离线批量出片（不调用大模型）

对队列里"已有转写缓存 + 源音轨在"的场次依次跑 pipeline/pipe_offline.py。
已处理过的场次记录在 queue/offline_done.json，避免重复。

用法: python3 tools/run_offline.py [最多几场]
"""
import json
import subprocess
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


PY = PY_BIN
DONE = ROOT / 'queue' / 'offline_done.json'


def log(m):
    line = f'{time.strftime("%m-%d %H:%M:%S")} {m}'
    print(line, flush=True)
    with open(ROOT / 'logs' / 'offline.log', 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load(p, d):
    p = Path(p)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else d


def free_gb():
    out = subprocess.run('df -BG --output=avail / | tail -1', shell=True, capture_output=True, text=True).stdout.strip()
    return int(out.replace('G', '')) if out else 0


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    q = load(ROOT / 'queue' / 'streams_v3.json', [])
    done = load(DONE, [])
    n = 0
    for it in q:
        if n >= limit:
            break
        page = int(it.get('page') or 1)
        tag = f"{it['bvid']}_p{page}" if page > 1 else it['bvid']
        if tag in done:
            continue
        cache = ROOT / 'queue' / 'asr_v3' / f'{tag}.jsonl'
        src = ROOT / 'res' / f'{tag}.m4a'
        if not (cache.exists() and cache.stat().st_size > 1000 and src.exists()):
            continue
        if free_gb() < 5:
            log('磁盘不足，停止离线批处理'); break
        log(f'离线处理 {tag}（{it["title"][:24]} P{page}）')
        r = subprocess.run(f'{PY} {ROOT}/pipeline/pipe_offline.py {it["bvid"]} {page}',
                           shell=True, capture_output=True, text=True)
        tail = (r.stdout or '').strip().splitlines()[-3:]
        for ln in tail:
            log('   ' + ln[:120])
        if r.returncode == 0:
            done.append(tag)
            Path(DONE).write_text(json.dumps(done, ensure_ascii=False), encoding='utf-8')
        else:
            log(f'   失败：{(r.stderr or "")[-200:].strip()[-160:]}')
        n += 1
    log(f'本轮离线处理 {n} 场')


if __name__ == '__main__':
    main()