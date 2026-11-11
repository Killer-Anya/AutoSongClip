# 贡献指南

## 原则

1. **质量优先于数量**：任何"为了多出片而放宽门槛"的改动必须给出指标对比。
2. **切点与歌词保持解耦**：切点只看音频与逐句标签；歌词只用于验证，不得反过来改切点。
3. **不引入人声分离**：这是项目定位（保原声）。
4. **每个门槛都要可自动判定**，并在 `logs/qc_rejects_sample.json` 里留原因。

## 开发

```bash
pip install -r requirements.txt   # 见 README 依赖段
python3 tools/validate_library.py  # 成品终检
python3 tools/audit_published.py   # 独立复核
```

## 提交前自检

- [ ] 改动后跑一场完整流水线，确认能产出至少 1 首且指标正常
- [ ] 不硬编码任何 API key（用环境变量 `TONGJI_API_KEY`）
- [ ] 日志里不出现个人信息
