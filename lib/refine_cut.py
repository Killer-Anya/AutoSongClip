#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refine_cut.py —— 边界吸附到低能量点后切歌并编码 m4a"""
import json, sys, wave, numpy as np
from pathlib import Path
import av

import os
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

def main():
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

    WAV = Path(os.environ.get('CUT_WAV') or f'{ROOT}/newaudio/full16k.wav')
    PLAN = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    OUTD = Path(sys.argv[2]); OUTD.mkdir(parents=True, exist_ok=True)
    SR = 16000

    w = wave.open(str(WAV))
    total = w.getnframes() / SR

    def rms_at(a, b):
        a = max(0, min(a, total)); b = max(a + 0.05, min(b, total))
        w.setpos(int(a * SR))
        x = np.frombuffer(w.readframes(int((b - a) * SR)), dtype='<i2').astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(x ** 2) + 1e-12))

    def snap_start(t, back=15.0, fwd=2.0, win=0.4):
        best, bt = 9e9, t
        x = t - back
        while x <= t + fwd:
            e = rms_at(x, x + win)
            if e < best:
                best, bt = e, x + win / 2
            x += 0.25
        return max(0.0, bt)

    def snap_end(t, back=2.0, fwd=15.0, win=0.4):
        best, bt = 9e9, t
        x = t - back
        while x <= t + fwd:
            e = rms_at(x, x + win)
            if e < best:
                best, bt = e, x + win / 2
            x += 0.25
        return min(total, bt)

    res = []
    for p in PLAN:
        raw = wave.open(str(WAV))
        a = snap_start(p['start']); b = snap_end(p['end'])
        raw.setpos(int(a * SR))
        x = np.frombuffer(raw.readframes(int((b - a) * SR)), dtype='<i2').astype(np.float32) / 32768.0
        nf = min(int(0.3 * SR), len(x) // 2)
        if nf > 0:
            ramp = np.linspace(0, 1, nf, dtype=np.float32)
            x[:nf] *= ramp; x[-nf:] *= ramp[::-1]
        name = f"{p['no']}_{p['title']}_{p['artist']}".replace('/', '_')
        outp = OUTD / (name + '.m4a')
        oc = av.open(str(outp), 'w')
        st = oc.add_stream('aac', rate=44100); st.layout = 'stereo'; st.bit_rate = 128000
        rs = av.AudioResampler(format='fltp', layout='stereo', rate=44100)
        frame = av.AudioFrame.from_ndarray(x.reshape(1, -1), format='flt', layout='mono')
        frame.sample_rate = SR
        for f2 in rs.resample(frame):
            for pkt in st.encode(f2): oc.mux(pkt)
        for pkt in st.encode(None): oc.mux(pkt)
        oc.close()
        dur = len(x) / SR
        res.append({'no': p['no'], 'title': p['title'], 'artist': p['artist'],
                    'start': round(a, 2), 'end': round(b, 2), 'dur': round(dur, 1), 'file': outp.name})
        print(f"  {name}  {a:.1f}->{b:.1f}s  {dur:.1f}s", flush=True)
    Path(OUTD / 'cuts.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print('done', len(res), flush=True)


if __name__ == "__main__":
    main()