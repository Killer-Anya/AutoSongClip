#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mimo_asr.py —— 用云端音频模型做整场转写（实验，默认不启用）

实测结论（见 docs/竞品与差异.md 第六节）：
  * 速度约为本地的 4~6 倍（14~17 倍实时），不占本机 CPU/内存
  * 文本更准（简体、少同音错字）
  * **但句级时间与本地 whisper 相差 3~5 秒，且粒度 10~20 秒/句**
    → 不能作为排轴的时间来源，仅作实验保留

用法: python3 lib/mimo_asr.py <音频> <输出.jsonl> [块长秒] [并发]
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(os.environ.get('SONG_CUT_HOME') or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))

import mimo  # noqa: E402

from paths import FFMPEG, FFPROBE
CHUNK = 120.0
CONC = 3

PROMPT = ('请把这段音频里"演唱的歌词"逐句输出，每行格式：相对秒数|歌词。'
          '相对秒数以这段音频开头为 0，保留一位小数；歌词只写该句内容。'
          '只输出这些行，不要任何解释或标题；听不清的词写（？），不要编造。'
          '若这段没有演唱（纯说话/纯伴奏），只输出：NOSONG')

RANGE = re.compile(r'^\s*(\d{1,2}:\d{1,2}(?:[.,]\d{1,2})?|\d+(?:\.\d+)?)'
                   r'\s*[-–~]\s*(\d{1,2}:\d{1,2}(?:[.,]\d{1,2})?|\d+(?:\.\d+)?)\s*$')
RPIPE = re.compile(r'^\s*(\d{1,2}:\d{1,2}(?:[.,]\d{1,2})?|\d+(?:\.\d+)?)'
                   r'\s*[-–~]\s*(\d{1,2}:\d{1,2}(?:[.,]\d{1,2})?|\d+(?:\.\d+)?)\s*\|\s*(.+)$')
SINGLE = re.compile(r'^\s*(\d{1,2}:\d{1,2}(?:[.,]\d{1,2})?|\d+(?:\.\d+)?)\s*[\|,，:：]\s*(.+)$')
SPEAK = re.compile(r'^(?:SPEAKER[_-]?\d+|说话人\d*)\s*[:：]\s*', re.I)


def _to_sec(tok):
    parts = str(tok).strip().split(':')
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(tok)


def _clean(body):
    b = SPEAK.sub('', body or '').strip().strip('`').strip('"').strip("'")
    return re.sub(r'^[\|\s]+', '', b).strip()


def _parse(txt, off):
    """支持三种输出：'12.3|歌词'、'0:02.6-0:11.0'+下一行歌词、'31.4-33.0 | SPEAKER_00: 歌词'"""
    rows = []
    lines = [l.strip().strip('`') for l in (txt or '').splitlines()]
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln or ln.upper().startswith('NOSONG'):
            i += 1
            continue
        m = RPIPE.match(ln)
        if m:
            t0, t1 = _to_sec(m.group(1)), _to_sec(m.group(2))
            body = _clean(m.group(3))
            if len([c for c in body if not c.isspace()]) >= 2:
                rows.append({'start': off + t0, 'end': off + max(t1, t0 + 0.8), 'text': body})
            i += 1
            continue
        m = RANGE.match(ln)
        if m:
            t0, t1 = _to_sec(m.group(1)), _to_sec(m.group(2))
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            body = ''
            if j < len(lines) and not RANGE.match(lines[j]) and not SINGLE.match(lines[j]):
                body = _clean(lines[j]); i = j + 1
            else:
                i += 1
            if len([c for c in body if not c.isspace()]) >= 2:
                rows.append({'start': off + t0, 'end': off + max(t1, t0 + 0.8), 'text': body})
            continue
        m = SINGLE.match(ln)
        if m:
            t0 = _to_sec(m.group(1))
            body = _clean(m.group(2))
            if not re.fullmatch(r'[\d.\-\s~–]+', body or '') and \
                    len([c for c in body if not c.isspace()]) >= 2:
                rows.append({'start': off + t0,
                             'end': off + t0 + max(0.8, 0.22 * len(body)), 'text': body})
        i += 1
    rows.sort(key=lambda r: r['start'])
    return rows


def _dur(src):
    out = subprocess.run(
        [FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', src],
        capture_output=True, text=True,
    ).stdout
    try:
        return float((json.loads(out).get('format') or {}).get('duration'))
    except Exception:
        return 0.0


def _slice(src, a, b, out):
    r = subprocess.run(
        [FFMPEG, '-v', 'error', '-y', '-ss', f'{a:.2f}', '-to', f'{b:.2f}', '-i', src,
         '-ar', '16000', '-ac', '1', out],
        capture_output=True,
    )
    return r.returncode == 0


def transcribe(src, out='asr.jsonl', chunk=CHUNK, conc=CONC, verbose=True):
    total = _dur(src)
    if total <= 0:
        raise RuntimeError('无法读取音频时长')
    blocks, t = [], 0.0
    while t < total:
        blocks.append((t, min(total, t + chunk))); t += chunk
    results, fails, lock = {}, [], threading.Lock()

    def work(i):
        a, b = blocks[i]
        wav = f'/tmp/mimoasr_{threading.get_ident()}_{i}.wav'
        for attempt in range(3):
            try:
                if not _slice(src, a, b, wav):
                    raise RuntimeError('切片失败')
                txt, _u = mimo._ask(PROMPT, [wav], max_tokens=1600, timeout=180)
                with lock:
                    results[i] = _parse(txt, a)
                Path(wav).unlink(missing_ok=True)
                return
            except Exception:
                time.sleep(2 + 4 * attempt)
        with lock:
            fails.append(i); results[i] = []

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        list(ex.map(work, range(len(blocks))))
    if verbose:
        print(f'[mimo-asr] {len(blocks)} 块完成，失败 {len(fails)}，耗时 {time.time()-t0:.0f}s', flush=True)
    if fails and len(fails) > max(1, 0.1 * len(blocks)):
        raise RuntimeError(f'MiMo 转写失败块过多：{len(fails)}/{len(blocks)}')
    rows = []
    for i in range(len(blocks)):
        rows.extend(results.get(i) or [])
    rows.sort(key=lambda r: r['start'])
    ded = []
    for r in rows:
        if ded and abs(r['start'] - ded[-1]['start']) < 0.4 and r['text'][:6] == ded[-1]['text'][:6]:
            continue
        ded.append(r)
    with open(out, 'w', encoding='utf-8') as f:
        for r in ded:
            chars = [c for c in r['text'] if not c.isspace()]
            step = max(0.08, (r['end'] - r['start']) / max(1, len(chars)))
            words = [[round(r['start'] + k * step, 2), round(r['start'] + (k + 1) * step, 2), c]
                     for k, c in enumerate(chars)]
            f.write(json.dumps({'start': round(r['start'], 2), 'end': round(r['end'], 2),
                                'text': r['text'], 'words': words}, ensure_ascii=False) + '\n')
    return out


if __name__ == '__main__':
    transcribe(sys.argv[1], sys.argv[2],
               float(sys.argv[3]) if len(sys.argv) > 3 else CHUNK,
               int(sys.argv[4]) if len(sys.argv) > 4 else CONC)
