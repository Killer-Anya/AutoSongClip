import sys
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qwen_sent.py —— 逐句判定：歌词演唱 / 说话（同济 Qwen，非思考模式，批量）"""
import json, sys, time, urllib.request
from pathlib import Path

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
DELAY = 1.2          # 批间隔（秒），遇限流自动加倍
_SLOW = [0]

SYS = ('给你直播录播的逐句 ASR 文本（带编号i）。逐句判断是「歌词演唱」还是「说话」还是「无法判断」。'
       '演唱=歌词、有旋律、句子短而整齐、常重复；说话=口语聊天、念弹幕、答谢礼物、聊天互动、'
       '对伴奏旋律的讨论、报幕。ASR有错字，请按语义和上下文判断。'
       '输出JSON数组[{"i":编号,"k":"s|t|?"}]，s=演唱, t=说话, ?=无法判断（如只有啦啦啦或空）。只输出JSON。')


def call(items, tries=6):
    user = json.dumps(items, ensure_ascii=False)
    body = {'model': MODEL, 'temperature': 0.05, 'max_tokens': 4000,
            **_C.EXTRA,
            'messages': [{'role': 'system', 'content': SYS}, {'role': 'user', 'content': user}]}
    data = json.dumps(body).encode()
    for k in range(tries):
        try:
            req = urllib.request.Request(API, data=data,
                                         headers={'Authorization': 'Bearer ' + KEY,
                                                  'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=150) as r:
                j = json.loads(r.read().decode())
            try:
                import os
                U = f'{ROOT}/queue/token_usage.json'
                d = json.load(open(U)) if os.path.exists(U) else {}
                d['calls'] = d.get('calls', 0) + 1
                d['tokens'] = d.get('tokens', 0) + int((j.get('usage') or {}).get('total_tokens') or 0)
                json.dump(d, open(U, 'w'))
            except Exception:
                pass
            c = j['choices'][0]['message'].get('content') or ''
            s, e = c.find('['), c.rfind(']')
            if s < 0:
                raise ValueError('no json: ' + c[:80])
            return json.loads(c[s:e + 1])
        except Exception as ex:
            msg = str(ex)
            print(f'  重试{k+1} {type(ex).__name__} {msg[:80]}', flush=True)
            if '429' in msg:                     # 触发限流：加长批间隔 + 长时间退避
                _SLOW[0] = min(3, _SLOW[0] + 1)
                DELAY = 1.2 * (2 ** _SLOW[0])
                wait = 25 + 20 * k
                print(f'    限流，等待 {wait}s', flush=True)
                time.sleep(wait)
                continue
            try:                      # 同济通道掉线时自动重连，避免整场失败
                _C.ensure_online()
            except Exception:
                pass
            time.sleep(2 + 2 * k)
    return []



TALK_HINTS = ('哈哈哈', '谢谢', '弹幕', '直播间', '关注', '关注一下', '礼物', '榜', '打赏',
              '大家', '宝宝', '姐妹们', '兄弟们', '拜拜', '晚安', '早安', '开播', '下播',
              '牌子', '粉丝团', '卡', '打卡', '整点', '抽奖', '投票', '连麦', '字幕组')


def obvious_talk(text):
    """本地判定"明显是说话"的句子，省掉大模型调用（只处理铁定是闲聊的，宁可漏判）"""
    s = (text or '').strip()
    if not s:
        return True
    if any(h in s for h in TALK_HINTS):
        return True
    if len(s) >= 40:                       # 歌词几乎不会这么长
        return True
    if s.endswith(('？', '?', '！', '!')) and len(s) > 12:
        return True
    if s.count('，') + s.count('。') >= 3:  # 多个句读，像口语
        return True
    return False


def main(src, out, per=60):
    recs = [json.loads(l) for l in Path(src).read_text(encoding='utf-8').splitlines() if l.strip()]
    recs = [r for r in recs if r['text'].strip()]
    for i, r in enumerate(recs, 1):
        r['i'] = i
    out = Path(out)
    done = {}
    if out.exists():
        for x in json.loads(out.read_text(encoding='utf-8')):
            done[x['i']] = x['k']
    # 先用本地规则标出"明显是说话"的句子，减少大模型请求量
    pre = 0
    for r in recs:
        if r['i'] not in done and obvious_talk(r['text']):
            done[r['i']] = 't'
            pre += 1
    if pre:
        print(f'本地预判为说话 {pre} 句（省下大模型请求）', flush=True)
        out.write_text(json.dumps([{'i': k, 'k': done[k]} for k in sorted(done)],
                                  ensure_ascii=False), encoding='utf-8')
    todo = [r for r in recs if r['i'] not in done]
    print(f'待判 {len(todo)} 句（总 {len(recs)}）', flush=True)
    for round_no in range(4):                      # 失败批次多轮重试，绝不静默丢句
        batch = todo if round_no == 0 else [r for r in todo if r['i'] not in done]
        if not batch:
            break
        for i in range(0, len(batch), per):
            chunk = batch[i:i + per]
            res = call([{'i': r['i'], 't': r['text'][:90]} for r in chunk], tries=5)
            for x in res:
                if isinstance(x, dict) and 'i' in x:
                    done[int(x['i'])] = x.get('k', '?')
            out.write_text(json.dumps([{'i': k, 'k': done[k]} for k in sorted(done)],
                                      ensure_ascii=False), encoding='utf-8')
            print(f'  轮{round_no+1} {min(i+per,len(batch))}/{len(batch)} 累计 {len(done)}', flush=True)
            if _SLOW[0] and len(done) % 300 == 0:
                _SLOW[0] = max(0, _SLOW[0] - 1)   # 稳定后逐步恢复速度
            time.sleep(1.2 * (2 ** _SLOW[0]))
        missing = [r for r in todo if r['i'] not in done]
        if not missing:
            break
        print(f'  还有 {len(missing)} 句未判定，等待网络后重试', flush=True)
        try:
            _C.ensure_online()
        except Exception:
            pass
        time.sleep(8 + 6 * round_no)
    missing = [r for r in recs if r['i'] not in done]
    if len(missing) > 0.05 * len(recs):
        print(f'FAIL 仍有 {len(missing)}/{len(recs)} 句未判定', flush=True)
        sys.exit(3)
    print(f'完成（{len(done)} 句，缺 {len(missing)}）', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 60)