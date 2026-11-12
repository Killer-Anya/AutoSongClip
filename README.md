# VTuber Auto Song Clipper｜VTuber 录播歌切工作流

**English** · [简体中文](README.zh-CN.md)

Submit a recording URL to extract performances, identify the songs, align their lyrics, and review the results. Approved performances can then be published to a web song library.

[Case study](#case-study) · [Workflow](#workflow) · [Quick start](#quick-start) · [Technology](#technology) · [Quality requirements](#quality-requirements) · [Development log](#development-log)

## Case study

- **VTuber**: 妮莉安Lily
- **VTuber profile**: [妮莉安Lily on Bilibili](https://space.bilibili.com/3493271057730096?spm_id_from=333.337.0.0)
- **Recording platform**: [Bilibili singing stream archive, November 26, 2023](https://www.bilibili.com/video/BV1ej411L7qb/) (example from the processing log)
- **Live player**: [Open the 妮莉安Lily song library](http://101.43.7.149:18081/web/)

The screenshots were captured from the deployed V1 player on November 10, 2026. This repository includes the V2 pipeline and web player source. V2 is undergoing batch testing on the server.

> **Copyright and takedown.** The recordings, performances, lyrics, cover artwork, and character imagery shown in this case study belong to their respective rights holders. The screenshots illustrate the project. If you believe any displayed material infringes your rights, contact the maintainer with a link, the material at issue, and a description of your rights. The maintainer will review removal or correction requests. Keep personal information and proof of ownership out of public issues. [Contact the maintainer](https://github.com/Killer-Anya/songcut/issues/new)

<table>
  <tr>
    <td align="center" valign="top"><img src="docs/images/player-desktop.jpg" height="375" alt="Desktop player with cover art, synchronized lyrics, and playback controls"></td>
    <td align="center" valign="top"><img src="docs/images/player-mobile.jpg" height="375" alt="Mobile player with the current lyric and playback controls"></td>
    <td align="center" valign="top"><img src="docs/images/library-mobile.jpg" height="375" alt="Mobile song library filtered by performance date"></td>
  </tr>
  <tr>
    <td align="center">Desktop player</td>
    <td align="center">Mobile player</td>
    <td align="center">Mobile library</td>
  </tr>
</table>

## Workflow

[![The flow starts with a Bilibili recording. Invalid audio ends the session. Each detected singing segment is identified, cut, aligned and checked. A failed candidate is logged and rejected. Passing clips are packaged for manual review. Approved clips are published and unapproved clips remain pending.](docs/images/workflow-en.svg)](docs/images/workflow-en.svg)

Symbols follow [ISO 5807:1985](https://www.iso.org/standard/11955.html). Matching circles (A and B) continue the flow in the next phase.

[Quality requirements](docs/质量要求.md#english) · [Measured results](docs/指标与质量报告.md#english-summary) · [Architecture notes](docs/架构说明.md)

## Quick start

### Download, extract, and double-click to preview

1. [Download the ZIP](https://github.com/Killer-Anya/songcut/archive/refs/heads/main.zip) and extract the whole folder.
2. Install [Python 3.10 or later](https://www.python.org/downloads/). On macOS, double-click `Start SongCut.command`. On Windows, double-click `Start SongCut.bat`.
3. Keep the launcher window open while using the player. The preview only needs Python and starts with an empty library. To load your own tracks, follow the [player notes](site/README.md).

On Linux, run `python3 site/server.py 18081 --open` in the extracted folder. If port 18081 is in use, choose another port in that command.

### Set up and process a recording

Run the full pipeline on Linux. In the extracted folder, install the dependencies and download the CTranslate2 version of Whisper small. On Ubuntu or Debian, use the following commands.

```bash
sudo apt install python3 python3-venv ffmpeg util-linux procps
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='models/small')"
```

| What you have | How to proceed |
| --- | --- |
| Text review and MiMo audio access | The server uses GLM-5.3-Flash for text review and MiMo-V2.6-Flash for audio spot checks. The public code defaults to a compatible local proxy on port 18090. Follow the [configuration example](docs/架构说明.md#文本服务与资源配置) to set `JUDGE_API`, `JUDGE_HEALTH`, `JUDGE_MODEL`, and `JUDGE_KEY`. Supply `TONGJI_API_KEY` when using the Tongji proxy. |
| Text review access without MiMo | Use the command below. Local Whisper and lyric checks run as usual, and audio review is recorded as `skipped`. The deployed V1 used local transcription, GLM text review, and manual listening. This option follows that division of work while retaining V2 lyric checks. |
| Source audio and a transcript cache, without model API access | The server-tested cached path is `python3 pipeline/pipe_offline.py <BV-ID> [part]`. It needs `res/<recording-tag>.m4a`, `queue/asr_v3/<recording-tag>.jsonl`, and a local lyric corpus or catalog. It may query NetEase Cloud Music for missing lyrics. See the [queue notes](queue/README.md) to prepare a transcript cache. |

Replace the URL, title, and date with your recording details. The `?p=2` in the URL selects part 2. This command disables all MiMo calls and uses the text review service you configured.

```bash
MIMO_VERIFY=0 MIMO_ASR=0 MIMO_ANCHOR=0 python3 pipeline/pipe_v3.py \
  'https://www.bilibili.com/video/BV1xxxxxxxxx/?p=2' 'Recording title' 2026-01-01
```

Find the outputs in `library/` and `queue/songs_index_new.json`. Before publishing, keep only approved entries in the pending index. Put the matching M4A files under `site/audio/` using the relative paths in the index, then run `python3 tools/publish_new.py` to rebuild the library page. See the [queue notes](queue/README.md) for batch input.

### Verified low-resource baseline

| Component | Server tested on November 12, 2026 |
| --- | --- |
| CPU and memory | 2 vCPUs on AMD EPYC 7K62, 3,723 MiB RAM, and about 2 GiB swap. Local transcription runs on the CPU. |
| OS and tools | Ubuntu 24.04.4 LTS, Python 3.12.3, and project-provided FFmpeg / FFprobe static build `n9.0.2-17-g2a571b6068`. |
| Disk | About 69 GB total and 36 GB free at the time of the check. Audio tracks, caches, and clips consume additional space. |
| Execution and timing | One job at a time. The most recent 15 V2 sessions had a median of about 31 minutes from download to packaging. The handoff reports around 10 minutes with a transcript cache and 35–50 minutes for a cold run. |

The default guard defers transcription below 1,200 MB available memory and stops it below 350 MB during a run. The table gives a tested baseline. Stability below that configuration needs further testing. Runtime varies with the recording, cache, and service availability.

## Technology

| Component | Technology and responsibility |
| --- | --- |
| Audio acquisition | Python standard-library requests retrieve Bilibili metadata and DASH audio. The player serves approved audio from the local media directory. |
| Media processing | PyAV decodes and resamples for analysis. NumPy measures energy and silence. FFmpeg stream-copies cuts, FFprobe checks format, and FFmpeg `ebur128` measures loudness and true peak. |
| Local transcription and alignment | faster-whisper and CTranslate2 run CPU INT8 transcription. zhconv normalizes Chinese text, pypinyin supplies pinyin, and the project uses DTW and local re-anchoring to handle repeated or missing lines. |
| External services | OpenAI-compatible endpoints serve GLM text review and MiMo audio review. NetEase Cloud Music supplies song candidates and reference lyrics. |
| Queue and publishing | Python entry points run single sessions, batches, and cached reprocessing. JSON and JSONL store queue state, caches, and metrics. The server uses systemd, Bash, `flock`, and `free` for supervision and resource control. |
| Web player | HTML, CSS, JavaScript, and `HTMLAudioElement`. The Python preview server supports HTTP byte ranges for seeking. |

`pipeline/` contains the entry points, `lib/` the processing stages, `tools/` the review and publishing tools, `site/` the player, and `docs/` the documentation.

## Quality requirements

SongCut draws on ITU-R BS.1770 and EBU R 128 for audio measurement and Netflix's timing and readability guidelines for subtitles. **Those sources define methods and delivery principles. SongCut sets its own thresholds for long livestream audio, source preservation, and line-timed lyrics.** Loudness is measured and flagged while the source level is preserved. Alignment checks use the local transcript as a reference. Independent listening or manual annotation is needed to establish timing against the performance itself. [Quality requirements and references](docs/质量要求.md#english) · [Sample results](docs/指标与质量报告.md#english-summary)

## Development log

The [development log](docs/开发日志.md#english) records V1 deployment, V2 stage validation, model comparisons, recovery from service errors, and checks run on the public code. [Sanitized log samples](logs/) show stage output and failure reasons.

## Contributing and license

When reporting a problem, include the version, steps to reproduce, and expected and observed results. Changes to cut points or lyric timing should include sample details, before-and-after measurements, and listening results. Remove credentials, private recordings, and full lyrics before sharing logs or test data. [Contribution guide](CONTRIBUTING.md#english)

The project code is released under the **MIT License**. Preserve the copyright and permission notice when redistributing the code or substantial portions of it. The case study's recordings, songs, lyrics, artwork, and character imagery retain their respective rights. [Full license](LICENSE)
