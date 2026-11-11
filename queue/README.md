# queue/ 说明

| 文件 | 作用 |
|---|---|
| `streams_v3.json`（或 `streams.json`） | 场次队列：`idx/bvid/page/title/status/tries`；`status` ∈ `pending/fail/done/skip/running` |
| `songs_index_new.json` | 成品索引（歌曲元数据 + LRC 文本），由流水线写入 |
| `asr_v3/<bvid>_pN.jsonl` | 整场转写缓存（可断点续跑） |
| `qc_rejects.json` | 拦截记录（歌名 + 原因 + 指标） |
| `qc_metrics.jsonl` | 入库成品指标（锚定/召回/同步/误差/响度…） |

`streams.sample.json` 是格式示例，复制成 `streams_v3.json` 后按需填写即可。
