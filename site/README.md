# Web player / 网页播放器

From the repository root, run `python3 site/server.py 18081` and open <http://127.0.0.1:18081/web/>. Python 3.10 or later is sufficient for the preview. The checked-in player contains an empty song list.

在仓库根目录运行 `python3 site/server.py 18081`，打开 <http://127.0.0.1:18081/web/>。预览只需要 Python 3.10 或以上。随源码附带的播放器曲库为空。

With your own `queue/songs_index.json`, run `python3 lib/build_site.py` to embed the catalog and lyrics. Place the referenced audio files in `site/audio/` and an optional cover at `site/web/cover.jpg`. The generated HTML can contain lyrics and catalog data. Use content you have permission to publish.

准备好自己的 `queue/songs_index.json` 后，运行 `python3 lib/build_site.py` 嵌入目录和歌词。把索引引用的音频放进 `site/audio/`，封面可放在 `site/web/cover.jpg`。生成的 HTML 可能包含曲库数据和歌词，发布时请使用你有权公开的素材。
