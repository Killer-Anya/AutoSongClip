#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_regions.py —— 纯音频的"有没有伴奏"检测，用来定位疑似唱歌区间（不依赖任何大模型）

思路：歌回的唱歌段一定有伴奏（低频持续能量 + 频谱较平），而纯说话段几乎没有低频底盘。
  1. 解码 16kHz 单声道
  2. 每 2 秒算：总 RMS、0~200Hz 低频能量占比
  3. 低频占比 > thr 且 RMS 高于噪声底 → 判为"有伴奏"
  4. 连续"有伴奏" ≥ min_dur 的段 → 候选歌曲区间

用法: python3 lib/audio_regions.py <音频或wav> [--json]
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
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


FF = FFMPEG
SR = 16000
WIN = 2.0            # 统计窗口（秒）
LOW_HZ = 220.0       # 低频上限
LOW_RATIO = 0.30     # 低频能量占比阈值
MIN_DUR = 40.0       # 最短歌曲片段
MAX_GAP = 8.0        # 允许的短暂中断


def to_wav(src, out='/tmp/areg.wav'):
    r = subprocess.run(f'{FF} -v error -y -i "{src}" -ar {SR} -ac 1 -f wav {out}',
                       shell=True, capture_output=True, text=True)
    return out if r.returncode == 0 else None


def analyse(wav):
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32) / 32768
    n = int(SR * WIN)
    rows = []
    for i in range(0, len(x) - n, n):
        seg = x[i:i + n]
        rms = float(np.sqrt(np.mean(seg ** 2) + 1e-12))
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / SR)
        tot = float(np.sum(spec ** 2) + 1e-12)
        low = float(np.sum(spec[freqs <= LOW_HZ] ** 2))
        rows.append((i / SR, rms, low / tot))
    return rows


def regions(rows):
    if not rows:
        return []
    rms_all = np.array([r[1] for r in rows])
    floor = float(np.percentile(rms_all, 20))
    out, cur = [], None
    for t, rms, low in rows:
        has_music = (low >= LOW_RATIO) and (rms > floor * 1.5)
        if has_music:
            if cur is None:
                cur = [t, t + WIN]
            else:
                if t - cur[1] <= MAX_GAP:
                    cur[1] = t + WIN
                else:
                    if cur[1] - cur[0] >= MIN_DUR:
                        out.append(cur)
                    cur = [t, t + WIN]
        else:
            if cur and cur[1] - cur[0] >= MIN_DUR and t - cur[1] > MAX_GAP:
                out.append(cur); cur = None
    if cur and cur[1] - cur[0] >= MIN_DUR:
        out.append(cur)
    return [{'start': round(a, 1), 'dur': round(b - a, 1)} for a, b in out]


def detect(src):
    wav = to_wav(src)
    if not wav:
        return []
    return regions(analyse(wav))


if __name__ == '__main__':
    p = sys.argv[1]
    res = detect(p)
    print(json.dumps(res, ensure_ascii=False))
    print(f'共 {len(res)} 段候选')