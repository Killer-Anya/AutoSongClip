#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bound_lyric.py —— 用歌词本身校正切歌边界

ASR 分类得到的区间常常偏窄：漏掉第一段主歌，或者提前收尾。
这里用官方歌词的首句/末句去全场转写里找真正起止点。

refine(segs, lines, t0, t1) -> (na, nb)
  segs  全场转写段 [{start,end,text}]
  lines 官方歌词行（按顺序，无时间）
  t0,t1 ASR 分类给出的粗略区间
"""
import re

_BACK = 150.0   # 向前最多回溯 150 秒找首句
_FWD = 180.0    # 向后最多延伸 180 秒找末句


def _zh(s):
    return ''.join(re.findall(r'[\u4e00-\u9fff]', s or ''))


def _score(line, text):
    """歌词行与转写段的字面吻合度 0~1"""
    a, b = set(_zh(line)), set(_zh(text))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def _best(segs, line, lo, hi):
    best, bt = 0.0, None
    for s in segs:
        if s['end'] < lo or s['start'] > hi:
            continue
        sc = _score(line, s['text'])
        if sc > best:
            best, bt = sc, s['start']
    return best, bt


def refine(segs, lines, t0, t1, min_score=0.55):
    """返回校正后的 (na, nb)；找不到合适匹配就原样返回"""
    zh_lines = [l for l in (lines or []) if len(_zh(l)) >= 4]
    if not zh_lines:
        return t0, t1
    na, nb = float(t0), float(t1)

    # 1) 用开头三句里最容易匹配的一句，向前找最早命中
    head, tail = zh_lines[:3], zh_lines[-3:]
    starts = []
    for ln in head:
        sc, t = _best(segs, ln, t0 - _BACK, t0 + 45)
        if sc >= min_score and t is not None:
            starts.append(t)
    if starts:
        na = min(starts)

    # 2) 用结尾三句向后找最晚命中
    ends = []
    for ln in tail:
        best, bt = 0.0, None
        for s in segs:
            if s['end'] < t1 - 60 or s['start'] > t1 + _FWD:
                continue
            sc = _score(ln, s['text'])
            if sc > best:
                best, bt = sc, s['end']
        if best >= min_score and bt is not None:
            ends.append(bt)
    if ends:
        nb = max(ends)

    if nb - na < 60:            # 校正后过短，说明匹配不可信，回退
        return t0, t1
    return na, nb
