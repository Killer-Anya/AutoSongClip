#!/bin/bash
# heavy.sh —— 重活（whisper/ASR/识别）统一入口：串行锁 + 内存闸门
#
# 背景：2026-11-04 00:22 / 00:42 两次 OOM 强杀 dsh-web，
#       原因是同机并行跑了两路 faster-whisper（各 ~500MB 模型 + 音频数组），
#       峰值 3.3G + swap 1.8G，超过 4G 物理内存。
#
# 用法：  heavy.sh <命令...>
#
# 行为：
#   1. flock 保证同一时刻只有一路重活；
#   2. 启动前检查可用内存，低于 MIN_AVAIL_MB 直接拒绝（默认 1200MB）；
#   3. 运行期每 10s 采样一次，可用内存低于 KILL_MB（默认 350MB）时主动退让。
set -u
ROOT=${SONG_CUT_HOME:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}
LOCK="$ROOT/run/heavy.lock"

if ! command -v flock >/dev/null || ! command -v free >/dev/null; then
  echo "[heavy] Requires Linux with flock and free." >&2
  exit 69
fi

mkdir -p -- "$ROOT/run" || exit 73
MIN_AVAIL_MB=${MIN_AVAIL_MB:-1200}
KILL_MB=${KILL_MB:-350}

avail() { free -m | awk '/^Mem:/{print $7}'; }

exec 200>"$LOCK" || exit 73
if ! flock -n 200; then
  echo "[heavy] 已有重活在跑，拒绝并发启动（避免 OOM）" >&2
  exit 75
fi

a=$(avail)
if [ "$a" -lt "$MIN_AVAIL_MB" ]; then
  echo "[heavy] 可用内存 ${a}MB < ${MIN_AVAIL_MB}MB，拒绝启动。" >&2
  echo "[heavy] 先等现有任务结束，或释放内存后重试。" >&2
  exit 76
fi

echo "[heavy] 可用内存 ${a}MB，开始执行：$*" >&2
"$@" &
pid=$!
while kill -0 "$pid" 2>/dev/null; do
  sleep 10
  a=$(avail)
  if [ "$a" -lt "$KILL_MB" ]; then
    echo "[heavy] 可用内存降至 ${a}MB，主动终止子进程 $pid 以保护系统" >&2
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    exit 77
  fi
done
wait "$pid"
exit $?
