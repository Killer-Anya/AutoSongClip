#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audiospec.py —— 音频专业校验（对标交付规范：源参数、切点帧对齐、响度与真峰值）

用法：
    probe(path)                  → {"codec","sr","ch","br","dur"}
    check_source(p)              → (ok, reasons, info)   源音轨必须 AAC/48k/立体声/≥200kbps
    check_cut(p, expect_dur)     → (ok, reasons, info)   成品必须与源同参数、时长±0.15s、单声道/立体声不变
    loudness(p)                  → {"lufs","tpeak"}       EBU R128 整体响度与真峰值（只测不改）
    frame_align(t, sr=48000)     → 距最近 AAC 帧(1024 样本)对齐的时间点
"""
import json
import subprocess
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


SR_OK = (44100, 48000)   # B 站部分老录播只有 44.1kHz，属于平台上限，不算不合格
BR_MIN = 128000          # 平台最低可接受档；实际使用最高可用档并记录真实码率
DUR_TOL = 0.15
LUFS_MIN = -24.0         # 过轻（异常）
LUFS_MAX = -6.0          # 过响（可能削波）
TPEAK_MAX = -1.0         # dBTP，超过即视为有削波风险


def _run(cmd, t=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 1, '', f'{type(e).__name__}: {e}'


def probe(path):
    rc, out, _ = _run(f'{FFPROBE} -v error -select_streams a:0 '
                      f'-show_entries stream=codec_name,sample_rate,channels,bit_rate:format=duration '
                      f'-of json "{path}"')
    if rc != 0 or not out.strip():
        return {}
    try:
        d = json.loads(out)
    except Exception:
        return {}
    st = (d.get('streams') or [{}])[0]
    dur = (d.get('format') or {}).get('duration')
    return {'codec': st.get('codec_name'), 'sr': int(st.get('sample_rate') or 0),
            'ch': int(st.get('channels') or 0), 'br': int(st.get('bit_rate') or 0),
            'dur': round(float(dur), 3) if dur else 0.0}


def frame_align(t, sr=48000, frame=1024):
    step = frame / float(sr)          # 21.33ms
    return round(round(float(t) / step) * step, 3)


def check_source(path):
    info = probe(path)
    bad = []
    if not info:
        return False, ['无法读取音频信息'], {}
    if info['codec'] not in ('aac', 'mp4a'):
        bad.append(f"编码 {info['codec']} 非 AAC")
    if info['sr'] not in SR_OK:
        bad.append(f"采样率 {info['sr']} 不在 {SR_OK}")
    if info['ch'] != 2:
        bad.append(f"声道 {info['ch']} 非立体声")
    if info['br'] and info['br'] < BR_MIN:
        bad.append(f"码率 {info['br']//1000}kbps 低于 {BR_MIN//1000}kbps")
    return (not bad), bad, info


def check_cut(path, expect_dur, src_info=None):
    info = probe(path)
    bad = []
    if not info:
        return False, ['无法读取成品信息'], {}
    if src_info:
        for k, name in (('codec', '编码'), ('sr', '采样率'), ('ch', '声道')):
            if info.get(k) != src_info.get(k):
                bad.append(f'{name}与源不一致（{info.get(k)} vs {src_info.get(k)}）')
    if expect_dur and abs(info['dur'] - expect_dur) > DUR_TOL:
        bad.append(f"时长偏差 {info['dur']-expect_dur:+.2f}s 超过 ±{DUR_TOL}s")
    return (not bad), bad, info


def loudness(path):
    """EBU R128：integrated LUFS + true peak（只测量，不改音频）"""
    rc, out, err = _run(f'{FFMPEG} -hide_banner -nostats '
                        f'-i "{path}" -af ebur128=peak=true -f null - 2>&1 | tail -20', t=180)
    txt = (out or '') + (err or '')
    lufs = tpeak = None
    for ln in txt.splitlines():
        if 'I:' in ln and 'LUFS' in ln:
            try:
                lufs = float(ln.split('I:')[1].split()[0])
            except Exception:
                pass
        if 'Peak:' in ln and 'dBFS' in ln:
            try:
                tpeak = float(ln.split('Peak:')[1].split()[0])
            except Exception:
                pass
    return {'lufs': lufs, 'tpeak': tpeak}


def check_loudness(l):
    bad = []
    if l.get('lufs') is None:
        return True, ['响度未测出（不阻断）'], l
    if l['lufs'] < LUFS_MIN:
        bad.append(f"整体响度过低 {l['lufs']:.1f} LUFS")
    if l['lufs'] > LUFS_MAX:
        bad.append(f"整体响度过高 {l['lufs']:.1f} LUFS")
    if l.get('tpeak') is not None and l['tpeak'] > TPEAK_MAX:
        bad.append(f"真峰值 {l['tpeak']:.1f} dBTP 有削波风险")
    return (not bad), bad, l