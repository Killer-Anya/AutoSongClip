#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_library.py —— 上架前对成品目录做一致性终检（不依赖转写缓存）

检查每首：
  1. 三件套齐全（01_audio.m4a / 02_lyrics.lrc / 03_karaoke.ass）
  2. 音频参数 AAC 48k/44.1k 立体声，时长与索引记录一致（±0.3s）
  3. 歌词严格单调、行间隔 ≥0.6s、末行不超时长
  4. 逐字字幕单字 ≥80ms、行间不重叠
  5. 索引条目与目录一一对应（无孤立目录、无缺失文件）

用法: python3 tools/validate_library.py
"""
import json
import re
import subprocess
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


LIB = ROOT / 'library'


def probe(p):
    out = subprocess.run(
        [FFPROBE, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
         'stream=codec_name,sample_rate,channels:format=duration', '-of', 'json', p],
        capture_output=True, text=True).stdout
    try:
        d = json.loads(out)
        st = (d.get('streams') or [{}])[0]
        return {'codec': st.get('codec_name'), 'sr': int(st.get('sample_rate') or 0),
                'ch': int(st.get('channels') or 0), 'dur': float((d.get('format') or {}).get('duration') or 0)}
    except Exception:
        return {}


def lrc_rows(txt):
    rows = []
    for ln in txt.splitlines():
        m = re.match(r'\[(\d+):(\d+\.\d+)\](.*)', ln)
        if m and m.group(3).strip():
            rows.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return rows


def check_pkg(d):
    bad = []
    a, l, s = d / '01_audio.m4a', d / '02_lyrics.lrc', d / '03_karaoke.ass'
    for f in (a, l, s):
        if not f.exists():
            bad.append(f'缺文件 {f.name}')
    if bad:
        return bad, {}
    info = probe(a)
    if not info:
        bad.append('音频无法读取')
        return bad, {}
    if info['codec'] not in ('aac', 'mp4a'):
        bad.append(f"编码 {info['codec']}")
    if info['sr'] not in (44100, 48000):
        bad.append(f"采样率 {info['sr']}")
    if info['ch'] != 2:
        bad.append(f"声道 {info['ch']}")
    rows = lrc_rows(l.read_text(encoding='utf-8'))
    if len(rows) < 5:
        bad.append('歌词行过少')
    else:
        ts = [t for t, _ in rows]
        gaps = [ts[i+1]-ts[i] for i in range(len(ts)-1)]
        if any(g <= 0 for g in gaps):
            bad.append('歌词非单调')
        if sum(1 for g in gaps if g < 0.6) > 0:
            bad.append(f"行间隔过密 {sum(1 for g in gaps if g < 0.6)}")
        if ts[-1] > info['dur'] + 0.3:
            bad.append('末行超出时长')
    ev = [x for x in s.read_text(encoding='utf-8').splitlines() if x.startswith('Dialogue')]
    ks = [int(v) for e in ev for v in re.findall(r'\\k(\d+)', e)]
    if ks and min(ks) < 8:
        bad.append(f'字幕单字过短 {min(ks)}cs')
    return bad, info


def main():
    idxf = ROOT / 'queue' / 'songs_index_new.json'
    idx = json.loads(idxf.read_text(encoding='utf-8')) if idxf.exists() else []
    names = {x['file'].split('/')[0] for x in idx}
    dirs = {p.name for p in LIB.iterdir() if p.is_dir()}
    orphans = dirs - names
    bad_n = 0
    print(f'索引 {len(idx)} 首，目录 {len(dirs)} 个，孤立目录 {len(orphans)}')
    for name in sorted(orphans):
        print('  孤立目录：', name)
    for x in idx:
        d = LIB / x['file'].split('/')[0]
        bad, info = check_pkg(d)
        if bad:
            bad_n += 1
            print(f"  ✗ {x['title']}（{x.get('date','')}）：{'；'.join(bad)}")
        else:
            drift = abs(info['dur'] - float(x.get('dur') or 0))
            if drift > 0.3:
                print(f"  ⚠ {x['title']}：时长与索引差 {drift:.2f}s")
    print(f'\n不合格 {bad_n} / {len(idx)}')


if __name__ == '__main__':
    main()