#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cutwin.py —— 决定切片窗口（歌词对齐 → 真实演唱首末 → 静音吸附）

流程：
 1) 用官方歌词把 ASR 粗区间校正（bound_lyric.refine）
 2) 在该范围的全场转写切片上做拼音 DTW，取**首句命中时刻**与**末句命中时刻**
 3) 窗口 = [首句 - head_pad, 末句 + tail_pad]，再按静音段吸附（boundary.find）
 4) 返回 (na, nb, ok_start, ok_end, info)
"""
HEAD_PAD = 3.0     # 首句前留 3 秒（前奏/起唱气口）
TAIL_PAD = 4.0     # 末句后留 4 秒（尾音/收尾）
HEAD_MAX = 6.5     # 规范上限 8s，留 1.5s 对齐余量
TAIL_MAX = 11.0    # 规范上限 12s，留 1s 余量


def _slice(segs, a, b):
    return [s for s in segs if s.get('end', 0) > a and s.get('start', 0) < b]


def window(segs_all, lyrics, t0, t1, find_bounds=None):
    """find_bounds(src, t0, dur) -> (na, nb, ok_s, ok_e)；不传则不做静音吸附"""
    import bound_lyric as BL
    import dtw_align as D

    c0, c1 = BL.refine(segs_all, lyrics, t0, t1)
    lo, hi = max(0.0, c0 - 8.0), c1 + 8.0
    segs = _slice(segs_all, lo, hi)
    first_hit = last_hit = None
    if segs and lyrics:
        amap = D.dtw_map(lyrics, segs)
        if amap:
            first_hit = min((v[1] for k, v in amap.items() if k == 1), default=None)
            last_hit = max((v[1] for k, v in amap.items() if k == len(lyrics)), default=None)
    start = (first_hit - HEAD_PAD) if first_hit is not None else c0
    end = (last_hit + TAIL_PAD) if last_hit is not None else c1
    if end - start < 60:
        start, end = c0, c1
    info = {'lyric_start': None if first_hit is None else round(first_hit, 2),
            'lyric_end': None if last_hit is None else round(last_hit, 2),
            'pre': round(start, 2), 'post': round(end, 2)}
    if find_bounds is None:
        return round(max(0.0, start), 2), round(end, 2), True, True, info
    na, nb, ok_s, ok_e = find_bounds(None, start, max(60.0, end - start))
    # 静音吸附可能把窗口拖得过远，按规范钳制（首句 ≤8s、末句 ≤12s 到边界）
    if first_hit is not None:
        na = max(na, first_hit - HEAD_MAX)
    if last_hit is not None:
        nb = min(nb, last_hit + TAIL_MAX)
    info.update({'na': na, 'nb': nb})
    return na, nb, ok_s, ok_e, info

def audio_window(recs, clean, t0, dur, find_bounds=None, head_pad=3.0, tail_pad=4.0,
                 max_head=20.0, max_tail=12.0, min_len=90.0, max_len=600.0):
    """**纯音频/转写标签**决定切片窗口（完全不看歌词）

    1) 只取被判定为"演唱"的转写句子，得到演唱跨度 [s_first, s_last]
    2) 起点：在 s_first 之前 ≤max_head 秒内找合规静音（吃回前奏）；找不到就用 s_first-head_pad
    3) 终点：s_last 之后 ≤max_tail 秒内找合规静音；找不到就用 s_last+tail_pad
    4) 时长夹在 [min_len, max_len]

    歌词只在之后的"验证"环节使用，不参与切点决定（避免循环依赖）。
    """
    lo, hi = max(0.0, t0 - 45.0), t0 + dur + 45.0
    sung = [(r['start'], r['end']) for i, r in enumerate(recs, 1)
            if clean.get(i) == 's' and r['end'] > lo and r['start'] < hi]
    if not sung:
        return None
    s_first = min(a for a, _ in sung)
    s_last = max(b for _, b in sung)
    start = max(0.0, s_first - head_pad)
    end = s_last + tail_pad
    ok_s = ok_e = False
    if find_bounds is not None:
        a, b, ok_s, ok_e = find_bounds(None, start, max(60.0, end - start))
        if ok_s and a >= s_first - max_head:
            start = a
        if ok_e and b <= s_last + max_tail:
            end = b
    if end - start < min_len:
        end = start + min_len
    if end - start > max_len:
        end = start + max_len
    return round(start, 2), round(end, 2), ok_s, ok_e, {
        'sung_first': round(s_first, 2), 'sung_last': round(s_last, 2),
        'na': round(start, 2), 'nb': round(end, 2)}
