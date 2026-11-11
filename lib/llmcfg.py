#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llmcfg.py —— 文本判断类大模型的统一配置

优先级：环境变量 JUDGE_* > run/judge.env > 默认（同济 GLM 本机代理）
切换实现时只需改写 run/judge.env，不必改代码。
"""
import json
import os
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


ENVF = ROOT / 'run' / 'judge.env'

DEFAULT = {
    'api': 'http://127.0.0.1:18090/v1/chat/completions',
    'health': 'http://127.0.0.1:18090/v1/models',
    'key': os.environ.get('TONGJI_API_KEY', ''),
    'model': 'GLM-5.3-Flash',
    'tongji': True,
}


def _load():
    cfg = dict(DEFAULT)
    if ENVF.exists():
        try:
            cfg.update({k: v for k, v in json.loads(ENVF.read_text(encoding='utf-8')).items() if v})
        except Exception:
            pass
    for k in ('api', 'health', 'key', 'model'):
        v = os.environ.get('JUDGE_' + k.upper())
        if v:
            cfg[k] = v
    if 'tongji' not in cfg or os.environ.get('JUDGE_API'):
        cfg['tongji'] = 'tongji' in cfg['api']
    return cfg


CFG = _load()
API = CFG['api']
HEALTH = CFG['health']
KEY = CFG['key']
MODEL = CFG['model']
# 通义/GLM 才认的思考开关，DeepSeek 不认（按 api 地址判断，避免配置不一致时把参数发错家）
_IS_TONGJI = ('127.0.0.1:18090' in API) or ('tongji' in API.lower())
EXTRA = {'chat_template_kwargs': {'enable_thinking': False}} if _IS_TONGJI else {}


def ensure_online(timeout=90):
    """同济通道掉线时自动重新连接（只发 on，不触发 dsh-web 重启）"""
    import json as _j
    import socket as _s
    import time as _t
    import urllib.request as _u
    if not _IS_TONGJI:
        return True

    def _probe():
        try:
            req = _u.Request(HEALTH)
            req.add_header('Authorization', 'Bearer ' + KEY)
            with _u.urlopen(req, timeout=12) as r:
                return r.status == 200
        except Exception:
            return False

    if _probe():
        return True
    try:
        sk = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        sk.settimeout(timeout)
        sk.connect('/run/tongji-vpn.sock')
        sk.sendall(b'on')
        while sk.recv(65536):
            pass
        sk.close()
    except Exception:
        return False
    for _ in range(6):
        _t.sleep(5)
        if _probe():
            return True
    return False