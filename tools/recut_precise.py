#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recut_precise.py —— 精密切歌：保留真实前奏与尾音
思路：已知歌曲旧起点/终点（来自歌单），在原始录播上向前/向后扩展到最近的静音边界，
      再用原音轨流复制切出，同时把歌词时间整体平移并生成 ASS 字幕。
用法: recut_precise.py <bvid> <no> [<no> ...]
"""
import json, subprocess, sys, wave
from pathlib import Path
import numpy as np
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


sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'lib'))
AUD = ROOT/'media'/'audio'
IDX = ROOT/'queue'/'songs_index.json'
RES = ROOT/'res'
PY = PY_BIN
SR = 16000
HOP = 0.01


def ensure_source(bvid):
    f = RES / f'{bvid}.m4a'
    if f.exists() and f.stat().st_size > 1e6:
        return f
    RES.mkdir(exist_ok=True)
    import bili
    bili.fetch_audio(bvid, str(RES))
    got = sorted(RES.glob('*.m4a'))
    src = [g for g in got if g.name.startswith(bvid)]
    if not src:
        raise RuntimeError('下载失败')
    if src[0].name != f'{bvid}.m4a':
        src[0].rename(f)
    return f


def decode_window(src, a, b, out):
    subprocess.run(f'{PY} {ROOT}/bin2/ffmpeg -v error -y -ss {a:.2f} -to {b:.2f} -i "{src}" '
                   f'-ar {SR} -ac 1 -f wav "{out}"', shell=True, check=True)
    with wave.open(str(out)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32) / 32768
    return x


def rms_env(x, win=int(0.02*SR), hop=int(HOP*SR)):
    n = max(0, (len(x)-win)//hop+1)
    return np.array([np.sqrt(np.mean(x[i*hop:i*hop+win]**2)+1e-12) for i in range(n)])


def find_start(env, vocal_idx, base, max_back=90.0, quiet_runs=8):
    """从人声起点往回找：最后一个足够长的静音段之后，就是音乐真正开始处"""
    thr = max(np.percentile(env, 35), 0.004)
    i = vocal_idx
    while i > 0 and env[i] > thr:
        i -= 1
    # 从静音区继续回溯到它的开头
    j = i
    while j > 0 and env[j] <= thr:
        j -= 1
    back_limit = max(0, int(vocal_idx - max_back/HOP))
    start_idx = max(j, back_limit)
    return round(base + start_idx*HOP, 2)


def find_end(env, vocal_idx, base, max_fwd=40.0):
    thr = max(np.percentile(env, 35), 0.004)
    i = min(vocal_idx, len(env)-1)
    while i < len(env)-1 and env[i] > thr:
        i += 1
    fwd_limit = min(len(env)-1, int(vocal_idx + max_fwd/HOP))
    end_idx = min(i, fwd_limit)
    return round(base + end_idx*HOP, 2)


def shift_lrc(lrc, delta, dur):
    import re
    out = []
    for ln in (lrc or '').split('\n'):
        m = re.match(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)', ln.strip())
        if not m: continue
        t = int(m.group(1))*60 + float(m.group(2)) + delta
        if t < 0.2 or t > dur: continue
        out.append(f'[{int(t)//60:02d}:{t%60:05.2f}]{m.group(3)}')
    return '\n'.join(out)


def main(bvid, nos):
    ix = json.loads(IDX.read_text(encoding='utf-8'))
    src = ensure_source(bvid)
    print(f'原始音轨 {src.name} {src.stat().st_size/1e6:.0f}MB', flush=True)
    for x in ix:
        if x['no'] not in nos:
            continue
        old_start = x.get('stream_time') or '0:00'
        try:
            m, s = old_start.split(':')
            t0 = int(m)*60+int(s)
        except Exception:
            t0 = 0
        dur = float(x['dur'])
        a = max(0, t0-90); b = t0+dur+60
        wav = Path('/tmp')/f'win_{x["no"]}.wav'
        w = decode_window(src, a, b, wav)
        env = rms_env(w)
        vi = int((t0-a)/HOP)
        new_a = find_start(env, vi, a)
        new_b = find_end(env, int((t0+dur-a)/HOP), a)
        delta = t0 - new_a
        newdur = new_b - new_a
        outp = AUD / x['file']
        tmp = Path('/tmp')/f'cut_{x["no"]}.m4a'
        subprocess.run(f'{PY} {ROOT}/bin2/ffmpeg -v error -y -ss {new_a:.2f} -to {new_b:.2f} '
                       f'-i "{src}" -c copy "{tmp}"', shell=True, check=True)
        print(f"{x['no']} {x['title'][:12]:<14} 旧 {t0:.1f}+{dur:.0f} → 新 {new_a:.1f}+{newdur:.1f} "
              f"(前奏+{delta:.1f}s 尾+{newdur-dur-delta:.1f}s)", flush=True)
        x['prev_no'] = x['no']; x['lrc'] = shift_lrc(x.get('lrc'), delta, newdur)
        x['dur'] = round(newdur, 1); x['stream_time'] = '%02d:%02d' % (new_a//60, new_a%60)
        x['file'] = x['file']
        tmp.replace(outp)
        IDX.write_text(json.dumps(ix, ensure_ascii=False, indent=1), encoding='utf-8')
    print('DONE', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], set(sys.argv[2:]))