# scripts/ — 开发期测试脚本（非生产入口）

> ⚠️ 这里都是**开发调试 / 烟囱测试**用的脚本，**正式跑专利用不到本目录**。
> 生产全流程走 [`src/patentradar/server/runner.py`](../src/patentradar/server/runner.py)
> （Web Dashboard 或 `POST /api/run/{pub}` 触发），不依赖这里任何文件。

| 脚本 | 用途 | 备注 |
|---|---|---|
| `run_full_pipeline.py` | 模块 2-4 的测试 wrapper | 固定从 `tests/decompose/outputs/<PUB>/` 读模块一 fixture，**不重跑 decompose**，不适合跑生产专利 |
| `smoke_aihubmix.py` | 跨 LLM backend 烟囱测试 | 换 backend 时手动验证链路是否通，产物写到 `tests/smoke_aihubmix/` |
