#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_v3.py —— v3 精切队列：一场一场跑，跑完重建页面；原始音轨保留 7 天后自动清理"""
import json, re, subprocess, sys, time
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'lib'))
Q = ROOT/'queue'/'streams_v3.json'
PY = PY_BIN
SKIP_KW = ('舰长', '合唱', '连麦', '毕业', '生日会', '游戏')


def log(m):
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {m}'
    print(line, flush=True)
    with open(ROOT/'logs'/'run_v3.log', 'a', encoding='utf-8') as f:
        f.write(line+'\n')


def sweep(days=7):
    """原始音轨保留 days 天"""
    import os
    now = time.time()
    for f in (ROOT/'res').glob('*.m4a'):
        try:
            if now - f.stat().st_mtime > days*86400:
                f.unlink(); log(f'清理旧音轨 {f.name}')
        except Exception:
            pass


import llmcfg as _LC

def judge_available():
    import urllib.request

    request = urllib.request.Request(_LC.HEALTH)
    if _LC.KEY:
        request.add_header('Authorization', 'Bearer ' + _LC.KEY)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status == 200
    except OSError:
        return False


def main(limit=10**6):
    if not Q.exists() and not (ROOT/'queue'/'streams.json').exists():
        log('未找到队列文件 queue/streams_v3.json 或 queue/streams.json；'
            '可参考 queue/streams.sample.json 的格式自行创建')
        return
    if not Q.exists():
        q = json.loads((ROOT/'queue'/'streams.json').read_text(encoding='utf-8'))
        for x in q:
            x['status'] = 'pending'
        Q.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding='utf-8')
    q = json.loads(Q.read_text(encoding='utf-8'))
    # 上次被中途杀掉（如机器重启）的场次，重置为 pending 以便续跑
    for x in q:
        if x.get('status') == 'running':
            x['status'] = 'pending'
    Q.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding='utf-8')
    PAUSE = ROOT/'run'/'PAUSE'
    done = 0
    while done < limit:
        while PAUSE.exists():
            log('已暂停（run/PAUSE 存在），10 分钟后复查')
            time.sleep(600)
        q = json.loads(Q.read_text(encoding='utf-8'))     # 每轮重读，外部改动即时生效
        it = None
        for cand in q:
            if cand['status'] in ('pending', 'fail'):
                it = cand
                break
        if it is None:
            break
        if any(k in it['title'] for k in SKIP_KW):
            it['status'] = 'skip'
            Q.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding='utf-8')
            continue
        if int(it.get('tries', 0)) >= 2:
            it['status'] = 'fail_final'
            Q.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding='utf-8')
            continue
        if not judge_available():
            log('判断模型不可用。请检查 JUDGE_HEALTH 和凭据，恢复服务后重新运行队列。')
            return 1
        it['tries'] = int(it.get('tries', 0)) + 1
        it['status'] = 'running'
        Q.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding='utf-8')
        m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', it['title'])
        ds = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''
        log(f"开始 #{it['idx']} {it['title'][:34]} ({it['bvid']})")
        t0 = time.time()
        tagp = f'{it["bvid"]}_p{it.get("page") or 1}' if (it.get('page') or 1) > 1 else it["bvid"]
        slog = ROOT/'logs'/f'v3_{tagp}_t{it.get("tries", 1)}.log'
        pg = int(it.get('page') or 1)
        with open(slog, 'w', encoding='utf-8') as sf:
            sf.write(f'== {time.strftime("%Y-%m-%d %H:%M:%S")} {it["bvid"]} P{pg} {it["title"]}\n')
            sf.flush()
            r = subprocess.run(
                [PY, ROOT / 'pipeline/pipe_v3.py', it['bvid'], it['title'], ds, str(pg)],
                stdout=sf, stderr=subprocess.STDOUT, text=True)
        it['status'] = 'done' if r.returncode == 0 else 'fail'
        it['seconds'] = int(time.time() - t0)
        # 重新读盘再写，避免覆盖期间的外部改动
        q2 = json.loads(Q.read_text(encoding='utf-8'))
        for x in q2:
            if x['bvid'] == it['bvid'] and int(x.get('page') or 1) == pg:
                x.update({'status': it['status'], 'seconds': it['seconds'], 'tries': it['tries']})
        Q.write_text(json.dumps(q2, ensure_ascii=False, indent=1), encoding='utf-8')
        log(f"  {'完成' if r.returncode == 0 else '失败'} 用时 {it['seconds']//60} 分钟")
        subprocess.run([PY, ROOT / 'lib/build_site.py'], capture_output=True)
        sweep()
        done += 1
    log(f'本轮结束，处理 {done} 场')


if __name__ == '__main__':
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10**6))