#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_report.py —— 生成当日进度报告（写入 docs/进度报告_YYYY-MM-DD.txt）"""
import json, collections, time
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


def load(p, d=None):
    p = Path(p)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else (d if d is not None else [])

def main():
    q = load(ROOT/'queue/streams_v3.json', [])
    st = collections.Counter(i['status'] for i in q)
    new = load(ROOT/'queue/songs_index_new.json', [])
    rej = load(ROOT/'queue/qc_rejects.json', [])
    rc = collections.Counter(x['reason'].split('：')[0][:14] for x in rej)
    lines = [f'歌切 V5 进度报告 {time.strftime("%Y-%m-%d %H:%M")}', '']
    lines.append(f"场次：完成 {st.get('done',0)} / 待跑 {st.get('pending',0)} / 跳过 {st.get('skip',0)} "
                 f"/ 失败 {st.get('fail',0)+st.get('fail_final',0)} / 进行中 {st.get('running',0)}")
    lines.append(f"新版入库：{len(new)} 首")
    by_date = collections.Counter(x.get('date','') for x in new)
    for d, n in sorted(by_date.items()):
        titles = [x['title'] for x in new if x.get('date') == d]
        lines.append(f"  {d}: {n} 首 — {'、'.join(titles)}")
    lines.append('')
    lines.append(f"拦截累计：{len(rej)} 条")
    for k, v in rc.most_common(10):
        lines.append(f"  {k}: {v}")
    mf = ROOT/'queue/qc_metrics.jsonl'
    if mf.exists():
        rows = [json.loads(l) for l in mf.read_text(encoding='utf-8').splitlines() if l.strip()]
        if rows:
            med = [r['qc'].get('err_med') for r in rows if r.get('qc', {}).get('err_med') is not None]
            anc = [r['qc'].get('anchor') for r in rows if r.get('qc', {}).get('anchor') is not None]
            lines.append('')
            lines.append(f"入库指标：{len(rows)} 首有记录；锚定中位 {sorted(anc)[len(anc)//2]:.0%}，"
                         f"行级误差中位 {sorted(med)[len(med)//2]:.2f}s" if med and anc else '')
    out = ROOT/'docs'/f'进度报告_{time.strftime("%Y-%m-%d")}.txt'
    out.write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))
    print('\n已写入', out)

if __name__ == '__main__':
    main()