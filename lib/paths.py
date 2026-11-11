#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paths.py —— 统一的路径与外部命令解析（开源可移植）

优先顺序：
  1) 环境变量 SONG_CUT_HOME 指定项目根目录
  2) 本文件所在位置的上两级目录（lib/ 的父目录）
  3) 当前工作目录

外部命令：
  * ffmpeg / ffprobe：优先 SONG_CUT_FFMPEG / SONG_CUT_FFPROBE，其次项目内 bin2/，最后 PATH
  * Python 解释器：环境变量 SONG_CUT_PY（默认 python3）
  * 依赖目录：SONG_CUT_PYTHONPATH（默认空，即用系统/虚拟环境）
"""
import os
import shutil
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


def _root():
    env = os.environ.get('SONG_CUT_HOME')
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    cand = here.parent.parent
    if (cand / 'pipeline').is_dir() or (cand / 'lib').is_dir():
        return cand
    return Path.cwd()


ROOT = _root()


def _which(env, name, local):
    v = os.environ.get(env)
    if v:
        return v
    p = ROOT / local
    if p.exists():
        return str(p)
    return shutil.which(name) or name


FFMPEG = _which('SONG_CUT_FFMPEG', 'ffmpeg', 'bin2/ffmpeg')
FFPROBE = _which('SONG_CUT_FFPROBE', 'ffprobe', 'bin2/ffprobe')
PY = os.environ.get('SONG_CUT_PY', 'python3')
PYTHONPATH = os.environ.get('SONG_CUT_PYTHONPATH', '')
MODELS = Path(os.environ.get('SONG_CUT_MODELS', ROOT / 'models'))


def run_py(script, args=''):
    pre = f'env PYTHONPATH={PYTHONPATH} ' if PYTHONPATH else ''
    return f'{pre}{PY} {script} {args}'.strip()


def run_ff(tool, args=''):
    pre = f'env PYTHONPATH={PYTHONPATH} ' if PYTHONPATH else ''
    return f'{pre}{tool} {args}'.strip()