#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipe_offline.py —— 离线模式：不调用任何大模型，用本地歌词语料检歌并出片

用途：同济 API 被限流/不可用期间继续产出。
流程：转写缓存 → 语料检歌(corpus_detect) → 歌词校正边界 → 静音吸附 → 流复制切歌
      → 全场转写切片排轴 → 门槛+质检 → 打包（三件套）→ 写索引与指标

用法: python3 pipeline/pipe_offline.py <bvid> [page]
"""
import os as _os
from pathlib import Path as _P
ROOT = _P(_os.environ.get('SONG_CUT_HOME') or _P(__file__).resolve().parent.parent)
_ROOT = ROOT
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'pipeline'))

import align_lib as AL          # noqa: E402
import align_qwen as AQ         # noqa: E402
import audiospec as AS          # noqa: E402
import corpus_detect as CD      # noqa: E402
import audio_regions as AR      # noqa: E402
import identify2 as I2          # noqa: E402
import os                       # noqa: E402
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

os.environ['JUDGE_OFF'] = '1'   # 离线：禁用一切大模型调用
import cutwin as CW             # noqa: E402
import dtw_align as D           # noqa: E402
import gates as G               # noqa: E402
import qc as QC                 # noqa: E402
import boundary as B            # noqa: E402
import subprocess               # noqa: E402


FF = FFMPEG
LIB = ROOT / 'library'
IDX = ROOT / 'queue' / 'songs_index_new.json'
METRICS = ROOT / 'queue' / 'qc_metrics.jsonl'
REJ = ROOT / 'queue' / 'qc_rejects.json'
VER = 'OFFLINE-2026-11-10'


def log(*m):
    print(' '.join(str(x) for x in m), flush=True)


def reject(what, reason, metrics=None):
    try:
        d = json.loads(REJ.read_text(encoding='utf-8')) if REJ.exists() else []
    except Exception:
        d = []
    d.append({'what': what, 'reason': reason, 'metrics': metrics or {},
              'at': time.strftime('%Y-%m-%d %H:%M:%S')})
    REJ.write_text(json.dumps(d[-500:], ensure_ascii=False, indent=1), encoding='utf-8')


def run_command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=3600)


def find_bounds(src, t0, dur):
    a = max(0, t0 - 90); b = t0 + dur + 60
    out = '/tmp/offex.wav'
    result = run_command([FF, '-v', 'error', '-y', '-ss', f'{a:.2f}', '-to', f'{b:.2f}',
                          '-i', src, '-ar', '16000', '-ac', '1', '-f', 'wav', out])
    if result.returncode != 0:
        return t0, t0 + dur, False, False
    env, hop = B.load_env(out)
    s1, _, oks, _ = B.find(env, hop, t0 - a)
    _, e1, _, oke = B.find(env, hop, t0 - a + dur)
    if not oke:
        _, e1, _, oke = B.find(env, hop, t0 - a + dur, fwd=20.0)
    return round(a + s1, 2), round(a + e1, 2), oks, oke


def main(bvid, page=1):
    tag = f'{bvid}_p{page}' if page > 1 else bvid
    src = ROOT / 'res' / f'{tag}.m4a'
    if not src.exists():
        raise RuntimeError(f'缺源音轨 {src}')
    ok, why, src_info = AS.check_source(src)
    if not ok:
        raise RuntimeError(f"源音轨不达标：{'；'.join(why)}")
    asr = ROOT / 'queue' / 'asr_v3' / f'{tag}.jsonl'
    recs = [json.loads(l) for l in asr.read_text(encoding='utf-8').splitlines() if l.strip()]
    regions = CD.detect(bvid, page)
    log(f'[离线] 语料检歌命中 {len(regions)} 段')
    if len(regions) < 3:
        # 语料不够时，用"音频里有伴奏"的段做候选，再用网易云歌词核验认歌
        audio_regs = AR.detect(str(src))
        log(f'[离线] 音频候选 {len(audio_regs)} 段，用歌词核验认歌')
        for r in audio_regs:
            a, d = r['start'], r['dur']
            if any(not (a + d <= x['start'] or x['start'] + x['dur'] <= a + 20) for x in regions):
                continue
            segs_r = [{'start': s['start'] - a, 'end': s['end'] - a, 'text': s['text'],
                       'words': [[w[0] - a, w[1] - a, w[2]] for w in (s.get('words') or [])]}
                      for s in recs if s['end'] > a - 2 and s['start'] < a + d + 2]
            txt = ' '.join(s['text'] for s in segs_r)
            info = I2.identify_region(txt, segs_r)
            if info.get('title'):
                regions.append({'start': a, 'dur': d, 'title': info['title'],
                                'artist': info.get('artist', ''), 'ratio': info.get('recall') or 0,
                                'src': 'audio'})
        log(f'[离线] 合并后候选 {len(regions)} 段')
    if not regions:
        log('[离线] 无可处理段落'); return
    wd = Path('/tmp/off') / tag
    wd.mkdir(parents=True, exist_ok=True)
    date = ''
    try:
        q = json.loads((ROOT / 'queue' / 'streams_v3.json').read_text(encoding='utf-8'))
        for it in q:
            if it['bvid'] == bvid:
                import re as _re
                m = _re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', it.get('title') or '')
                if m:
                    date = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
                break
    except Exception:
        pass
    ix = json.loads(IDX.read_text(encoding='utf-8')) if IDX.exists() else []
    ix = [x for x in ix if not (x.get('bvid') == bvid and int(x.get('page') or 1) == page)]
    next_no = max([int(x['no']) for x in ix], default=0) + 1
    added = 0
    for r in regions:
        title, artist = r['title'], r.get('artist', '')
        off = AQ.official(title, artist)
        if not off or not off[0]:
            reject(f'{bvid} {title}', '取歌词失败'); continue
        lyrics = off[0]
        t0, dur = r['start'], r['dur']
        if r.get('src') == 'audio':
            # 音频检出的边界很粗，先按歌词把范围放宽，让歌词对齐去找真正的首末句
            t0 = max(0.0, t0 - 25.0)
            dur = dur + 70.0
        na, nb, ok_s, ok_e, _info = CW.window(recs, lyrics, t0, t0 + dur,
                                              find_bounds=lambda _s, a, d: find_bounds(src, a, d))
        if nb - na < 90:
            reject(f'{bvid} {title}', f'窗口过短 {nb-na:.0f}s'); continue
        na, nb = AS.frame_align(na), AS.frame_align(nb)
        cut = wd / 'cut.m4a'
        run_command([FF, '-v', 'error', '-y', '-ss', f'{na:.3f}', '-to', f'{nb:.3f}',
                     '-i', src, '-c', 'copy', cut])
        ok_cut, why_cut, cut_info = AS.check_cut(cut, nb - na, src_info)
        if not ok_cut:
            reject(f'{bvid} {title}', f"成品校验：{'；'.join(why_cut)}", cut_info); continue
        segs = [{'start': s['start'] - na, 'end': s['end'] - na, 'text': s['text'],
                 'words': [[w[0] - na, w[1] - na, w[2]] for w in (s.get('words') or [])]}
                for s in recs if s['end'] > na - 1 and s['start'] < nb + 1]
        segs = [s for s in segs if s['text'].strip()]
        lrc = AL.align(title, artist, segs, nb - na)
        amap = D.dtw_map(lyrics, segs)
        anchor = min(1.0, len(amap) / max(1, len(lyrics)))
        ok_g, mg, why_g = G.check(lrc, lyrics, anchor, nb - na)
        if not ok_g:
            reject(f'{bvid} {title}', f"门槛：{'；'.join(why_g)}", mg); continue
        ok_q, bad_q, qm = QC.check(lrc, lyrics, amap, segs, nb - na)
        if not ok_q:
            reject(f'{bvid} {title}', f"质检：{'；'.join(bad_q)}", qm); continue
        no = str(next_no + added).zfill(3)
        pkg = LIB / f"{date or '未标注'}_{title}_{artist}".replace('/', '／')
        pkg.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cut, pkg / '01_audio.m4a')
        (pkg / '02_lyrics.lrc').write_text(lrc, encoding='utf-8')
        run_command([PY_BIN, ROOT / 'tools/make_ass.py', title, artist, pkg / '02_lyrics.lrc',
                     pkg / '03_karaoke.ass', f'{nb-na:.1f}'])
        loud = AS.loudness(str(cut))
        ix = [x for x in ix if x.get('file') != f'{pkg.name}/01_audio.m4a']
        ix.append({'no': no, 'title': title, 'artist': artist, 'dur': round(nb - na, 1),
                   'file': f'{pkg.name}/01_audio.m4a', 'lrc': lrc, 'lang': '国语', 'style': '未分类',
                   'date': date, 'stream': '', 'bvid': bvid, 'na': round(na, 3), 'nb': round(nb, 3),
                   'stream_time': '%02d:%02d:%05.2f' % (na // 3600, (na % 3600) // 60, na % 60),
                   'quality_status': 'PASS', 'pipeline': VER,
                   'peak': loud.get('tpeak'), 'lufs': loud.get('lufs')})
        IDX.write_text(json.dumps(ix, ensure_ascii=False, indent=1), encoding='utf-8')
        with open(METRICS, 'a', encoding='utf-8') as mf:
            mf.write(json.dumps({'v': VER, 'title': title, 'artist': artist, 'bvid': bvid,
                                 'cut': round(nb - na, 2), 'na': na, 'nb': nb,
                                 'qc': qm, 'loud': loud}, ensure_ascii=False) + '\n')
        added += 1
        log(f"    {no} {title[:14]:<16}{nb-na:.0f}s 锚定{qm['anchor']:.0%} 召回{qm['recall']:.0%} 同步{qm['err_rate']:.0%}")
    log(f'[离线] 本场新增 {added} 首')


if __name__ == '__main__':
    try:
        main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    except Exception:
        import traceback; traceback.print_exc(); sys.exit(1)
