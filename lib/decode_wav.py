#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decode_wav.py —— 任意音频解码为 16k 单声道 wav（分块写盘，省内存）"""
import sys, wave
import av, av.audio
SR = 16000


def main(src=None, dst=None):
    if src is None:
        src, dst = sys.argv[1], sys.argv[2]
    c = av.open(src)
    st = c.streams.audio[0]
    rs = av.AudioResampler(format='s16', layout='mono', rate=SR)
    w = wave.open(dst, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    n = 0
    for fr in c.decode(st):
        for f2 in rs.resample(fr):
            b = f2.to_ndarray().astype('<i2').tobytes()
            w.writeframes(b); n += len(b) // 2
    w.close(); c.close()
    print(f'decoded {n/16000:.1f}s')


if __name__ == "__main__":
    main()
