#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_resume.py —— 限流期间每 10 分钟探一次同济，恢复后自动解除暂停"""
import json, subprocess, time
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


KEY = __import__('os').environ.get('TONGJI_API_KEY', '')
PAUSE = ROOT / 'run' / 'PAUSE'
LOG = ROOT / 'logs' / 'auto_resume.log'

def log(m):
    line = f'{time.strftime("%m-%d %H:%M:%S")} {m}'
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def probe():
    cmd = ("curl -s -m 25 -o /tmp/resume_probe.json -w '%{http_code}' "
           "http://127.0.0.1:18090/v1/chat/completions -H 'Authorization: Bearer " + KEY + "' "
           "-H 'Content-Type: application/json' -d '{\"model\":\"GLM-5.3-Flash\","
           "\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":4}'")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip()

def main():
    for _ in range(288):          # 最多轮询 48 小时
        code = probe()
        if code == '200':
            log('同济恢复（200），解除暂停')
            PAUSE.unlink(missing_ok=True)
            return
        log(f'仍不可用（{code or "timeout"}），10 分钟后再试')
        time.sleep(600)
    log('轮询结束仍未恢复，保留暂停状态')

if __name__ == '__main__':
    main()