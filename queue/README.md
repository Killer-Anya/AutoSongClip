# 队列与转写缓存 / Queue and Transcription Cache

复制 `streams.sample.json` 为 `queue/streams_v3.json`，填入 BV 号、分 P、场次标题和顺序。新任务用 `status: "pending"`、`tries: 0`。在仓库根目录运行 `python3 pipeline/run_v3.py 5` 可处理至多五次任务执行。队列会记录 `running`、`done`、`skip`、`fail` 或 `fail_final`。

Copy `streams.sample.json` to `queue/streams_v3.json`. Set each recording's BV ID, part, title, and position. New jobs use `status: "pending"` and `tries: 0`. Run `python3 pipeline/run_v3.py 5` from the repository root to run up to five processing attempts.

## 无模型 API 时准备转写 / Prepare a transcript without a model API

配置 Linux 依赖和本地 Whisper 后，先在队列里放入一条待处理录播，再从仓库根目录执行。以下命令只下载音轨并生成本地转写缓存。源音轨进入 `res/`，转写进入 `queue/asr_v3/`。

After installing the Linux dependencies and local Whisper, put one pending recording in the queue and run the following from the repository root. This downloads the audio into `res/` and prepares its local transcript under `queue/asr_v3/`.

```bash
python3 tools/prewarm_asr.py 1
```

缓存重处理还需要本地歌词语料。`queue/official_cache.json` 是以 `曲名|原唱` 为键的 JSON，值形如 `[["第一行歌词", "第二行歌词"], "歌曲来源"]`。也可以用带 LRC 的现有曲库索引。用你有权处理的内容填充语料。第一 P 使用 BV 号作文件名，后续分 P 使用 `BV号_pN`。

Cached processing also uses a local lyric corpus. In `queue/official_cache.json`, use `title|original performer` as the key and a value such as `[["first lyric line", "second lyric line"], "source"]`. An existing catalog containing LRC can also supply lyrics. Use material you have permission to process. The first part uses the BV ID as the file stem, and later parts use `BV_ID_pN`.

待审核曲目、质量指标和拦截记录分别写入 `songs_index_new.json`、`qc_metrics.jsonl` 和 `qc_rejects.json`。正式网页使用 `songs_index.json`。更多步骤见 [架构说明](../docs/架构说明.md)。

Review candidates, metrics, and rejections are written to `songs_index_new.json`, `qc_metrics.jsonl`, and `qc_rejects.json`. The player build reads the published index, `songs_index.json`. See the [architecture notes](../docs/架构说明.md) for the data flow.
