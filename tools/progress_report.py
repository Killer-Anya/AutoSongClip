#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""progress_report.py —— 一行命令出一份进度摘要（给每小时汇报用）"""
import json
import collections
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




def main():
    q = json.loads((ROOT / 'queue' / 'streams_v3.json').read_text(encoding='utf-8'))
    st = collections.Counter(i['status'] for i in q)
    newf = ROOT / 'queue' / 'songs_index_new.json'
    new = json.loads(newf.read_text(encoding='utf-8')) if newf.exists() else []
    rejf = ROOT / 'queue' / 'qc_rejects.json'
    rej = json.loads(rejf.read_text(encoding='utf-8')) if rejf.exists() else []
    rc = collections.Counter(x['reason'].split('：')[0][:14] for x in rej)
    print(f"场次：完成 {st.get('done',0)} / 待跑 {st.get('pending',0)} / 跳过 {st.get('skip',0)}"
          f" / 失败 {st.get('fail',0)+st.get('fail_final',0)} / 进行中 {st.get('running',0)}")
    print(f"新版入库：{len(new)} 首")
    if new:
        dur = [x.get('dur', 0) for x in new]
        print(f"  平均时长 {sum(dur)/len(dur):.0f}s；最近：{new[-1]['title']}（{new[-1].get('date','')}）")
    print(f"拦截记录：{len(rej)} 条")
    for k, v in rc.most_common(6):
        print(f"  {k}: {v}")
    # 最近一场的逐首结果
    logs = sorted((ROOT / 'logs').glob('v3_*_t*.log'), key=lambda p: p.stat().st_mtime)[-1:]
    for lg in logs:
        lines = lg.read_text(encoding='utf-8', errors='ignore').splitlines()
        pub = [l for l in lines if '质检通过' in l]
        rej_l = [l for l in lines if '不发布' in l or '跳过' in l]
        print(f"最近一场 {lg.name}：通过 {len(pub)} 首 / 拦截 {len(rej_l)} 条")
        for l in rej_l[-4:]:
            print('  ' + l.strip()[:90])
    mf = ROOT / 'queue' / 'qc_metrics.jsonl'
    if mf.exists():
        rows = [json.loads(l) for l in mf.read_text(encoding='utf-8').splitlines() if l.strip()]
        if rows:
            r = rows[-1]
            qc = r.get('qc', {})
            print(f"最近入库指标：锚定{qc.get('anchor')} 召回{qc.get('recall')} "
                  f"同步{qc.get('err_rate')} 中位{qc.get('err_med')}s 切片{r.get('cut')}s")


if __name__ == '__main__':
    main()