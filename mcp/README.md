# PatentRadar MCP 1.0

PatentRadar 的私有远程 MCP 服务。它按 `skills/patentradar` 的完整四模块规则运行：用户在自己的 Codex 中使用 ChatGPT 登录完成推理和内置网页搜索；服务器托管模块规则、严格校验阶段结果、协同用户自备搜索 Key，并生成 PDF 报告。

本目录是独立 uv 项目，不要求修改父项目。终端命令均在 `mcp/` 目录执行。

## 已实现

- Streamable HTTP MCP：`/mcp`
- 自动搜索策略：Codex 内置网页搜索始终参与
- 可选增强：有可用 Key 时组合 Tavily、Bocha、Exa、Brave；无 Key、无额度或失败时自动回退 Codex
- 搜索 Key 经 Fernet 加密后写入 SQLite，接口只返回是否配置
- 工作区和案件隔离，支持断点续跑
- 完整四模块工作流：权利要求拆解、竞品搜索与权1判定、全部 Claim Chart、报告
- 内置与 skill 同版的四份完整 agent prompt、三份 JSON Schema 和技术领域站点配置
- 服务端语义校验：全部 claim/feature 覆盖、SKU 锁定、status-score 映射、权1评分、失效规则、严格推理标记、证据缺口和报告结构
- 服务端 Markdown/PDF 生成
- 15 分钟有效的签名 PDF 下载地址
- Windows/macOS 双教程、Key 设置页

用户的 ChatGPT auth 永远不传给本服务。现有项目中读取 `~/.codex/auth.json` 的代码不被本 MCP 使用。

## 本地启动

```bash
cd mcp
uv sync
uv run patentradar-mcp
```

打开 <http://127.0.0.1:8000>。教程页可创建工作区令牌并生成 Codex 配置命令。

默认运行数据保存在 `mcp/data/`，已被 `.gitignore` 忽略。第一次启动会生成 `data/.master_key`；删除或更换该文件后，已经保存的搜索 Key 将无法解密。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PATENTRADAR_MCP_DATA_DIR` | `data` | SQLite、报告和本地主密钥目录 |
| `PATENTRADAR_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | MCP 与 PDF 对外地址 |
| `PATENTRADAR_MCP_HOST` | `127.0.0.1` | 监听地址；容器部署设为 `0.0.0.0` |
| `PATENTRADAR_MCP_PORT` | `8000` | 监听端口 |
| `PATENTRADAR_MASTER_KEY` | 自动生成 | Fernet 主密钥；生产环境应由托管平台 Secret 注入 |
| `PATENTRADAR_MCP_DEBUG` | 空 | `true` 时启用开发重载 |

生成生产主密钥：

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## MCP 工具

| 工具 | 作用 |
|---|---|
| `analysis_start` | 用公开号创建案件并自动选择搜索策略 |
| `analysis_next` | 获取当前阶段和输入材料 |
| `analysis_submit` | 校验并保存阶段 artifact |
| `provider_search` | 使用用户自备 Key：候选发现按 QueryPlan 最多3源，证据补搜使用全部已配置源 |
| `analysis_status` | 查看案件进度 |
| `analysis_report` | 获取签名 PDF 地址 |
| `search_key_status` | 只查询四个平台是否配置 |

典型的 agent 循环是 `analysis_start → analysis_next → analysis_submit`，依次执行四个模块。模块二和三始终使用 Codex 内置搜索；如果配置了 Key，必须同时调用 `provider_search`，再把两类结果合并、打开正文验活并核对 SKU。外部搜索失败或无额度不会中断案件。完成后调用 `analysis_report`。

外部搜索按父项目的两种模式运行：`discovery` 尊重本地 Codex QueryPlan 中每条查询的 `preferred_providers`，未指定时按语言使用与 `src/patentradar` 相同的默认顺序，每条最多 3 个已配置平台；`evidence` 按 Bocha → Brave → Tavily → Exa 顺序并发尝试全部已配置平台。未配置的平台不占名额，单个平台鉴权、额度或网络失败不会阻塞其他平台，结果按规范化 URL 做机械去重。

服务器不做申请人/关联品牌过滤、相关性裁决或证据验活。本地 Codex 必须把外部结果与内置搜索结果合并，完成语义去重、申请人过滤、正文/PDF/图片复核和 SKU 一致性判断。Codex 内置搜索是必选通道，不由外部结果替代。

## 测试

```bash
cd mcp
uv run pytest
uv run python -m compileall -q src
```

测试覆盖用户隔离、加密存储、脱敏错误、工作流顺序、MCP 鉴权、工具清单、网页 API 和 PDF 生成。搜索测试使用模拟 HTTP，不消耗真实额度。

## Linux 服务器运行

Docker 不是 MCP 协议的必需品，只是推荐的 Linux 服务端封装方式，能够一次安装 WeasyPrint、Pango 和 Noto CJK 字体。Windows/macOS 最终用户不需要 Docker、Python 或这些字体依赖。

### Docker

```bash
cd mcp
docker build -t patentradar-mcp .
docker run --rm -p 8000:8000 \
  -e PATENTRADAR_MCP_HOST=0.0.0.0 \
  -e PATENTRADAR_PUBLIC_BASE_URL=https://mcp.yccode.xyz \
  -e PATENTRADAR_MASTER_KEY='替换为 Fernet 主密钥' \
  -v patentradar-data:/app/data \
  patentradar-mcp
```

公网部署必须使用 HTTPS，并在 Cloudflare 或源站增加速率限制。1.0 当前使用工作区 Bearer Token；正式开放注册前，应使用 Cloudflare Access/邀请机制保护“创建工作区”接口，后续可替换为完整 OAuth 2.1，MCP 工具契约无需改变。

## 隐私边界

- 用户不会下载 `skills/patentradar` 文件包或服务器源码。
- 规则资产、服务器校验、搜索 Key 和 PDF 逻辑留在服务器。
- 为使用用户本地 ChatGPT 推理，Codex 必须接收当前模块规则和输入材料；必要的模块指令可能在用户自己的 MCP 调用记录中可见。
- 可选的搜索 Key 会到达 PatentRadar 服务器，以便服务器代用户调用搜索 API；它不会进入模型上下文或 MCP 结果。
- 输出是公开资料线索分析，不构成法律意见。
