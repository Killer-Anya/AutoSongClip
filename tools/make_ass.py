#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_ass.py —— 由 lrc 生成带逐字高亮的 .ass 字幕（滚动歌词视频用）
用法: make_ass.py <title> <artist> <lrc_file> <out.ass> [时长秒]
逐字时间按行时长和字数均分，够做卡拉OK填充效果。
"""
import re, sys


def parse(lrc):
    out = []
    for ln in (lrc or '').split('\n'):
        m = re.match(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)', ln.strip())
        if m:
            out.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return out


def ts(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f'{h}:{m:02d}:{s:05.2f}'



MAX_CHARS = 16          # 单行显示上限（中日韩字幕通行 14~16 字）
GAP_CS = 0.07           # 分屏两行之间留 2 帧 ≈70ms


def _split_display(t, end, txt):
    """一行太长就按空格就近折成两屏，逐字计时按字符数比例分配（V5 可读性要求）"""
    plain = re.sub(r'\s', '', txt)
    if len(plain) <= MAX_CHARS or end - t < 1.6:
        return [(t, end, txt)]
    # 找最靠近中点的空格切分
    best = None
    for m in re.finditer(r'\s+', txt):
        left = len(re.sub(r'\s', '', txt[:m.start()]))
        score = abs(left - len(plain) / 2.0)
        if best is None or score < best[0]:
            best = (score, m.start(), m.end())
    if best is None:
        half = len(plain) // 2
        return [(t, t + (end - t) * half / len(plain), txt[:half]),
                (t + (end - t) * half / len(plain), end, txt[half:])]
    _, a, b = best
    left_n = len(re.sub(r'\s', '', txt[:a]))
    cut = t + (end - t) * left_n / len(plain)
    cut = max(t + 0.6, min(end - 0.6, cut))
    return [(t, cut, txt[:a].strip()), (min(end, cut + GAP_CS), end, txt[b:].strip())]


def main(title, artist, lrcf, outf, dur=None):
    lines = parse(open(lrcf, encoding='utf-8').read())
    head = f"""[Script Info]
Title: {title} - {artist}
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,思源黑体,72,&H00FFFFFF,&H00FF9DBB,&H00101010,&H80000000,1,0,0,0,100,100,1,0,1,3,2,2,80,80,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for i, (t, txt) in enumerate(lines):
        end = lines[i + 1][0] if i + 1 < len(lines) else min(dur or (t + 12), t + 12)
        for ct, ce, chunk in _split_display(t, end, txt):
            n = max(1, len(re.sub(r'\s', '', chunk)))
            step = max(0.08, (ce - ct) / n)     # V4：单字最短 80ms，避免闪烁
            parts = []
            for ch in chunk:
                kc = max(8, int(step * 100))    # 厘秒
                parts.append(f'{{\\k{kc}}}{ch}')
            ev.append(f'Dialogue: 0,{ts(ct)},{ts(ce)},Main,,0,0,0,,{"".join(parts)}')
    open(outf, 'w', encoding='utf-8').write(head + '\n'.join(ev) + '\n')
    print(f'{outf}  行数 {len(ev)}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
         float(sys.argv[5]) if len(sys.argv) > 5 else None)
