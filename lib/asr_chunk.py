#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asr_chunk.py —— 分块无 VAD 转写，控制内存（whisper small int8）"""
import json, sys, wave, numpy as np
from pathlib import Path
import faster_whisper.audio as _fa
from faster_whisper import WhisperModel

def _dec(inp, sampling_rate=16000):
    with wave.open(inp) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')
    return x.astype(np.float32) / 32768.0
_fa.decode_audio = _dec
import faster_whisper.transcribe as _ft
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

    _ft.decode_audio = _dec

    src = Path(sys.argv[1]); out = Path(sys.argv[2])
    beam = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    CH = 300.0
    model = Path(_os.environ.get('SONG_CUT_MODELS', ROOT / 'models')) / 'small'
    m = WhisperModel(str(model), device='cpu', compute_type='int8', cpu_threads=2)
    w = wave.open(str(src))
    total = w.getnframes() / 16000.0
    start_at = 0.0
    if out.exists() and out.stat().st_size > 100:
        last = [json.loads(l) for l in out.read_text(encoding='utf-8').splitlines() if l.strip()]
        if last:
            start_at = last[-1]['end'] - 1.0
    print(f'总 {total/60:.1f} min, 从 {start_at/60:.1f} min 继续', flush=True)
    f = open(out, 'a', encoding='utf-8')
    t = start_at
    while t < total:
        a = t
        b = min(t + CH, total)
        w.setpos(int(a * 16000))
        x = np.frombuffer(w.readframes(int((b - a) * 16000)), dtype='<i2').astype(np.float32) / 32768.0
        segs, _ = m.transcribe(x, language='zh', beam_size=beam, vad_filter=False,
                               condition_on_previous_text=False, word_timestamps=True,
                               temperature=[0.0, 0.2])
        n = 0
        for s in segs:
            f.write(json.dumps({'start': round(s.start + a, 2), 'end': round(s.end + a, 2),
                                'text': s.text.strip(),
                                'words': [[round(w.start + a, 2), round(w.end + a, 2), w.word]
                                          for w in (s.words or [])]},
                               ensure_ascii=False) + '\n')
            n += 1
        f.flush()
        print(f'  {a/60:5.1f}-{b/60:5.1f} min  {n} 句', flush=True)
        del x
        t = b
    f.close()
    print('DONE', flush=True)


if __name__ == "__main__":
    main()