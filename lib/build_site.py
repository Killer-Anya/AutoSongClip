#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_site.py —— 由 queue/songs_index.json 生成歌单页面（支持大量歌曲、按场次标注时间）"""
import json, re
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


PAGE = ROOT / 'site' / 'web' / 'index.html'
INDEX = ROOT / 'queue' / 'songs_index.json'


def main():
    songs = json.loads(INDEX.read_text(encoding='utf-8'))
    songs.sort(key=lambda z: z['no'])

    # UX028：用歌词字符集自动判定演唱语言，覆盖默认值
    import re as _re
    def detect_lang(lrc, title, artist):
        txt = _re.sub(r'\[[^\]]*\]', '', lrc or '')
        kana = len(_re.findall(r'[\u3040-\u30ff]', txt))
        hangul = len(_re.findall(r'[\uac00-\ud7af]', txt))
        han = len(_re.findall(r'[\u4e00-\u9fff]', txt))
        latin = len(_re.findall(r'[A-Za-z]', txt))
        total = kana + hangul + han + latin
        if total < 10:
            return None
        if kana / total > 0.10:
            return '日语'
        if hangul / total > 0.10:
            return '韩语'
        if latin / total > 0.60:
            return '英文'
        if han / total > 0.60:
            return '粤语' if '粤' in (artist or '') else '国语'
        return None

    def nice_date(d):
        m = re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', str(d or ''))
        return f'{m.group(1)}/{int(m.group(2))}/{int(m.group(3))}' if m else (d or '')
    out = []
    for x in songs:
        out.append({
            'no': x['no'], 'title': x['title'], 'artist': x['artist'],
            'dur': round(float(x.get('dur') or 0), 1), 'file': x['file'],
            'lrc': x.get('lrc') or '',
            'lang': detect_lang(x.get('lrc'), x.get('title'), x.get('artist')) or x.get('lang') or '国语',
            'style': (x.get('style') if (x.get('style') or '') not in ('', '流行') else '未分类'), 'date': nice_date(x.get('date')),
            'stream': x.get('stream') or '', 'time': '',
            'ver': x.get('ver') or '',
            'legacy': bool(x.get('legacy')),
            'batch': x.get('batch') or '',
        })
    # 同一首歌多次演唱 → 加版本序号，便于区分
    from collections import defaultdict
    groups = defaultdict(list)
    for x in out:
        groups[(x['title'], x['artist'], x['date'])].append(x)
    for k, lst in groups.items():
        if len(lst) > 1:
            lst.sort(key=lambda z: z.get('time') or '')
            for i, x in enumerate(lst, 1):
                x['ver'] = f'第{i}次'
    s = PAGE.read_text(encoding='utf-8')
    marker = 'const SONGS = '
    start = s.index(marker) + len(marker)
    _, length = json.JSONDecoder().raw_decode(s[start:])
    payload = json.dumps(out, ensure_ascii=False).replace('<', r'\u003c')
    s = s[:start] + payload + s[start + length:]
    PAGE.write_text(s, encoding='utf-8')
    print('页面已更新：', len(out), '首')


if __name__ == '__main__':
    main()