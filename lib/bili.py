#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bili.py —— 直连 B站 API 下载音频（绕开网页 412 风控）"""
import json
import re
import urllib.request
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


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
API = "https://api.bilibili.com"


def _get(url, cookie=None, timeout=25):
    h = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_buvid():
    d = _get(f"{API}/x/frontend/finger/spi")
    return f"buvid3={d['data']['b_3']}"


def parse_bvid(s):
    m = re.search(r"(BV[0-9A-Za-z]{10})", s)
    if m:
        return m.group(1)
    raise ValueError(f"无法解析 BV 号: {s}")


def parse_page(url):
    m = re.search(r"[?&]p=(\d+)", url)
    return int(m.group(1)) if m else 1


def video_info(bvid, cookie):
    d = _get(f"{API}/x/web-interface/view?bvid={bvid}", cookie)
    if d.get("code") != 0:
        raise RuntimeError(f"view 失败: {d.get('code')} {d.get('message')}")
    v = d["data"]
    return {
        "bvid": v["bvid"], "aid": v["aid"], "title": v["title"],
        "uploader": v["owner"]["name"], "duration": v["duration"],
        "pages": [{"cid": p["cid"], "page": p["page"], "part": p["part"],
                   "duration": p["duration"]} for p in v.get("pages", [])],
    }


def audio_streams(aid, cid, cookie):
    d = _get(f"{API}/x/player/playurl?avid={aid}&cid={cid}&fnval=16&fourk=1", cookie)
    if d.get("code") != 0:
        raise RuntimeError(f"playurl 失败: {d.get('code')} {d.get('message')}")
    dash = (d.get("data") or {}).get("dash") or {}
    out = []
    for a in dash.get("audio") or []:
        u = a.get("baseUrl") or a.get("base_url")
        if u:
            out.append({"id": a.get("id"), "bandwidth": a.get("bandwidth"), "url": u})
    out.sort(key=lambda x: x["bandwidth"], reverse=True)
    return out


def download(url, dest, cookie, chunk=1 << 20):
    h = {"User-Agent": UA, "Referer": "https://www.bilibili.com/", "Cookie": cookie}
    req = urllib.request.Request(url, headers=h)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            b = r.read(chunk)
            if not b:
                break
            f.write(b)
            got += len(b)
            if total and got % (20 * 1024 * 1024) < chunk:
                print(f"  {got*100//total}% {got/1048576:.0f}/{total/1048576:.0f}MB", flush=True)
    tmp.replace(dest)
    return dest


def fetch_audio(url_or_id, out_dir=f"{ROOT}/newaudio"):
    cookie = get_buvid()
    bvid = parse_bvid(url_or_id)
    page = parse_page(url_or_id)
    info = video_info(bvid, cookie)
    pg = next((p for p in info["pages"] if p["page"] == page), info["pages"][0])
    print(f"[info] {info['title']} | {info['uploader']} | {info['duration']}s | "
          f"共{len(info['pages'])}P | 处理 P{pg['page']}: {pg['part']}", flush=True)
    streams = audio_streams(info["aid"], pg["cid"], cookie)
    if not streams:
        raise RuntimeError("无可用音轨")
    # 严格取最高带宽档（30280 通常为最高：约 230kbps/48kHz/立体声）
    pick = max(streams, key=lambda x: x.get("bandwidth") or 0)
    print(f"[audio] 可用档位: " + ", ".join(f"{s['id']}/{s['bandwidth']//1000}k" for s in streams), flush=True)
    print(f"[audio] 选用 id={pick['id']} {pick['bandwidth']//1000}kbps", flush=True)
    out = Path(out_dir) / f"{bvid}_p{pg['page']}.m4a"
    download(pick["url"], out, cookie)
    print(f"[done] {out}", flush=True)
    return out, info, pg


if __name__ == "__main__":
    import sys
    fetch_audio(sys.argv[1] if len(sys.argv) > 1 else "")