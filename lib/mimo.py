#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mimo.py —— 同济音频模型（MiMo-V2.6-Flash）调用封装

用途（替代/补充本地算力）：
  is_singing(clip)        判断这段音频是唱歌还是说话
  transcribe(clip)        转写演唱歌词（中文为主）
  verify_song(clips, lines)  独立验收：这段音频是否在唱给定的这些歌词、有无夹杂说话/拼接
  guess_song(clip)        尝试凭旋律+歌词判断歌名（仅作候选，不作最终依据）

设计要求（用户要求：严格、高质量）：
  * 提示词里明确"不许猜测""不确定就说不确定"
  * 一律要求 JSON 输出，字段固定，便于程序判定
  * 音频统一 16kHz 单声道 wav，20 秒/段
"""
import base64
import json
import subprocess
import time
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


API = 'http://127.0.0.1:18090/v1/chat/completions'
KEY = __import__('os').environ.get('TONGJI_API_KEY', '')
MODEL = 'MiMo-V2.6-Flash'


def clip(src, start, dur=20.0, out='/tmp/mimo_clip.wav'):
    r = subprocess.run(
        [FFMPEG, '-v', 'error', '-y', '-ss', f'{start:.2f}', '-t', str(dur), '-i', src,
         '-ar', '16000', '-ac', '1', out],
        capture_output=True,
    )
    return out if r.returncode == 0 else None


def _ask(prompt, clips, max_tokens=1200, tries=3, timeout=150):
    content = [{'type': 'text', 'text': prompt}]
    for c in clips:
        try:
            data = base64.b64encode(Path(c).read_bytes()).decode()
        except Exception:
            continue
        content.append({'type': 'input_audio', 'input_audio': {'data': data, 'format': 'wav'}})
    payload = {'model': MODEL, 'max_tokens': max_tokens, 'temperature': 0.0,
               'chat_template_kwargs': {'enable_thinking': False},
               'messages': [{'role': 'user', 'content': content}]}
    body = json.dumps(payload)
    for k in range(tries):
        p = subprocess.run(
            f'curl -s -m {timeout} {API} -H "Authorization: Bearer {KEY}" '
            f'-H "Content-Type: application/json" --data-binary @-',
            input=body, shell=True, capture_output=True, text=True)
        try:
            d = json.loads(p.stdout)
            txt = (d['choices'][0]['message'].get('content') or '').strip()
            u = d.get('usage') or {}
            try:      # 记录 MiMo 用量，便于监控额度
                import os
                UF = f'{ROOT}/queue/mimo_usage.json'
                c = json.load(open(UF)) if os.path.exists(UF) else {}
                c['calls'] = c.get('calls', 0) + 1
                c['tokens'] = c.get('tokens', 0) + int(u.get('total_tokens') or 0)
                c['audio_tokens'] = c.get('audio_tokens', 0) + int((u.get('prompt_tokens_details') or {}).get('multimodal_tokens', {}).get('audio') or 0)
                json.dump(c, open(UF, 'w'))
            except Exception:
                pass
            return txt, u
        except Exception:
            time.sleep(3 + 3 * k)
    return '', {}


def _json_of(txt):
    s, e = txt.find('{'), txt.rfind('}')
    if s >= 0 and e > s:
        try:
            return json.loads(txt[s:e + 1])
        except Exception:
            pass
    return None


def is_singing(clip_path):
    """返回 {'singing':bool,'confidence':0~1,'note':str}"""
    prompt = ('请严格判断这段音频的内容类型，只输出 JSON：'
              '{"singing": true/false, "confidence": 0~1, "note": "简短说明"}。'
              '判定标准：有旋律、有伴奏、连续演唱=唱歌；口语交谈、念弹幕、报幕=说话；'
              '两者mixed 时 singing 取是否以演唱为主（演唱占比>60% 才算 true）。不确定时 confidence 给低值。')
    txt, _u = _ask(prompt, [clip_path], max_tokens=400)
    j = _json_of(txt) or {}
    return {'singing': bool(j.get('singing')), 'confidence': float(j.get('confidence') or 0),
            'note': str(j.get('note') or ''), 'raw': txt[:200]}


def transcribe(clip_path, max_tokens=900):
    prompt = ('请把这段音频里"演唱的歌词"逐句转写出来，只输出歌词正文，不要解释、不要加标题。'
              '如果有说话内容，忽略；听不清的地方用（？）代替，不要编造。')
    txt, u = _ask(prompt, [clip_path], max_tokens=max_tokens)
    return {'text': txt, 'usage': u}


def verify_song(clips, lines, title=''):
    """独立验收：音频是否在唱给定歌词（lines 为官方歌词若干行）"""
    sample = ' / '.join(l.strip() for l in lines[:24] if l.strip())
    prompt = ('这是一首现场演唱的录音片段，以及我们认为是这首歌的官方歌词。请严格核对，只输出 JSON：'
              '{"same_song": true/false, "singing": true/false, "lines_hit": 0~1, '
              '"has_talk": true/false, "mixed_songs": true/false, "confidence": 0~1, "note": "说明"}。'
              '判定要求：'
              '1) same_song：音频里唱的内容是否就是这些歌词（同音不同字可接受，整句不同则 false）；'
              '2) lines_hit：这些歌词被唱到的估计比例；'
              '3) has_talk：片段里是否夹杂明显说话（念弹幕/报谢/闲聊）；'
              '4) mixed_songs：是否拼接了两首以上不同的歌；'
              '5) 禁止猜测：不确定就把 confidence 给低值并在 note 说明。'
              f'\n歌曲：{title}\n官方歌词节选：{sample}')
    txt, u = _ask(prompt, clips, max_tokens=700)
    j = _json_of(txt) or {}
    return {'same_song': j.get('same_song'), 'singing': j.get('singing'),
            'lines_hit': j.get('lines_hit'), 'has_talk': j.get('has_talk'),
            'mixed_songs': j.get('mixed_songs'), 'confidence': j.get('confidence'),
            'note': str(j.get('note') or ''), 'usage': u, 'raw': txt[:300]}


def guess_song(clip_path):
    prompt = ('这段是直播翻唱。请判断歌名与原唱，只输出 JSON：'
              '{"title": "", "artist": "", "confidence": 0~1}。'
              '不确定就把 title 留空、confidence 给低值，禁止猜测。')
    txt, _u = _ask(prompt, [clip_path], max_tokens=300)
    j = _json_of(txt) or {}
    return {'title': str(j.get('title') or ''), 'artist': str(j.get('artist') or ''),
            'confidence': float(j.get('confidence') or 0), 'raw': txt[:200]}