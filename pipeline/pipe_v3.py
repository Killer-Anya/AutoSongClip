#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipe_v3.py —— 精密切歌流水线（保留前奏/尾音，三件套交付）
每场：下载原音轨 → 全流转写(beam2) → GLM分类 → 合并区间 → 识曲+GLM复核
      → 边界扩展到静音处 → 原音轨流复制 → 逐曲 beam5 重转排轴 → 门槛 → 打包(audio/lrc/ass)
用法: pipe_v3.py <bvid> "<场次标题>" <日期 YYYY-MM-DD>
"""
import os as _os
from pathlib import Path as _P
ROOT = _P(_os.environ.get('SONG_CUT_HOME') or _P(__file__).resolve().parent.parent)
_ROOT = ROOT
import json, os, re, shutil, subprocess, sys, time, wave
from pathlib import Path
import numpy as np

sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'lib')); sys.path.insert(0, str(ROOT/'tools'))
import align_lib as AL, gates as G, dtw_align as D, align_qwen as AQ, bound_lyric as BL, qc as QC, cutwin as CW
import audiospec as AS
import mimo as MM
import mimo_align as MA
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

WORK = Path('/tmp/sw'); RES = ROOT/'res'; LIB = ROOT/'library'
IDX = ROOT/'queue'/'songs_index_new.json'   # 新版单独入库，等全部跑完再合并上架
PY = PY_BIN
FF = FFMPEG
SR, HOP = 16000, 0.01
BAD = ('Zither','Harp','字幕','索兰娅','MING PAO','ISRC')


def log(*m): print(' '.join(str(x) for x in m), flush=True)


FINDS = []
METRICS = ROOT/'queue'/'qc_metrics.jsonl'
VER = 'V2-2026-11-10'

REJ = ROOT/'queue'/'qc_rejects.json'


def reject(what, reason, metrics=None):
    try:
        d = json.loads(REJ.read_text(encoding='utf-8')) if REJ.exists() else []
    except Exception:
        d = []
    d.append({'what': what, 'reason': reason, 'metrics': metrics or {},
              'at': __import__('time').strftime('%Y-%m-%d %H:%M:%S')})
    REJ.write_text(json.dumps(d[-500:], ensure_ascii=False, indent=1), encoding='utf-8')



def run_command(args, timeout=7200):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def env_of(x):
    w = int(0.02*SR); h = int(HOP*SR)
    return np.array([np.sqrt(np.mean(x[i:i+w]**2)+1e-12) for i in range(0, max(1, len(x)-w), h)])


def find_bounds(src, t0, dur):
    """V4：绝对静音阈值 + 最短静音 500ms + 切点必须在静音段内
    返回 (start, end, ok_start, ok_end)；ok=False 表示该侧找不到合规静音"""
    import boundary as B
    a = max(0, t0-90); b = t0+dur+60
    out = '/tmp/v3ex.wav'
    result = run_command([FF, '-v', 'error', '-y', '-ss', f'{a:.2f}', '-to', f'{b:.2f}',
                          '-i', src, '-ar', str(SR), '-ac', '1', '-f', 'wav', out])
    if result.returncode != 0:
        return t0, t0+dur, False, False
    env, hop = B.load_env(out)
    s1, _, oks, _ = B.find(env, hop, t0-a)
    thr_s = getattr(B.find, 'last_thr', None)
    _, e1, _, oke = B.find(env, hop, t0-a+dur)
    if not oke:                                   # 尾音后没静音：把搜索窗口放宽到 20 秒
        _, e1, _, oke = B.find(env, hop, t0-a+dur, fwd=20.0)
    thr_e = getattr(B.find, 'last_thr', None)
    FINDS.append({'thr_start': thr_s, 'thr_end': thr_e,
                  'floor': round(getattr(B.find, 'last_floor', 0.0) or 0.0, 1)})
    return round(a+s1, 2), round(a+e1, 2), oks, oke


def shift_lrc(lrc, delta, dur):
    out = []
    for ln in (lrc or '').split('\n'):
        m = re.match(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)', ln.strip())
        if not m: continue
        t = int(m.group(1))*60+float(m.group(2))+delta
        if 0.2 <= t <= dur: out.append(f'[{int(t)//60:02d}:{t%60:05.2f}]{m.group(3)}')
    return '\n'.join(out)


def asr_file(wav, out, beam=2, expect=None):
    """转写结果必须存在且覆盖到接近结尾，避免复用半截文件"""
    if out.exists() and out.stat().st_size > 100:
        try:
            rows=[json.loads(l) for l in out.read_text(encoding='utf-8').splitlines() if l.strip()]
            if rows:
                last=rows[-1]['end']
                if expect is None:
                    return True
                # 缓存必须与当前音轨时长匹配：过短说明没转完，过长说明是别的音轨留下的
                if last >= expect*0.95 and last <= expect*1.05 + 60:
                    return True
        except Exception:
            pass
    # 优先走 MiMo 云端转写（快 4~6 倍、不占本机）；失败自动回退本地 whisper
    import os as _os
    if _os.environ.get('MIMO_ASR', '0') == '1':   # 默认用本地 whisper 出时间戳（MiMo 转写句太稀，排轴会退化）
        for attempt in range(2):
            try:
                run_command([PY, ROOT / 'lib/mimo_asr.py', wav, out, '120', '3'])
                if out.exists() and out.stat().st_size > 100:
                    rows = [json.loads(l) for l in out.read_text(encoding='utf-8').splitlines() if l.strip()]
                    if rows and (expect is None or rows[-1]['end'] >= expect * 0.95):
                        log(f'    MiMo 转写完成（{len(rows)} 句）')
                        return True
                    log('    MiMo 转写覆盖不足，回退本地 whisper')
                    break
            except Exception as e:
                log(f'    MiMo 转写异常（{type(e).__name__}），第 {attempt+1} 次')
                time.sleep(10)
        log('    本地 whisper 兜底转写')

    # 重活锁被占 / 内存不足时等一等再试，不要把这归为"转写失败"（会白白消耗场次重试）
    for attempt in range(24):
        r = subprocess.run(
            ['bash', ROOT / 'scripts/heavy.sh', PY, ROOT / 'lib/asr_chunk.py', wav, out, str(beam)],
            capture_output=True, text=True, timeout=7200,
        )
        if out.exists() and out.stat().st_size > 100:
            return True
        if r.returncode in (75, 76):
            log(f'    重活受限（rc={r.returncode}），5 分钟后再试（第 {attempt+1} 次）')
            time.sleep(300)
            continue
        log(f'    [debug] asr rc={r.returncode} err={(r.stderr or "")[-200:]}')
        return False
    return False


def get_duration(wav):
    with wave.open(str(wav)) as w:
        return w.getnframes()/float(w.getframerate())


def main(bvid, title, date, page=1):
    page = int(page or 1)
    TAG = f'{bvid}_p{page}' if page > 1 else bvid
    WORK.mkdir(exist_ok=True); RES.mkdir(exist_ok=True); LIB.mkdir(exist_ok=True)
    src = RES/f'{TAG}.m4a'
    if not src.exists():
        import bili
        log(f'[1] 下载原始音轨 P{page}')
        url = bvid if page == 1 else f'{bvid}?p={page}'
        # 必须用 fetch_audio 返回的路径：WORK 里会堆积历史文件，取"最新的一个"会拿错音轨
        got_path, _info, _pg = bili.fetch_audio(url, str(WORK))
        if not got_path or not Path(got_path).exists():
            raise RuntimeError('下载失败')
        shutil.copyfile(got_path, src)
        try:
            Path(got_path).unlink()          # 下载完立刻清掉临时文件，避免累积
        except Exception:
            pass
    log(f'    原始音轨 {src.stat().st_size/1e6:.0f}MB')
    ok_src, why_src, src_info = AS.check_source(src)
    if not ok_src:
        reject(f'{bvid} P{page}', f"源音轨不达标：{'；'.join(why_src)}", src_info)
        raise RuntimeError(f"源音轨不达标：{'；'.join(why_src)}")
    log(f"    源参数 {src_info['codec']} {src_info['sr']}Hz {src_info['ch']}ch {src_info['br']//1000}kbps")

    wd = WORK/TAG; wd.mkdir(exist_ok=True)
    wav_all = wd/'full.wav'
    if not wav_all.exists():
        log('[2] 解码整场')
        run_command([PY, ROOT / 'lib/decode_wav.py', src, wav_all])
    (ROOT/'queue'/'asr_v3').mkdir(parents=True, exist_ok=True)
    asr_all = ROOT/'queue'/'asr_v3'/f'{TAG}.jsonl'
    dur_all = get_duration(wav_all)
    if not asr_file(wav_all, asr_all, 2, dur_all):
        raise RuntimeError('全流转写失败')
    recs = [json.loads(l) for l in asr_all.read_text(encoding='utf-8').splitlines() if l.strip()]
    recs = [r for r in recs if r['text'].strip()]
    log(f'    转写句数 {len(recs)}')

    def classify_and_region():
        lab = wd/'labels.json'
        # 分类必须覆盖至少 95% 句子，否则作废（防止 GLM 抖动导致整场 0 候选）
        if lab.exists():
            # 缓存自检：不足 95% 句子 或 演唱比例低得离谱（多半是上次中途掉线）→ 作废重做
            try:
                m = {x['i']: x['k'] for x in json.loads(lab.read_text(encoding='utf-8'))}
                s_ratio = sum(1 for v in m.values() if v == 's') / max(1, len(m))
                if len(m) < 0.95 * len(recs) or (len(recs) > 300 and s_ratio < 0.03):
                    log(f'    分类缓存不可信（{len(m)}/{len(recs)} 句，演唱占比 {s_ratio:.1%}），作废重做')
                    lab.unlink()
            except Exception:
                try: lab.unlink()
                except Exception: pass
        if not lab.exists():
            log('[3] GLM 逐句分类')
            run_command([PY, ROOT / 'lib/qwen_sent.py', asr_all, lab, '120'])
        lab_map = {x['i']: x['k'] for x in json.loads(lab.read_text(encoding='utf-8'))}
        if len(lab_map) < 0.95 * len(recs):
            log(f'    分类只覆盖 {len(lab_map)}/{len(recs)} 句，作废重做')
            lab.unlink()
            run_command([PY, ROOT / 'lib/qwen_sent.py', asr_all, lab, '120'])
            lab_map = {x['i']: x['k'] for x in json.loads(lab.read_text(encoding='utf-8'))}
            if len(lab_map) < 0.95 * len(recs):
                raise RuntimeError(f'分类覆盖不足 {len(lab_map)}/{len(recs)}')
        clean = {}
        for i, r in enumerate(recs, 1):
            k = lab_map.get(i, '?')
            c = re.sub(r'[^\u4e00-\u9fff]', '', r['text'])
            if k == 't' and (any(b in r['text'] for b in BAD) or (len(c) >= 6 and len(set(c)) <= 2)): k = '?'
            clean[i] = k
        cj = wd/'clean.json'
        cj.write_text(json.dumps([{'i':k,'k':v} for k,v in sorted(clean.items())], ensure_ascii=False), encoding='utf-8')
        regs_f = wd/'regions.json'
        run_command([PY, ROOT / 'lib/seg_regions.py', asr_all, cj, regs_f, '60', '22'])
        return json.loads(regs_f.read_text(encoding='utf-8')), clean

    regs, clean = classify_and_region()
    log(f'[4] 候选区间 {len(regs)}')
    # 合理性校验：长场次候选区间少得离谱，先怀疑缓存了坏标注，重做一次再判
    total_min = dur_all / 60
    if len(regs) < max(2, total_min / 40):
        log(f'    候选区间偏少（{len(regs)} 个 / {total_min:.0f} 分钟），重建分类再判一次')
        for f in (wd/'labels.json', wd/'clean.json', wd/'regions.json'):
            try: Path(f).unlink()
            except Exception: pass
        regs, clean = classify_and_region()
        log(f'    重做后候选区间 {len(regs)}')
        if len(regs) < max(2, total_min / 40):
            log('    仍然偏少——这场确实歌少（如闲聊/鉴赏回），按实际情况继续')

    import identify2 as IL, judge_lib as J

    # 同一首歌被静默切断成两个区间时合并（间隔 <40s 且识别为同一首），避免发布半截片段
    cache_id = {}

    def quick_id(r):
        k = r['text'][:400]
        if k not in cache_id:
            s0, d0 = r['start'], r['dur']
            segs_r = [{'start': s['start']-s0, 'end': s['end']-s0, 'text': s['text'],
                       'words': [[w[0]-s0, w[1]-s0, w[2]] for w in (s.get('words') or [])]}
                      for s in recs if s['end'] > s0-2 and s['start'] < s0+d0+2]
            cache_id[k] = IL.identify_region(r['text'], segs_r) or {}
        return cache_id[k]

    def gap_to(i):
        return regs[i + 1]['start'] - (regs[i]['start'] + regs[i]['dur']) if i + 1 < len(regs) else 1e9

    merged, i = [], 0
    while i < len(regs):
        cur = dict(regs[i])
        # 只有"紧挨着"的区间才值得花识别成本去判断是否同一首歌
        if cur['dur'] >= 90 and gap_to(i) <= 40:
            info0 = quick_id(cur)
        else:
            info0 = {}
        j = i + 1
        while info0.get('title') and j < len(regs):
            nxt = regs[j]
            gap = nxt['start'] - (cur['start'] + cur['dur'])
            info1 = quick_id(nxt)
            if (info1.get('title') == info0.get('title')
                    and (info1.get('artist') or '') == (info0.get('artist') or '')
                    and 0 <= gap <= 40):
                cur['dur'] = nxt['start'] + nxt['dur'] - cur['start']
                cur['text'] = (cur['text'] + ' ' + nxt['text'])
                log(f"    合并同一首歌的两段：+{nxt['dur']:.0f}s（{info0['title']}）")
                j += 1
            else:
                break
        merged.append(cur)
        i = j
    if len(merged) != len(regs):
        log(f'    区间合并后 {len(regs)} → {len(merged)}')
    regs = merged

    ix = json.loads(IDX.read_text(encoding='utf-8'))
    # 不清空该场已有条目：离线模式可能已经产出过歌，保留它们，新增的按成品路径覆盖同名条目
    before = len(ix)
    next_no = max([int(x['no']) for x in ix], default=0)+1
    added = 0
    for r in regs:
        if r['dur'] < 90: continue
        info = quick_id(r)
        if not info.get('title'):
            reject(f"{date}", f"识曲不确定：{info.get('why','')}")
            log(f"    跳过未识别区间（{info.get('why','')}）"); continue
        t_name = info['title']; artist = info.get('artist','')   # 网易云结果已是规范名，省一次大模型调用
        ver = J.verify_segment(r['text'], t_name) or {}
        if ver.get('chorus') or ver.get('playback') or ver.get('has_chat') or ver.get('complete') is False:
            log(f"    跳过 {t_name}（{ver.get('reason','合唱/播放/不完整')}）"); continue
        t0, dur = r['start'], r['dur']
        off = AQ.official(t_name, artist)
        lyrics = off[0] if off else []
        # 先用官方歌词首末句把区间校正到真正起止，再按静音吸附
        # 切点只用"音频+演唱标签"决定，歌词不参与（两套标准解耦）
        win = CW.audio_window(recs, clean, t0, dur,
                              find_bounds=lambda _s, a, d: find_bounds(src, a, d))
        if win is None:
            reject(f"{date} {t_name}", '区间内没有可用演唱跨度'); continue
        na, nb, ok_s, ok_e, info = win
        if nb - na < 60:
            reject(f"{date} {t_name}", f'窗口过短（{nb-na:.0f}s）')
            log(f'    不发布 {t_name}：窗口过短'); continue
        ndur = nb-na
        log(f'    边界 {t0:.0f}+{dur:.0f} → {na:.0f}+{ndur:.0f}（前奏+{t0-na:.1f}s）')
        def do_cut(a, b):
            a, b = AS.frame_align(a), AS.frame_align(b)
            cf = wd/f"cut_{added}.m4a"
            run_command([FF, '-v', 'error', '-y', '-ss', f'{a:.3f}', '-to', f'{b:.3f}',
                         '-i', src, '-c', 'copy', cf])
            return cf, a, b

        cut, na, nb = do_cut(na, nb)
        ok_cut, why_cut, cut_info = AS.check_cut(cut, nb-na, src_info)
        if not ok_cut:
            reject(f"{date} {t_name}", f"成品校验不通过：{'；'.join(why_cut)}", cut_info)
            log(f'    不发布 {t_name}：成品校验 {"；".join(why_cut)}'); continue
        loud = AS.loudness(cut)
        ok_l, why_l, _ = AS.check_loudness(loud)
        if not ok_l:
            log(f'    响度提示 {t_name}：{"；".join(why_l)}（不阻断，仅记录）')

        # 排轴用全场转写切片（切片自转的前奏段常有幻觉，会把首行锚到 0.5 秒）
        segs = [{'start': s['start']-na, 'end': s['end']-na, 'text': s['text'],
                 'words': [[w[0]-na, w[1]-na, w[2]] for w in (s.get('words') or [])]}
                for s in recs if s['end'] > na-1 and s['start'] < nb+1]
        segs = [s for s in segs if s['text'].strip() and not any(b in s['text'] for b in BAD)]
        if len(segs) < 12:
            wcut = wd/f"cut_{added}.wav"
            run_command([PY, ROOT / 'lib/decode_wav.py', cut, wcut])
            acut = wd/f"cut_{added}.jsonl"
            if asr_file(wcut, acut, 5):
                segs = [json.loads(l) for l in acut.read_text(encoding='utf-8').splitlines() if l.strip()]
                segs = [s for s in segs if s['text'].strip() and not any(b in s['text'] for b in BAD)]
        lrc = AL.align(t_name, artist, segs, ndur)
        amap = D.dtw_map(lyrics, segs) if lyrics else {}
        anchor = min(1.0, len(amap)/max(1,len(lyrics)))
        ok, m, why = G.check(lrc, lyrics, anchor, ndur)
        if not ok:
            reject(f"{date} {t_name}", f"门槛：{'；'.join(why)}", m)
            log(f"    不发布 {t_name}：{'；'.join(why)}"); continue
        # 切片标准（音频/标签侧）：片段内"说话"时长占比 ≤8%，超过不发布
        talk = sum(max(0.0, r['end'] - r['start']) for i, r in enumerate(recs, 1)
                   if clean.get(i) == 't' and r['start'] >= na and r['end'] <= nb)
        talk_ratio = talk / max(1.0, ndur)
        if talk_ratio > 0.08:
            reject(f"{date} {t_name}", f"片段内说话占比 {talk_ratio:.0%} > 8%", {'talk': round(talk_ratio, 3)})
            log(f'    不发布 {t_name}：说话占比 {talk_ratio:.0%}'); continue
        qok, qbad, qm = QC.check(lrc, lyrics, amap, segs, ndur)
        # 用 MiMo 的准确句时间做锚点，修正 DTW 在重复段上的错配；两种排轴取同步更好的那个
        try:
            anchors, ainfo = ([], {}) if os.environ.get('MIMO_ANCHOR', '0') != '1' else MA.get_anchors(str(cut), ndur, lyrics)
            if anchors and len(anchors) >= 5:
                fused = MA.fuse(QC.parse(lrc), anchors, lyrics, ndur)
                if fused:
                    fmap = D.dtw_map(lyrics, segs) if lyrics else {}
                    fok, fbad, fm = QC.check(fused, lyrics, fmap, segs, ndur)
                    base_rate = qm.get('err_rate') or 0.0
                    fuse_rate = fm.get('err_rate') or 0.0
                    log(f"    锚点融合：MiMo 锚点 {len(anchors)} 个，同步 {base_rate:.0%} → {fuse_rate:.0%}")
                    if False and fuse_rate > base_rate + 0.02:   # 实测 MiMo 锚点会拉低同步率，暂不采用，仅记录对比
                        lrc, amap, qok, qbad, qm = fused, fmap, fok, fbad, fm
                        log(f"    采用融合排轴（同步 {fuse_rate:.0%}）")
        except Exception as _e:
            log(f"    锚点融合跳过（{type(_e).__name__}）")
        if not qok:
            reject(f"{date} {t_name}", f"质检：{'；'.join(qbad)}", qm)
            log(f"    不发布 {t_name}：质检 {'；'.join(qbad)}"); continue
        # 独立验收（音频模型）：抽首/中/尾三段，确认确实在唱这些歌词、无说话、无拼接
        try:
            verify_clips = []
            for frac, tag in ((0.12, 'a'), (0.5, 'b'), (0.85, 'c')):
                cp = MM.clip(str(cut), max(0.0, ndur * frac), 20.0, f'/tmp/mv_{tag}.wav')
                if cp:
                    verify_clips.append(cp)
            mv = MM.verify_song(verify_clips, lyrics, t_name) if verify_clips else {}
        except Exception:
            mv = {}
        if mv:
            if mv.get('same_song') is False or mv.get('mixed_songs') is True or mv.get('has_talk') is True:
                reject(f"{date} {t_name}",
                       f"音频复核：同歌={mv.get('same_song')} 说话={mv.get('has_talk')} "
                       f"拼接={mv.get('mixed_songs')} 命中={mv.get('lines_hit')}", mv)
                log(f"    不发布 {t_name}：音频复核未通过（{str(mv.get('note'))[:40]}）"); continue
            log(f"    音频复核通过 {t_name}：同歌✓ 命中{mv.get('lines_hit')} 置信{mv.get('confidence')}")
        no = str(next_no+added).zfill(3)
        pkg = LIB/f"{date}_{t_name}_{artist}{'' if page == 1 else f'_P{page}'}".replace('/','／')
        pkg.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cut, pkg/'01_audio.m4a')
        (pkg/'02_lyrics.lrc').write_text(lrc, encoding='utf-8')
        run_command([PY, ROOT / 'tools/make_ass.py', t_name, artist, pkg / '02_lyrics.lrc',
                     pkg / '03_karaoke.ass', f'{ndur:.1f}'])
        ix = [x for x in ix if x.get('file') != f"{pkg.name}/01_audio.m4a"]   # 同一成品只留一条
        ix.append({'no':no,'title':t_name,'artist':artist,'dur':round(ndur,1),
                   'file':f"{pkg.name}/01_audio.m4a",'lrc':lrc,'lang':'国语','style':'未分类',
                   'date':date,'stream':title,'bvid':bvid,
                   'stream_time':'%02d:%02d:%05.2f'%(na//3600,(na%3600)//60,na%60),'na':round(na,3),'nb':round(nb,3),'quality_status':'PASS',
                   'pipeline':VER,'peak':loud.get('tpeak'),'lufs':loud.get('lufs')})
        rec = {'v': VER, 'title': t_name, 'artist': artist, 'bvid': bvid, 'page': page,
               'cut': round(ndur, 2), 'na': na, 'nb': nb, 'qc': qm,
               'talk': round(talk_ratio, 3), 'loud': loud,
               'cut_probe': cut_info, 'find': (FINDS[-2:] if FINDS else []), 'mimo': mv}
        with open(METRICS, 'a', encoding='utf-8') as mf:
            mf.write(json.dumps(rec, ensure_ascii=False)+'\n')
        # 写索引前重新读一遍，按 file 去重合并——绝不覆盖已有曲库（历史教训：整库被清空）
        try:
            disk = json.loads(IDX.read_text(encoding='utf-8'))
        except Exception:
            disk = []
        mine = {x.get('file') for x in ix}
        ix = [x for x in ix if x.get('file') in mine]
        ix = [x for x in disk if x.get('file') not in mine] + ix  # 旧条目被新结果替换
        seen = {x.get('file') for x in ix}
        _seen = {}
        for _x in ix:
            _seen[_x.get('file')] = _x
        ix = list(_seen.values())
        ix.sort(key=lambda x: (x.get('date') or '0000-00-00', x.get('no') or ''))
        IDX.write_text(json.dumps(ix, ensure_ascii=False, indent=1), encoding='utf-8')
        added += 1
        log(f"    {no} {t_name[:12]:<14} {ndur:.0f}s 前奏+{t0-na:.1f}s 歌词{m['lines']}行 锚定{anchor:.0%}")
    log(f'本场新增 {added} 首')
    shutil.rmtree(wd, ignore_errors=True)
    log('RESULT OK')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('用法: python3 pipeline/pipe_v3.py <bvid> "<场次标题>" [日期 YYYY-MM-DD] [分P, 默认1]')
        print('示例: python3 pipeline/pipe_v3.py BV1xxxxxxxxx "【直播回放】歌回 2026年01月01日19点场" 2026-01-01 1')
        sys.exit(2)
    try:
        main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv)>3 else '',
             sys.argv[4] if len(sys.argv)>4 else 1)
    except Exception as e:
        import traceback; traceback.print_exc(); print('RESULT FAIL', flush=True); sys.exit(1)
