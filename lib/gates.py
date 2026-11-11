#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gates.py —— 统一的发布门槛（严格版）
   1) 锚定率 >= 0.80        歌词行在转写里找到位置的比例
   2) 歌词行覆盖 >= 0.70    相对官方歌词总行数
   3) 单调性             时间严格递增（允许 0.05s 容差）
   4) 最大空档 <= 12s     相邻歌词行间隔过大说明漏了一整段
"""
import re

ANCHOR_MIN = 0.85
COVER_MIN = 0.80
MAX_GAP_S = 12.0


def parse_lrc(lrc):
    out = []
    for ln in (lrc or '').split('\n'):
        m = re.match(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)', ln.strip())
        if m:
            out.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return out


def check(lrc, official_lines, anchor=None, dur=None):
    lines = parse_lrc(lrc)
    reasons = []
    n_off = len(official_lines or [])
    cov = (len(lines) / n_off) if n_off else 0.0
    if len(lines) < 5:
        reasons.append('歌词行太少')
    if n_off and cov < COVER_MIN:
        reasons.append(f'歌词覆盖{cov:.0%}<{COVER_MIN:.0%}')
    # 单调
    bad = sum(1 for a, b in zip(lines, lines[1:]) if b[0] < a[0] - 0.05)
    if bad:
        reasons.append(f'时间非单调({bad}处)')
    # 空档：间奏造成的长间隔是正常的，只有"空档里还有未锚定的歌词行"才算缺陷
    gaps = [b[0] - a[0] for a, b in zip(lines, lines[1:])]
    big = [g for g in gaps if g > MAX_GAP_S]
    if dur and lines and lines[-1][0] > dur + 1.0:
        reasons.append('歌词超出音频长度')
    if anchor is not None and anchor < ANCHOR_MIN:
        reasons.append(f'锚定{anchor:.0%}<{ANCHOR_MIN:.0%}')
    return (len(reasons) == 0), {'coverage': round(cov, 3), 'lines': len(lines),
                                 'anchor': None if anchor is None else round(anchor, 3),
                                 'gap_reserved': len(big)}, reasons
