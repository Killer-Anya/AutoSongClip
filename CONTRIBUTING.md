# 贡献指南 / Contributing

[简体中文](#简体中文) · [English](#english)

## 简体中文

### 报告问题

开 Issue 时注明提交版本、操作系统和 Python 版本、处理入口、出错阶段、重现步骤、预期与实际结果。涉及音频时，说明录播分 P 和相对时间点。附相关脱敏日志，样本应由你有权共享的内容制作。版权或下架请求请使用 [README 的联系入口](README.zh-CN.md#项目案例)。

### 提交修改

1. 从 `main` 建立分支，提交范围聚焦的 Pull Request。描述用户遇到的问题、改动后的行为和验证方法。
2. 播放器改动应验证本地启动、空曲库、已有曲目播放与进度跳转。切歌、排轴或质检改动应提供同一录播片段的前后对照，标明分 P、切点、首末歌词和人工抽听结果。修改门槛时注明受影响的指标和可能变化的拦截范围。
3. 运行与改动相关的验证，写清用过的环境、样本和仍待验证的部分。若修改安装、命令或默认值，请同步更新两个 README。
4. 提交前检查变更文件。密钥、私人录播、完整歌词、模型权重与真实曲库索引保留在本地。生成的 HTML 可能包含歌词和场次信息，请在提交前核对。

代码采用 [MIT 许可证](LICENSE)。贡献中使用第三方代码或素材时，注明来源，并确认你有权以相应许可提交。

## English

### Report a problem

Include the commit, operating system, Python version, entry point, failing stage, steps to reproduce, and expected and observed results. For audio issues, give the recording part and relative timestamp. Attach relevant sanitized logs and use material you have permission to share. The [case study](README.md#case-study) has the contact route for rights and takedown requests.

### Submit a change

1. Create a branch from `main` and submit a focused pull request. Describe the user-facing problem, resulting behavior, and validation.
2. For player changes, check local startup, the empty library, playback, and seeking. For cutting, alignment, or quality changes, compare the same segment before and after. Include the recording part, cut boundaries, first and last lyric timestamps, and listening results. For threshold changes, explain which checks and acceptance decisions may change.
3. Run checks that match your change and report the environment, samples, and remaining verification. Update both READMEs when setup, commands, or defaults change.
4. Review the files being committed. Keep secrets, private recordings, full lyrics, model weights, and real catalog data local. Review generated HTML for embedded lyrics and recording metadata.

The code is distributed under the [MIT License](LICENSE). Credit third-party code or media and confirm you have permission to submit it under its applicable license.
