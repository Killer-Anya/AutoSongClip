#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtw_align.py —— 拼音序列 DTW 强制对齐（歌词音节 ↔ ASR 音节+时间）"""
import re
try:
    import zhconv as _zc
except Exception:
    _zc = None
try:
    from pypinyin import lazy_pinyin as _py
except Exception:
    _py = None

GAP_L = 0.9   # 歌词侧跨过（ASR 没唱到/漏字）
GAP_A = 0.6   # 转写侧跨过（ASR 多出来的字）


def norm(s):
    s = re.sub(r'[^\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z]', '', s)
    if _zc is not None and s:
        try:
            s = _zc.convert(s, 'zh-cn')
        except Exception:
            pass
    return s


def syls(s):
    out = []
    s = norm(s)
    if not s:
        return out
    for run in re.findall(r'[\u4e00-\u9fff]+|[\u3040-\u30ff]+|[\uac00-\ud7af]+|[A-Za-z]+', s):
        if re.match(r'[\u4e00-\u9fff]', run):
            out.extend(_py(run) if _py is not None else list(run))
        elif re.match(r'[A-Za-z]', run):
            out.append(run.lower())
        else:
            out.extend(list(run))          # 假名/韩文按字对齐
    return [x for x in out if x]


def cost(a, b):
    if a == b:
        return 0.0
    if a and b and a[0] == b[0]:
        return 0.3
    return 1.0


def dtw_map(lines, segs):
    """返回 {歌词行号: (句号, 时间秒)}"""
    L, Lline = [], []
    for i, l in enumerate(lines, 1):
        ss = syls(l)
        L.extend(ss); Lline.extend([i] * len(ss))
    A, At, Aj = [], [], []
    for j, s in enumerate(segs, 1):
        for w in (s.get('words') or []):
            ws = syls(w[2])
            if not ws:
                continue
            a, b = float(w[0]), float(w[1])
            step = (b - a) / len(ws)
            for k, sy in enumerate(ws):
                A.append(sy); At.append(a + step * k); Aj.append(j)
    if not L or not A:
        return {}
    n, m = len(L), len(A)
    INF = float('inf')
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        dp[i][0] = i * GAP_L; bt[i][0] = 2
    for j in range(1, m + 1):
        dp[0][j] = j * GAP_A; bt[0][j] = 3
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = dp[i - 1][j - 1] + cost(L[i - 1], A[j - 1]); arg = 1
            v = dp[i - 1][j] + GAP_L
            if v < best:
                best, arg = v, 2
            v = dp[i][j - 1] + GAP_A
            if v < best:
                best, arg = v, 3
            dp[i][j] = best; bt[i][j] = arg
    hits = {}
    i, j = n, m
    while i > 0 and j > 0:
        k = bt[i][j]
        if k == 1:
            ln = Lline[i - 1]
            t = At[j - 1]
            # 记录该行所有命中音节，最后取最早的那个（行首）
            if ln not in hits or t < hits[ln][1]:
                hits[ln] = (Aj[j - 1], t)
            i -= 1; j -= 1
        elif k == 2:
            i -= 1
        else:
            j -= 1
    return hits
