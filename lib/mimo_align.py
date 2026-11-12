#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mimo_align.py —— 用云端音频模型的句级时间做"锚点"修正排轴（实验，默认不采用）

实验背景见 docs/开发日志.md 的 MiMo 转写实验：
  MiMo 句级时间与本地 whisper 相差 3~5 秒，用作锚点会把同步率从 87~97% 拉低到 36~52%，
  因此**默认不采用**，仅在 MIMO_ANCHOR=1 时做对比记录。

对外接口：get_anchors() / fuse() / build_lrc()
"""
import difflib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get('SONG_CUT_HOME') or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))

import mimo  # noqa: E402

PROMPT = ('这段是一首歌的现场演唱片段。请把听到的歌词逐句输出，每行格式：相对秒数|歌词。'
          '相对秒数=该句开始的时刻，以这段音频开头为 0，保留一位小数。'
          '只输出这些行，不要解释、不要编号、不要加歌名；听不清的词写（？），不要编造。'
          '没有演唱的部分不要输出。')


def _zh(s):
    return ''.join(re.findall(r'[\u4e00-\u9fff]', s or ''))


def _sim(a, b):
    za, zb = _zh(a), _zh(b)
    return difflib.SequenceMatcher(None, za, zb).ratio() if za and zb else 0.0


def parse_lines(txt):
    out = []
    for ln in (txt or '').splitlines():
        ln = ln.strip().strip('`')
        m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*(?:[-–~]\s*\d+(?:\.\d+)?)?\s*[\|,，:：]\s*(.+)$', ln)
        if not m:
            continue
        body = re.sub(r'^(?:SPEAKER[_-]?\d+|说话人\d*)\s*[:：]\s*', '', m.group(2)).strip()
        if len(_zh(body)) >= 2:
            out.append((float(m.group(1)), body))
    out.sort(key=lambda x: x[0])
    return out


def _match(off_lines, heard):
    """官方歌词行 ↔ 云端句 的单调对齐（DP），返回 [(行号, 秒)]"""
    n, m = len(off_lines), len(heard)
    if not n or not m:
        return []
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]
    GAP = -0.12
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP; bt[i][0] = 2
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + GAP; bt[0][j] = 3
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = _sim(off_lines[i - 1], heard[j - 1][1])
            best, arg = dp[i - 1][j - 1] + (s if s >= 0.34 else -0.08), 1
            if dp[i - 1][j] + GAP > best:
                best, arg = dp[i - 1][j] + GAP, 2
            if dp[i][j - 1] + GAP > best:
                best, arg = dp[i][j - 1] + GAP, 3
            dp[i][j], bt[i][j] = best, arg
    pairs, i, j = [], n, m
    while i > 0 and j > 0:
        if bt[i][j] == 1:
            if _sim(off_lines[i - 1], heard[j - 1][1]) >= 0.34:
                pairs.append((i - 1, heard[j - 1][0]))
            i, j = i - 1, j - 1
        elif bt[i][j] == 2:
            i -= 1
        else:
            j -= 1
    pairs.sort()
    return pairs


def get_anchors(cut_audio, dur, official_lines, min_hit=5):
    off_lines = [l for l in official_lines if len(_zh(l)) >= 2]
    if not off_lines or not Path(cut_audio).exists():
        return [], {'ok': False, 'why': '缺输入'}
    wav = mimo.clip(cut_audio, 0.0, float(dur) + 0.5, '/tmp/mimo_anchor.wav')
    if not wav:
        return [], {'ok': False, 'why': '切片失败'}
    txt, usage = mimo._ask(PROMPT, [wav], max_tokens=2500, timeout=240)
    heard = parse_lines(txt)
    if len(heard) < 3:
        return [], {'ok': False, 'why': f'云端只给出 {len(heard)} 句', 'usage': usage}
    pairs = _match(off_lines, heard)
    mono, last = [], -1.0
    for idx, tt in pairs:
        if tt >= last:
            mono.append((idx, round(float(tt), 2))); last = tt
    if len(mono) < min_hit:
        return [], {'ok': False, 'why': f'锚点仅 {len(mono)} 个', 'heard': len(heard), 'usage': usage}
    return mono, {'ok': True, 'anchors': len(mono), 'heard': len(heard), 'usage': usage}


def fuse(rows, anchors, lines, dur):
    """锚点行用云端时间，其余在锚点之间按字数插值"""
    off_lines = [l for l in lines if len(_zh(l)) >= 2]
    if not anchors or not off_lines:
        return None
    times = [None] * len(off_lines)
    for i, t in anchors:
        if 0 <= i < len(times):
            times[i] = max(0.0, min(float(dur), t))
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        return None
    for k in range(known[0]):
        times[k] = max(0.0, times[known[0]] - (known[0] - k) * 2.2)
    for k in range(known[-1] + 1, len(times)):
        times[k] = min(float(dur), times[known[-1]] + (k - known[-1]) * 2.2)
    for a, b in zip(known, known[1:]):
        if b - a <= 1:
            continue
        span = times[b] - times[a]
        chars = [max(1, len(_zh(off_lines[k]))) for k in range(a, b)]
        total, acc = sum(chars), 0
        for k, c in zip(range(a, b), chars):
            acc += c
            times[k] = times[a] + span * acc / total
    last = 0.0
    for k in range(len(times)):
        times[k] = max(times[k], last + 0.6); last = times[k]
    return '\n'.join(f'[{int(t)//60:02d}:{t%60:05.2f}]{off_lines[k]}' for k, t in enumerate(times))


def build_lrc(cut_audio, official_lines, dur):
    off_lines = [l for l in official_lines if len(_zh(l)) >= 2]
    wav = mimo.clip(cut_audio, 0.0, float(dur) + 0.5, '/tmp/mimo_align.wav')
    if not wav:
        return '', {'ok': False, 'why': '切片失败'}
    txt, usage = mimo._ask(PROMPT, [wav], max_tokens=2500, timeout=240)
    heard = parse_lines(txt)
    if len(heard) < 3:
        return '', {'ok': False, 'why': f'云端只给出 {len(heard)} 句', 'usage': usage}
    pairs = _match(off_lines, heard)
    if len(pairs) < 3:
        return '', {'ok': False, 'why': f'匹配行数不足 {len(pairs)}', 'heard': len(heard)}
    lrc = fuse([], pairs, off_lines, dur)
    return lrc or '', {'ok': bool(lrc), 'hit': len(pairs), 'lines': len(off_lines),
                       'heard': len(heard), 'usage': usage}
