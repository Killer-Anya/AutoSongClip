#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""boundary.py —— 按广播/卡拉OK通行做法找切点
方法：
 1) 20ms 短时 RMS → dBFS
 2) 噪声底 = 10 分位；静音阈值 = max(噪声底+8dB, -55 dBFS)
 3) 静音段要求 ≥350ms（行业常见 300–500ms 起音/收尾判定）
 4) 起点：从首句人声往回，找到最近静音段的**结束点**（音乐真正开始处），再提前 100ms
 5) 终点：从末句人声往后，找到最近静音段的**开始点**（人声/尾音结束），再延后 150ms
返回 (start, end)
"""
import wave
import numpy as np

SR = 16000


def load_env(wav_path, win_ms=20, hop_ms=10):
    with wave.open(wav_path) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32)/32768
    win = int(SR*win_ms/1000); hop = int(SR*hop_ms/1000)
    n = max(1, (len(x)-win)//hop)
    env = np.array([np.sqrt(np.mean(x[i*hop:i*hop+win]**2)+1e-12) for i in range(n)])
    return 20*np.log10(env+1e-12), hop_ms/1000.0


def find(env_db, hop, anchor_s, min_sil=0.50, back=20.0, fwd=12.0, ladder=None):
    """在锚点前后找合规静音段。阈值分多级放宽，保证"切在静音里"这件事能做得到。

    阈值序列（dBFS，相对噪声底）：
      第 1 级 floor+6（严格） → floor+10 → floor+14 → -25（最宽松）
    返回 (start, end, ok_start, ok_end)
    """
    floor = float(np.percentile(env_db, 10))
    if ladder is None:
        ladder = [floor + 6.0, floor + 10.0, floor + 14.0, -25.0]
    ladder = [float(x) for x in ladder]

    def runs_at(thr):
        silent = env_db < thr
        out, i = [], 0
        while i < len(silent):
            if silent[i]:
                j = i
                while j + 1 < len(silent) and silent[j + 1]:
                    j += 1
                if (j - i + 1) * hop >= min_sil:
                    out.append((i * hop, (j + 1) * hop))
                i = j + 1
            else:
                i += 1
        return out

    runs = []
    used_thr = None
    for thr in ladder:
        r = runs_at(thr)
        if r:
            runs, used_thr = r, thr
            break
    if not runs:
        return round(max(0.0, anchor_s - 3.0), 3), round(anchor_s + 2.0, 3), False, False

    # 起点：锚点前 20 秒内、离锚点最近的静音段结束点
    ok_s, start = False, anchor_s
    for a, b in runs:
        if anchor_s - back <= b <= anchor_s + 0.3 and (not ok_s or b > start):
            ok_s, start = True, b
    if ok_s:
        start = max(0.0, start - 0.15)
    else:
        start = max(0.0, anchor_s - 3.0)

    # 终点：锚点后 12 秒内最早的静音段起点
    ok_e, end = False, anchor_s
    for a, b in runs:
        if anchor_s - 0.3 <= a <= anchor_s + fwd:
            ok_e, end = True, a
            break
    if ok_e:
        end = min(anchor_s + fwd, end + 0.25)
    else:
        end = anchor_s + 2.0
    find.last_thr = used_thr          # 便于日志记录本次用了哪一级阈值
    find.last_floor = floor
    return round(start, 3), round(end, 3), ok_s, ok_e
