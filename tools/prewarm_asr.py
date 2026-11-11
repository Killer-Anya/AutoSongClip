#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prewarm_asr.py —— 预热转写：只用本地 whisper，不碰同济 GLM

同济被限流时，队列无法做逐句判定；但转写（最耗时的环节）不需要 GLM。
这个脚本按队列顺序把接下来的场次**先转写完并落盘**，等 GLM 恢复后每场只需 10 分钟即可出歌。

用法: python3 tools/prewarm_asr.py [最多预热几场]
安全：转写统一走 heavy.sh（串行锁 + 内存闸门），磁盘剩余 <8G 自动停止。
"""
import json
import shutil
import subprocess
import time
import sys
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


PY = PY_BIN

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lib'))


def log(m):
    print(m, flush=True)
    with open(ROOT / 'logs' / 'prewarm.log', 'a', encoding='utf-8') as f:
        f.write(m + '\n')


def free_gb():
    out = subprocess.run('df -BG --output=avail / | tail -1', shell=True, capture_output=True, text=True).stdout.strip()
    return int(out.replace('G', '')) if out else 0


def duration(p):
    out = subprocess.run(
        [FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', p],
        capture_output=True, text=True).stdout
    try:
        return float((json.loads(out).get('format') or {}).get('duration'))
    except Exception:
        return 0.0


def asr_ok(cache, dur):
    if not cache.exists() or cache.stat().st_size < 1000 or dur <= 0:
        return False
    lines = [l for l in cache.read_text(encoding='utf-8').splitlines() if l.strip()]
    if not lines:
        return False
    last = json.loads(lines[-1])['end']
    return last >= dur * 0.95 and last <= dur * 1.05 + 60


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    sys.path.insert(0, str(ROOT / 'lib'))
    import bili
    cookie = bili.get_buvid()
    q = json.loads((ROOT / 'queue' / 'streams_v3.json').read_text(encoding='utf-8'))
    todo = [i for i in q if i['status'] in ('pending', 'fail')]
    # 队列正在跑场次时不要抢重活（避免 OOM），等它跑完再预热
    for _ in range(720):
        ps = subprocess.run('ps -eo cmd', shell=True, capture_output=True, text=True).stdout
        busy = any('pipeline/pipe_v3.py' in ln and 'pgrep' not in ln and 'ps -eo' not in ln
                   for ln in ps.splitlines())
        if not busy:
            break
        log('队列正在跑场次，预热等 5 分钟')
        time.sleep(300)
    # 按队列文件里的顺序（已按日期+分P排好）
    done_n = 0
    for it in todo:
        if done_n >= limit:
            break
        if free_gb() < 8:
            log('磁盘剩余不足 8G，停止预热')
            break
        page = int(it.get('page') or 1)
        tag = f"{it['bvid']}_p{page}" if page > 1 else it['bvid']
        cache = ROOT / 'queue' / 'asr_v3' / f'{tag}.jsonl'
        src = ROOT / 'res' / f'{tag}.m4a'
        wk = ROOT / 'tmp_asr' / tag
        wk.mkdir(parents=True, exist_ok=True)
        if src.exists() and asr_ok(cache, duration(src)):
            log(f'已有转写，跳过 {tag}')
            shutil.rmtree(wk, ignore_errors=True)
            continue
        if not src.exists():
            log(f'下载 {tag}（P{page}）')
            try:
                got, _info, _pg = bili.fetch_audio(it['bvid'] if page == 1 else f"{it['bvid']}?p={page}",
                                                  str(wk))
                shutil.copyfile(got, src)
                Path(got).unlink(missing_ok=True)
            except Exception as e:
                log(f'  下载失败 {type(e).__name__}: {e}')
                continue
        dur = duration(src)
        wav = wk / 'full.wav'
        log(f'解码 {tag}（{dur/60:.0f} 分钟）')
        subprocess.run(f'{PY} {ROOT}/lib/decode_wav.py "{src}" "{wav}"', shell=True)
        log(f'转写 {tag} 开始')
        for attempt in range(6):
            r = subprocess.run(
                ['bash', ROOT / 'scripts/heavy.sh', PY, ROOT / 'lib/asr_chunk.py', wav, cache, '2'],
                capture_output=True, text=True,
            )
            if r.returncode not in (75, 76):
                break
            log(f'  重活锁/内存受限（{r.returncode}），等 5 分钟重试')
            time.sleep(300)
        ok = asr_ok(cache, dur)
        log(f'转写 {tag} {"完成" if ok else "失败（退出码 %d）" % r.returncode}')
        shutil.rmtree(wk, ignore_errors=True)
        done_n += 1
    log(f'预热结束，本次处理 {done_n} 场')


if __name__ == '__main__':
    main()