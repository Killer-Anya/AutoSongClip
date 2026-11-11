#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mimo_bench.py —— 评估 MiMo 音频模型的能力与速度（结果写入 docs/mimo_bench.json）"""
import os as _os
from pathlib import Path as _P
ROOT = _P(_os.environ.get('SONG_CUT_HOME') or _P(__file__).resolve().parent.parent)
_ROOT = ROOT
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))

import mimo  # noqa: E402
import os as _os
from pathlib import Path as _P


def _ff(name, env):
    _e = _os.environ.get(env)
    if _e:
        return _e
    _p = _ROOT / 'bin2' / name
    return str(_p) if _p.exists() else name


FFMPEG = _ff('ffmpeg', 'SONG_CUT_FFMPEG')
FFPROBE = _ff('ffprobe', 'SONG_CUT_FFPROBE')
PY_BIN = _os.environ.get('SONG_CUT_PY', 'python3')


SRC = str(ROOT / 'res/BV16j411Y7sS.m4a')      # 2023-11-05 场
OUT = {}


def clip(start, dur, tag):
    return mimo.clip(SRC, start, dur, f'/tmp/bench_{tag}.wav')


def timed(fn, *a, **k):
    t0 = time.time()
    r = fn(*a, **k)
    return r, round(time.time() - t0, 1)


def main():
    res = {}

    # 1) 速度与时长上限：20s / 60s / 120s / 300s
    speed = []
    for dur in (20, 60, 120, 300):
        c = clip(810, dur, f'len{dur}')
        r, dt = timed(mimo.transcribe, c, max_tokens=1500)
        speed.append({'dur': dur, 'sec': dt, 'tokens': (r.get('usage') or {}).get('total_tokens'),
                      'chars': len(r.get('text') or '')})
    res['speed'] = speed

    # 2) 说话/唱歌判别（含"有伴奏但说话"的诱导样本）
    disc = []
    for name, st in (('歌A 不亏不欠', 810), ('歌B 天黑黑', 2090), ('歌C 雨爱', 3160),
                     ('说话1', 1068), ('说话2', 1200), ('说话3', 1500)):
        c = clip(st, 20, f'd{st}')
        r, dt = timed(mimo.is_singing, c)
        disc.append({'case': name, 'singing': r['singing'], 'conf': r['confidence'],
                     'note': r['note'][:40], 'sec': dt})
    res['discriminate'] = disc

    # 3) 边界定位：从歌曲前 10 秒开始截 40 秒，问演唱从第几秒开始
    c = clip(780, 40, 'bound')
    txt, u = mimo._ask('这段音频里，如果先有说话/杂音然后开始唱歌，请只输出 JSON：'
                       '{"has_singing": true/false, "singing_start_sec": 数字, "note": "说明"}。'
                       'singing_start_sec 用相对音频开头的秒数，不确定给 null。',
                       [c], max_tokens=300)
    res['boundary'] = {'raw': txt[:200], 'tokens': u.get('total_tokens')}

    # 4) 片段完整性：取副歌中段 60 秒，问是否只唱了片段
    c = clip(950, 60, 'partial')
    txt2, u2 = mimo._ask('这段是现场演唱的一小段。请判断：它是完整的一首歌，还是只截取了其中一段/副歌？'
                         '只输出 JSON：{"complete_song": true/false, "reason": "简短说明"}。',
                         [c], max_tokens=300)
    res['partial'] = {'raw': txt2[:200], 'tokens': u2.get('total_tokens')}

    # 5) 串烧/拼接检测：跨两首歌边界截 40 秒（不亏不欠结束→下一段）
    c = clip(1000, 40, 'mix')
    txt3, u3 = mimo._ask('这段音频里是否出现了两首以上不同的歌（串烧/拼接）？只输出 JSON：'
                         '{"mixed": true/false, "songs_heard": 数字, "reason": "简短说明"}。',
                         [c], max_tokens=300)
    res['mixed'] = {'raw': txt3[:200], 'tokens': u3.get('total_tokens')}

    # 6) 并发能力：3 个 20 秒片段同时请求
    clips = [clip(a, 20, f'p{i}') for i, a in enumerate((810, 2090, 3160))]
    t0 = time.time()
    procs = []
    for i, c in enumerate(clips):
        data = base64.b64encode(Path(c).read_bytes()).decode()
        payload = {'model': mimo.MODEL, 'max_tokens': 400, 'temperature': 0.0,
                   'chat_template_kwargs': {'enable_thinking': False},
                   'messages': [{'role': 'user', 'content': [
                       {'type': 'text', 'text': '只输出 JSON：{"singing": true/false}'},
                       {'type': 'input_audio', 'input_audio': {'data': data, 'format': 'wav'}}]}]}
        open(f'/tmp/par_{i}.json', 'w').write(json.dumps(payload))
        procs.append(subprocess.Popen(
            f'curl -s -m 120 {mimo.API} -H "Authorization: Bearer {mimo.KEY}" '
            f'-H "Content-Type: application/json" --data-binary @/tmp/par_{i}.json '
            f'-o /tmp/par_{i}.out', shell=True))
    for pr in procs:
        pr.wait()
    res['parallel'] = {'sec': round(time.time() - t0, 1), 'n': len(clips)}

    (ROOT / 'docs' / 'mimo_bench.json').write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                   encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
