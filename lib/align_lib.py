#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""align_lib.py —— 单曲排轴：只显示"确实唱到了"的歌词行（DTW 命中行 + 中间补插）"""
import re
import dtw_align as D
import align_qwen as A


def _decompress(final, min_gap=0.9, dur=None):
    """把被压成 0.5 秒一行的簇，按字符数在该区间内重新均匀铺开"""
    if len(final) < 2:
        return final
    out = list(final)
    i = 0
    while i < len(out) - 1:
        j = i
        while j < len(out) - 1 and (out[j+1][0] - out[j][0]) < min_gap:
            j += 1
        if j > i:                      # 找到 [i..j] 压缩簇
            start = out[i][0]
            end = out[j+1][0] if j+1 < len(out) else min(out[j][0] + 6.0, start + 6.0)
            total_chars = sum(max(1, len(t)) for t in [out[k][1] for k in range(i, j+1)])
            need = total_chars / 3.0          # 按每秒约3字估算该簇至少要占多长
            n_line = j - i + 1
            # 每行至少留 0.9 秒，避免整簇被摊成 0.2~0.3 秒一行（历史问题：歌词挤成一团）
            span = max(0.9 * n_line, end - start, min(need, max(1.0, (dur or 1e9) - start)))
            if dur:
                span = min(span, max(0.9 * n_line, dur - start))
            texts = [out[k][1] for k in range(i, j+1)]
            total = sum(max(1, len(t)) for t in texts) or 1
            acc = 0.0
            for k in range(i, j+1):
                out[k] = (round(start + span * acc / total, 2), texts[k-i])
                acc += max(1, len(texts[k-i]))
            i = j + 1
        else:
            i += 1
    return out




def _syl_timeline(segs):
    out_s, out_t = [], []
    for s in segs:
        for w in (s.get('words') or []):
            ss = D.syls(w[2])
            if not ss:
                continue
            a, b = float(w[0]), float(w[1])
            step = (b - a) / len(ss)
            for k, sy in enumerate(ss):
                out_s.append(sy)
                out_t.append(a + step * k)
    return out_s, out_t


def _reanchor(final, segs, window=4.0, keep=4):
    """把每行吸附到转写里最匹配的演唱位置（局部 ±window 秒搜索），修正 DTW 在重复副歌处的错配"""
    syl, tms = _syl_timeline(segs)
    if not syl or not final:
        return final
    out = []
    for t, line in final:
        key = D.syls(line)[:keep]
        if len(key) < 2:
            out.append((t, line))
            continue
        best, bt = 0, None
        for i, tt in enumerate(tms):
            if not (t - window <= tt <= t + window):
                continue
            sc = 0
            for off in (-1, 0, 1):
                s = 0
                for k, sy in enumerate(key):
                    j = i + k + off
                    if 0 <= j < len(syl) and syl[j] == sy:
                        s += 1
                sc = max(sc, s)
            if sc > best or (sc == best and bt is not None and abs(tms[i]-t) < abs(bt-t)):
                best, bt = sc, tms[i]
        if bt is not None and best / len(key) >= 0.75 and abs(bt - t) <= window:
            out.append((bt, line))
        else:
            out.append((t, line))
    out.sort(key=lambda x: x[0])
    return out


def _finalize(final, dur, min_gap=0.9):
    """收尾：严格单调、行间隔 ≥ min_gap、全部落在时长内（放不下时整体压缩，仍不行就丢弃尾部溢出）"""
    if not final:
        return []
    final = sorted(final, key=lambda x: x[0])
    out, last = [], -1e9
    for t, l in final:
        t = max(float(t), last + min_gap)
        out.append([t, l])
        last = t
    if dur:
        end_lim = dur - 0.4
        if out[-1][0] > end_lim:
            span = out[-1][0] - out[0][0]
            avail = end_lim - out[0][0]
            if span > 0 and avail > min_gap * len(out) * 0.6:
                k = avail / span
                scaled = [[out[0][0] + (t - out[0][0]) * k, l] for t, l in out]
                out, last = [], -1e9
                for t, l in scaled:
                    t = max(t, last + min_gap)
                    out.append([t, l])
                    last = t
            if out and out[-1][0] > end_lim:
                out = [x for x in out if x[0] <= end_lim]
    return [(round(t, 2), l) for t, l in out]


def align(title, artist, segs, dur, keep_gap=True):
    """返回 lrc 字符串：只保留 DTW 有命中的行，以及命中行之间被漏识别的行"""
    if not segs:
        return ''
    off = A.official(title, artist)
    if not off or not off[0]:
        return ''
    lines = off[0]
    # 过滤开头/中间的短促幻觉句（"嗯""啊""啦啦"等），避免歌词被锚到静音处
    def usable(t):
        c = re.sub(r'[^\u4e00-\u9fffA-Za-z]', '', t or '')
        if len(c) < 3:
            return False
        if len(c) >= 6 and len(set(c)) <= 2:
            return False
        return True
    segs = [s2 for s2 in segs if usable(s2.get('text', ''))]
    if not segs:
        return '', {}
    raw = D.dtw_map(lines, segs)
    if not raw:
        return ''
    hit = sorted(raw)
    lo, hi = hit[0], hit[-1]
    # 命中区间内的行保留（中间缺锚点的用插值补齐），区间外整段丢弃
    keep = [i for i in range(lo, hi + 1)]
    sub_lines = [lines[i - 1] for i in keep]
    mp = {k: raw[k][0] for k in raw}
    tmap = {k: raw[k][1] for k in raw}
    final = A.monotonic_fill(sub_lines, segs, mp, dur, tmap, offset=lo)
    # 去掉 DTW 回绕造成的"末句出现在开头"
    if len(final) > 2 and final[0][1] == final[-1][1] and final[0][0] < 2.0:
        final = final[1:]
    final = _reanchor(final, segs)          # 局部重锚：修正重复副歌处的错配
    final = _decompress(final, dur=dur)
    final = _finalize(final, dur, min_gap=0.9)   # V4：行间隔至少 0.9s，且不越过时长
    # 去掉时间戳重复/倒序的行，保证严格单调（格式化到 2 位小数后仍可能碰撞）
    rows, last_s = [], None
    for t, l in final:
        s = f'{int(t)//60:02d}:{t%60:05.2f}'
        if last_s is not None and s <= last_s:
            continue
        rows.append((t, l))
        last_s = s
    final = rows
    return '\n'.join(f'[{int(t)//60:02d}:{t%60:05.2f}]{l}' for t, l in final)


if __name__ == '__main__':
    import json, sys
    segs = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8') if l.strip()]
    print(align(sys.argv[2], sys.argv[3], segs, segs[-1]['end'])[:400])
