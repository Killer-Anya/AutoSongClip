#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_lrc.py —— 体检成品：歌词是否对得上这场实际唱的内容 + 时间轴是否合理

用法: python3 tools/audit_lrc.py [最多检查多少首]
输出：每首的 歌词行数 / 最小行间隔 / 过密行数(疑压缩簇) / 与转写文本重合率 / 首行时间
"""
import json
import re
import sys
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


IDX = ROOT / 'queue' / 'songs_index.json'
ASR = ROOT / 'queue' / 'asr_v3'


def parse_lrc(lrc):
    out = []
    for ln in lrc.splitlines():
        m = re.match(r'\[(\d+):(\d+\.\d+)\](.*)', ln)
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        txt = m.group(3).strip()
        if txt:
            out.append((t, txt))
    return out


def to_sec(st):
    m = re.match(r'(\d+):(\d+)', str(st or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def zh(s):
    return ''.join(re.findall(r'[\u4e00-\u9fff]', s or ''))


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 6
    idx = [x for x in json.loads(IDX.read_text(encoding='utf-8')) if not x.get('legacy')]
    rows = []
    for x in idx[:limit]:
        lines = parse_lrc(x.get('lrc') or '')
        if not lines:
            rows.append((x['title'], 0, 0, 0, 0.0, 0, '无歌词'))
            continue
        gaps = [lines[i + 1][0] - lines[i][0] for i in range(len(lines) - 1)]
        dense = sum(1 for g in gaps if g < 0.6)
        mn = min(gaps) if gaps else 0
        st = to_sec(x.get('stream_time'))
        bvid = x.get('bvid') or ''
        overlap = None
        if st is not None and bvid:
            f = ASR / f'{bvid}.jsonl'
            if f.exists():
                segs = []
                for ln in f.read_text(encoding='utf-8').splitlines():
                    if not ln.strip():
                        continue
                    r = json.loads(ln)
                    s = float(r.get('start') or 0)
                    if st - 2 <= s <= st + float(x.get('dur') or 0) + 2:
                        segs.append(r.get('text') or '')
                heard = set(zh(''.join(segs)))
                if heard:
                    want = set(zh(''.join(t for _, t in lines)))
                    overlap = len(want & heard) / max(1, len(want))
        rows.append((x['title'], len(lines), round(mn, 2), dense, overlap, round(lines[0][0], 2), ''))
    rows.sort(key=lambda r: ((r[4] if r[4] is not None else 1), -r[3]))
    print(f'{"歌名":<22}{"行数":>5}{"最小间隔":>9}{"过密行":>7}{"文本重合":>9}{"首行时间":>9}')
    for t, n, mn, dense, ov, ft, note in rows:
        ovs = '—' if ov is None else f'{ov:.0%}'
        flag = ' ⚠' if (ov is not None and ov < 0.55) or dense > 3 else ''
        print(f'{t[:20]:<22}{n:>5}{mn:>9}{dense:>7}{ovs:>9}{ft:>9}{flag}')
    bad = [r for r in rows if (r[4] is not None and r[4] < 0.55) or r[3] > 3]
    print(f'\n可疑 {len(bad)}/{len(rows)} 首')


if __name__ == '__main__':
    main()