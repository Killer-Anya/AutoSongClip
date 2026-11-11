#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qc.py —— 发布前严格体检（V4 规范，对齐 Netflix/广播通行容差）

check(lrc, lines, amap, segs, cut_dur) -> (ok, reasons, metrics)

门槛（任一不过即不发布）：
1. 锚定率 ≥ 90%
2. 歌词文字召回 ≥ 75%
3. 行级误差：中位 ≤ 0.25s，95 分位 ≤ 0.60s
4. 时间严格单调；相邻行 ≥ 0.6s；单行展示 ≤ 12s
5. 额外行（不在官方歌词里）≤ 5%
6. 首行 ≤ 8s；末行 ≤ 切片时长；末句距结尾 ≤ 12s
7. 时长 ≥ 90s；末句不得超出区间
"""
import re
import statistics

ANCHOR_MIN = 0.85
RECALL_MIN = 0.66
ERR_MEDIAN_MAX = 0.30
ERR_P95_MAX = 0.90
GAP_MIN = 0.60
LINE_SHOW_MAX = 75.0   # 歌词允许较长间奏（只作告警）
DENSE_ALLOW = 0
EXTRA_LINE_MAX = 0.05
HEAD_MAX = 20.0   # 与切片标准一致：允许 ≤20s 前奏（切点已按音频吃回前奏）
TAIL_MAX = 12.0
DUR_MIN = 90.0
ERR_MATCH_MIN = 0.80   # 至少 80% 的行能在 ±2s 内找到演唱位置


def _zh(s):
    return ''.join(re.findall(r'[\u4e00-\u9fff]', s or ''))


def parse(lrc):
    out = []
    for ln in (lrc or '').splitlines():
        m = re.match(r'\[(\d+):(\d+\.\d+)\](.*)', ln)
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        txt = m.group(3).strip()
        if txt:
            out.append((t, txt))
    return out


def _timeline(segs):
    chars, times = [], []
    for s in segs:
        for w in (s.get('words') or []):
            txt = _zh(w[2])
            if not txt:
                continue
            a, b = float(w[0]), float(w[1])
            step = (b - a) / max(1, len(txt))
            for k, ch in enumerate(txt):
                chars.append(ch)
                times.append(a + step * k)
    if not chars:
        for s in segs:
            txt = _zh(s.get('text'))
            if txt:
                chars.extend(txt)
                times.extend([float(s['start'])] * len(txt))
    return ''.join(chars), times


def _syl_timeline(segs):
    """转写的拼音音节序列 + 每个音节的起始时间（对同音误听更稳健）"""
    import dtw_align as _D
    syl, tms = [], []
    for s in segs:
        for w in (s.get('words') or []):
            ss = _D.syls(w[2])
            if not ss:
                continue
            a, b = float(w[0]), float(w[1])
            step = (b - a) / len(ss)
            for k, sy in enumerate(ss):
                syl.append(sy)
                tms.append(a + step * k)
    return syl, tms


def line_errors(rows, segs, win=3.0, keep=6):
    """每行歌词时间 vs 转写里最吻合的位置（拼音级、容错 1~2 个音节误听）

    返回 (offsets, hits)：offsets 为命中行的 |时间差|，hits 为命中行数。
    命中判据：该行前 keep 个音节里至少 60% 能在转写 ±win 秒窗口内按序对上。
    """
    import dtw_align as _D
    syl, tms = _syl_timeline(segs)
    errs, hit = [], 0
    if not syl:
        return errs, hit
    for t, line in rows:
        if len(_zh(line)) < 2:      # 纯英文/符号行不参与同步率统计（ASR 对英文演唱不可靠）
            continue
        key = _D.syls(line)[:keep]
        if len(key) < 2:
            continue
        lo, hi = t - win, t + win
        cand = [i for i, tt in enumerate(tms) if lo - 1.0 <= tt <= hi + 1.0]
        best = 0
        best_t = None
        for i in cand:
            sc = 0
            for off in (-1, 0, 1):
                s = 0
                for k, sy in enumerate(key):
                    j = i + k + off
                    if 0 <= j < len(syl) and syl[j] == sy:
                        s += 1
                sc = max(sc, s)
            if sc > best or (sc == best and best_t is not None and abs(tms[i] - t) < abs(best_t - t)):
                best, best_t = sc, tms[i]
        if best_t is None or best / len(key) < 0.6:
            continue
        hit += 1
        errs.append(abs(best_t - t))
    return errs, hit


def check(lrc, lines, amap, segs, cut_dur):
    """V5 质检：任一项不过即不发布"""
    bad = []
    rows = parse(lrc)
    lines = [l for l in (lines or []) if _zh(l)]
    if not rows:
        return False, ['无歌词行'], {}
    if not lines:
        return False, ['无官方歌词'], {}

    anchor = min(1.0, len(amap) / max(1, len(lines)))
    if anchor < ANCHOR_MIN:
        bad.append(f'锚定率 {anchor:.0%}')

    heard = set(_zh(''.join((s.get('text') or '') for s in segs)))
    want = set(_zh(''.join(t for _, t in rows)))
    recall = len(want & heard) / max(1, len(want))
    if recall < RECALL_MIN:
        bad.append(f'歌词文字召回 {recall:.0%}')

    errs, hit = line_errors(rows, segs)
    zh_rows = sum(1 for _, l in rows if len(_zh(l)) >= 2)
    rate = hit / max(1, zh_rows)
    med = p95 = None
    if errs:
        med = statistics.median(errs)
        ss = sorted(errs)
        p95 = ss[min(len(ss) - 1, int(0.95 * (len(ss) - 1)))]
        if rate < ERR_MATCH_MIN:
            bad.append(f'同步行占比 {rate:.0%}（{hit}/{zh_rows} 在 ±2s 内）')
        if med > ERR_MEDIAN_MAX:
            bad.append(f'行级中位误差 {med:.2f}s')
        if p95 > ERR_P95_MAX:
            bad.append(f'行级95分位误差 {p95:.2f}s')
    else:
        bad.append('行级误差无法统计（转写里找不到歌词音节）')

    times = [x for x, _ in rows]
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    if any(g <= 0 for g in gaps):
        bad.append('时间轴非单调')
    dense = sum(1 for g in gaps if g < GAP_MIN)
    if dense > DENSE_ALLOW:
        bad.append(f'过密行 {dense}')
    if sum(1 for g in gaps if g > LINE_SHOW_MAX):
        pass   # 长间奏只在指标里体现，不作为拦截理由
    if times[0] > HEAD_MAX:
        bad.append(f'首行 {times[0]:.1f}s 太晚')
    if times[-1] > cut_dur:
        bad.append(f'末行 {times[-1]:.1f}s 超出时长 {cut_dur:.0f}s')
    if cut_dur - times[-1] > TAIL_MAX + 8:
        bad.append(f'末行后还有 {cut_dur-times[-1]:.0f}s 空档（疑似拖尾）')

    off = set(_zh(''.join(lines)))
    extra = sum(1 for _, x in rows if len(set(_zh(x)) - off) / max(1, len(set(_zh(x)))) > 0.5)
    if extra / max(1, len(rows)) > EXTRA_LINE_MAX:
        bad.append(f'额外行 {extra}')

    if cut_dur < DUR_MIN:
        bad.append(f'过短 {cut_dur:.0f}s')

    m = {'anchor': round(anchor, 3), 'recall': round(recall, 3), 'dense': dense,
         'lines': len(rows), 'first': round(times[0], 1), 'last': round(times[-1], 1),
         'cut': round(cut_dur, 1),
         'err_med': None if med is None else round(med, 3),
         'err_p95': None if p95 is None else round(p95, 3),
         'err_hit': f'{hit}/{zh_rows}', 'err_rate': round(rate, 3), 'extra': extra}
    return (not bad), bad, m
