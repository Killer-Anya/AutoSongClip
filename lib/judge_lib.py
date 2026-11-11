#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge_lib.py —— 所有"需要读文字判断"的活都走同济 API（默认 GLM-5.3-Flash：最快且实测同分）"""
import json, os, time, urllib.request

import sys as _s, pathlib as _p
_s.path.insert(0, str(_p.Path(__file__).resolve().parent))
import llmcfg as _C
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

API = _C.API
KEY = _C.KEY
MODEL = _C.MODEL


def ask(system, payload, model=None, max_tokens=2000, tries=3):
    body = {'model': model or MODEL, 'temperature': 0.05, 'max_tokens': max_tokens, **_C.EXTRA,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
    data = json.dumps(body).encode()
    for k in range(tries):
        try:
            req = urllib.request.Request(API, data=data,
                                         headers={'Authorization': 'Bearer ' + KEY,
                                                  'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=150) as r:
                j = json.loads(r.read().decode())
            _count(j.get('usage') or {})
            return j['choices'][0]['message'].get('content') or ''
        except Exception as e:
            if '429' in str(e):
                time.sleep(20 + 15 * k)      # 限流：退避后重试
                continue
            try:
                _C.ensure_online()      # 同济通道掉线立即重连
            except Exception:
                pass
            if k == tries - 1:
                return ''
            time.sleep(1 + k)
    return ''


USAGE = f'{ROOT}/queue/token_usage.json'


def _count(u):
    try:
        import os
        d = {}
        if os.path.exists(USAGE):
            d = json.load(open(USAGE))
        d['calls'] = d.get('calls', 0) + 1
        d['tokens'] = d.get('tokens', 0) + int(u.get('total_tokens') or 0)
        json.dump(d, open(USAGE, 'w'))
    except Exception:
        pass


def json_of(text, kind='['):
    a = text.find(kind)
    b = text.rfind(']' if kind == '[' else '}')
    if a < 0 or b < 0:
        return None
    try:
        return json.loads(text[a:b + 1])
    except Exception:
        return None


CANON_SYS = ('给你一首歌的歌词片段和用户在网易云匹配到的条目名（可能是翻唱版）。'
             '请给出这首歌的标准曲名与原唱歌手。'
             '输出JSON：{"title":"标准曲名","artist":"原唱","confidence":0到1}。只输出JSON。')


def canonical_song(region_text, matched_title, matched_artist):
    txt = ask(CANON_SYS, {'歌词片段': region_text[:500], '匹配条目': f'{matched_title} / {matched_artist}'}, max_tokens=600)
    j = json_of(txt, '{')
    if isinstance(j, dict) and j.get('title'):
        return {'title': str(j.get('title'))[:40], 'artist': str(j.get('artist') or matched_artist)[:40],
                'conf': float(j.get('confidence') or 0)}
    return {'title': matched_title, 'artist': matched_artist, 'conf': 0.0}


VERIFY_SYS = ('判断这段直播转写是否「一首完整、纯演唱」的独唱歌曲。标准：'
              '1) 是否同一首歌连续演唱（不是练习片段或多首拼接）；'
              '2) 是否夹带说话/念弹幕/答谢礼物；'
              '3) 是否像完整一首（唱到主歌+副歌，非半途截断）；'
              '4) 是否为合唱/多人对唱/连麦合唱（主播与嘉宾、观众、另一位主播一起唱）；'
              '5) 是否为「放原曲/播放原唱」而非本人现场演唱（例如只是播放音频、跟唱极少或没张嘴唱）。'
              '输出JSON：{"same_song":true/false,"has_chat":true/false,"complete":true/false,'
              '"chorus":true/false,"playback":true/false,"reason":"≤30字"}。只输出JSON。')


def verify_segment(region_text, title=''):
    txt = ask(VERIFY_SYS, {'曲名': title, '转写': region_text[:1200]}, max_tokens=600)
    j = json_of(txt, '{')
    if isinstance(j, dict):
        return j
    return {}