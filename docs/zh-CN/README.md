> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意：** 这是英文原版文档的自动翻译版本。
> 如有差异，以[英文版](../../README.md)为准。

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

将 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 连接到 Discord 和 GitHub。这是一个将 Claude Code CLI 与 Discord 桥接的框架，用于**交互式聊天、CI/CD 自动化和 GitHub 工作流集成**。

Claude Code 在终端中已经很强大，但它能做的远不止于此。通过这个桥接，你可以**在 GitHub 开发工作流中使用 Claude Code**：自动同步文档、审查和合并 PR、运行由 GitHub Actions 触发的任何 Claude Code 任务。Discord 作为通用粘合剂贯穿其中。

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免责声明：** 本项目与 Anthropic 无关，未经 Anthropic 背书或官方关联。"Claude"和"Claude Code"是 Anthropic, PBC 的商标。这是一个独立的开源工具，与 Claude Code CLI 交互。

> **完全由 Claude Code 构建。** 本项目由 Anthropic 的 AI 编码代理 Claude Code 本身设计、实现、测试和记录文档。人类作者未阅读源代码。详情请参阅[本项目的构建方式](#本项目的构建方式)。

## 两种使用方式

### 1. 交互式聊天（移动端 / 桌面端）

通过手机或任何有 Discord 的设备使用 Claude Code。每次对话都会成为一个具有完整会话持久化的 Discord 线程。

```
你 (Discord)  →  Bridge  →  Claude Code CLI
    ↑                              ↓
    ←──── stream-json 输出 ────────←
```

### 2. CI/CD 自动化（GitHub → Discord → Claude Code → GitHub）

通过 Discord webhook 从 GitHub Actions 触发 Claude Code 任务。Claude Code 自主运行——读取代码、更新文档、创建 PR 并启用自动合并。

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (自动合并)  ←  git push  ←  Claude Code  ←────┘
```

**实际案例：** 每次推送到 main，Claude Code 自动分析变更、更新英文和日文文档、创建双语摘要的 PR 并启用自动合并。无需人工干预。

## 功能

### 交互式聊天
- **Thread = Session** — 每个任务有自己的 Discord 线程，与 Claude Code 会话 1:1 映射
- **实时状态** — 表情符号反应显示 Claude 的状态（🧠 思考中、🛠️ 读取文件、💻 编辑中、🌐 网页搜索）
- **流式文本** — Claude 工作时中间文本实时显示，而非只在结束时显示
- **工具结果显示** — 工具使用结果以 embed 形式实时显示
- **实时工具计时** — 长时间运行的命令（如认证流程、构建）每 10 秒更新已用时间，让你随时知道 Claude 仍在工作
- **扩展思考** — Claude 的推理以剧透标签 embed 显示（点击展开）
- **会话持久化** — 通过 `--resume` 跨消息继续对话
- **技能执行** — 通过 `/skill` 斜杠命令执行 Claude Code 技能，支持自动补全、可选参数和线程内恢复
- **并发会话** — 并行运行多个会话（可配置上限）
- **停止而不清除** — `/stop` 暂停运行中的会话，同时保留以便后续恢复
- **附件支持** — 文本类型文件附件自动附加到提示（最多 5 个文件，每个 50 KB）
- **超时通知** — 会话超时时显示包含已用秒数和操作指南的专用 embed
- **交互式问题** — 当 Claude 调用 `AskUserQuestion` 时，Bot 渲染 Discord 按钮或 Select Menu，并用你的回答恢复会话
- **会话状态仪表盘** — 主频道中的 live 固定 embed 显示哪些线程正在处理 vs. 等待输入；当 Claude 需要回复时 @mention 所有者
- **多会话协调** — 设置 `COORDINATION_CHANNEL_ID` 后，每个会话将开始/结束事件广播到共享频道，让并发会话互相感知

### 定时任务（SchedulerCog）
- **定期 Claude Code 任务** — 通过 Discord 聊天或 REST API 注册任务；按可配置的间隔运行
- **SQLite 支持** — 任务在重启后持久保留；通过 `/api/tasks` 端点管理
- **零代码调度** — Claude Code 可在会话中通过 Bash 工具自行注册新任务；无需重启 Bot 或更改代码
- **单一主循环** — 一个 30 秒的 `discord.ext.tasks` 循环调度所有任务，保持低开销

### CI/CD 自动化
- **Webhook 触发** — 从 GitHub Actions 或任何 CI/CD 系统触发 Claude Code 任务
- **自动升级** — 上游包发布时自动更新 Bot
- **REST API** — 从外部工具推送通知并管理定时任务（可选，需要 aiohttp）

### 安全性
- **无 Shell 注入** — 仅使用 `asyncio.create_subprocess_exec`，从不使用 `shell=True`
- **会话 ID 验证** — 传递给 `--resume` 前使用严格正则验证
- **标志注入防护** — 所有提示前使用 `--` 分隔符
- **密钥隔离** — Bot 令牌和密钥从子进程环境中移除
- **用户授权** — `allowed_user_ids` 限制可调用 Claude 的用户

## 技能

通过 `/skill` 斜杠命令直接从 Discord 运行 [Claude Code 技能](https://docs.anthropic.com/en/docs/claude-code)。

```
/skill name:goodmorning                      → 运行 /goodmorning
/skill name:todoist args:filter "today"      → 运行 /todoist filter "today"
/skills                                      → 列出所有可用技能
```

**功能：**
- **自动补全** — 输入以过滤；名称和描述均可搜索
- **参数** — 通过 `args` 参数传递额外参数
- **线程内恢复** — 在已有 Claude 线程中使用 `/skill` 可在当前会话中运行技能，而非创建新线程
- **热重载** — 添加到 `~/.claude/skills/` 的新技能自动生效（60 秒刷新间隔，无需重启）

## 快速开始

### 前置条件

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 已安装并认证
- 启用了 Message Content intent 的 Discord Bot 令牌
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 独立运行

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# 使用你的 Bot 令牌和频道 ID 编辑 .env

uv run python -m claude_discord.main
```

### 作为包安装

如果你已有运行中的 discord.py Bot（Discord 每个令牌只允许一个 Gateway 连接）：

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeRunner, setup_bridge

runner = ClaudeRunner(command="claude", model="sonnet")

# 一次调用注册所有 Cog — 新功能自动包含
await setup_bridge(
    bot,
    runner,
    session_db_path="data/sessions.db",
    claude_channel_id=YOUR_CHANNEL_ID,
    allowed_user_ids={YOUR_USER_ID},
)
```

`setup_bridge()` 自动接入 `ClaudeChatCog`、`SkillCommandCog`、`SessionManageCog` 和 `SchedulerCog`。向 ccdb 添加新 Cog 时会自动包含——无需更改消费者代码。

<details>
<summary>手动接入（高级用法）</summary>

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```
</details>

更新到最新版本：

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord Bot 令牌 | （必填） |
| `DISCORD_CHANNEL_ID` | Claude 聊天频道 ID | （必填） |
| `CLAUDE_COMMAND` | Claude Code CLI 路径 | `claude` |
| `CLAUDE_MODEL` | 使用的模型 | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI 权限模式 | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Claude 的工作目录 | 当前目录 |
| `MAX_CONCURRENT_SESSIONS` | 最大并发会话数 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 会话非活动超时 | `300` |
| `DISCORD_OWNER_ID` | Claude 需要输入时 @mention 的 Discord 用户 ID | （可选） |
| `COORDINATION_CHANNEL_ID` | 多会话协调广播的频道 ID | （可选） |

## Discord Bot 设置

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建新应用
2. 创建 Bot 并复制令牌
3. 在 Privileged Gateway Intents 中启用 **Message Content Intent**
4. 使用以下权限邀请 Bot 到你的服务器：
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages（用于清理反应）
   - Read Message History

## GitHub + Claude Code 自动化

Webhook 触发系统让你能构建完全自主的 CI/CD 工作流，其中 Claude Code 作为智能代理运行——不只是执行脚本，而是理解代码变更并做出决策。

### 示例：自动文档同步

每次推送到 main，Claude Code：
1. 拉取最新变更并分析 diff
2. 如果源代码变更，更新英文文档
3. 翻译到日文（或任何目标语言）
4. 创建双语摘要的 PR
5. 启用自动合并——CI 通过后 PR 自动合并

**GitHub Actions 工作流：**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    # 跳过 docs-sync 自身的提交（防止无限循环）
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

**Bot 配置：**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="分析变更，更新文档，创建双语摘要的 PR，启用自动合并。",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
    "🚀 deploy": WebhookTrigger(
        prompt="部署到预发布环境。",
        timeout=300,
    ),
}

await bot.add_cog(WebhookTriggerCog(
    bot=bot,
    runner=runner,
    triggers=triggers,
    channel_ids={YOUR_CHANNEL_ID},
))
```

**安全性：** 仅处理 webhook 消息。可选 `allowed_webhook_ids` 实现更严格控制。提示在服务器端定义——webhook 只选择触发哪个触发器。

### 示例：自动批准所有者 PR

CI 通过后自动批准并自动合并自己的 PR：

```yaml
# .github/workflows/auto-approve.yml
name: Auto Approve Owner PRs
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  auto-approve:
    if: github.event.pull_request.user.login == 'your-username'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: write
    steps:
      - env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
        run: |
          gh pr review "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --approve
          gh pr merge "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --auto --squash
```

## 定时任务

`SchedulerCog` 运行存储在 SQLite 中的定期 Claude Code 任务。任务在运行时通过 REST API 注册——无需更改代码或重启 Bot。

### 通过 REST API 注册任务

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{
    "name": "daily-standup",
    "prompt": "检查开放的 GitHub issue 并向 Discord 发布简要摘要。",
    "interval_seconds": 86400,
    "channel_id": 123456789
  }'
```

### Claude 在会话中自行注册任务

Claude Code 可以在会话中使用 Bash 工具注册自己的定期任务——无需人工接入：

```
# 在 Claude Code 会话内，Claude 运行：
curl -X POST $CCDB_API_URL/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"name": "health-check", "prompt": "运行测试套件并报告结果。", "interval_seconds": 3600}'
```

当 `ClaudeRunner` 设置了 `api_port` 时，`CCDB_API_URL` 会自动注入到 Claude 的子进程环境中。

## 自动升级

上游包发布时自动升级 Bot。

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

**流程：** 上游推送 → CI webhook → `🔄 bot-upgrade` → `uv lock --upgrade-package` → `uv sync` → 服务重启。

### 优雅排空（DrainAware）

重启前，AutoUpgradeCog 等待所有活跃会话完成。任何实现了 `active_count` 属性（满足 `DrainAware` 协议）的 Cog 都会被自动发现——无需手动传入 `drain_check` lambda。

内置 DrainAware Cog：`ClaudeChatCog`、`WebhookTriggerCog`。

要让你自己的 Cog 支持排空，只需添加 `active_count` 属性：

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

你仍可传入显式的 `drain_check` 可调用对象来覆盖自动发现。

### 重启批准

对于自更新场景（如从 Bot 自身的 Discord 会话中更新），启用 `restart_approval` 可防止自动重启：

```python
config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
)
```

启用 `restart_approval=True` 后，升级包后 Bot 会发布一条请求批准的消息。用 ✅ 反应触发重启。Bot 会定期发送提醒直到批准。

## REST API

用于从外部工具向 Discord 推送通知的可选 REST API。需要 aiohttp：

```bash
uv add "claude-code-discord-bridge[api]"
```

```python
from claude_discord import NotificationRepository
from claude_discord.ext.api_server import ApiServer

repo = NotificationRepository("data/notifications.db")
await repo.init_db()

api = ApiServer(
    repo=repo,
    bot=bot,
    default_channel_id=YOUR_CHANNEL_ID,
    host="127.0.0.1",
    port=8080,
    api_secret="your-secret-token",  # 可选 Bearer 认证
)
await api.start()
```

### 端点

**通知**

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/notify` | 发送即时通知 |
| POST | `/api/schedule` | 安排稍后发送通知 |
| GET | `/api/scheduled` | 列出待处理通知 |
| DELETE | `/api/scheduled/{id}` | 取消定时通知 |

**定时任务**（需要 `SchedulerCog`）

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/tasks` | 注册新的定期 Claude Code 任务 |
| GET | `/api/tasks` | 列出所有已注册任务 |
| DELETE | `/api/tasks/{id}` | 删除定时任务 |
| PATCH | `/api/tasks/{id}` | 更新任务（启用/禁用、提示、间隔） |

### 使用示例

```bash
# 健康检查
curl http://localhost:8080/api/health

# 发送通知
curl -X POST http://localhost:8080/api/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"message": "构建成功！", "title": "CI/CD"}'

# 安排通知
curl -X POST http://localhost:8080/api/schedule \
  -H "Content-Type: application/json" \
  -d '{"message": "是时候审查 PR 了", "scheduled_at": "2026-01-01T09:00:00"}'
```

## 架构

```
claude_discord/
  main.py                  # 独立入口点
  bot.py                   # Discord Bot 类
  setup.py                 # setup_bridge() — 所有 Cog 的一键工厂
  cogs/
    claude_chat.py         # 交互式聊天（线程创建、消息处理）
    skill_command.py       # /skill 斜杠命令（自动补全）
    webhook_trigger.py     # Webhook → Claude Code 任务执行（CI/CD）
    auto_upgrade.py        # Webhook → 包升级 + 重启
    scheduler.py           # 定期 Claude Code 任务（SQLite 支持，30 秒主循环）
    _run_helper.py         # 共享 Claude CLI 执行逻辑
  claude/
    runner.py              # Claude CLI 子进程管理器
    parser.py              # stream-json 事件解析器
    types.py               # SDK 消息类型定义
  database/
    models.py              # SQLite 模式
    repository.py          # 会话 CRUD 操作
    ask_repo.py            # 待处理 AskUserQuestion CRUD（重启恢复）
    notification_repo.py   # 定时通知 CRUD
    task_repo.py           # 定时任务 CRUD（SchedulerCog）
  coordination/
    service.py             # CoordinationService — 向共享频道发布会话生命周期事件
  discord_ui/
    status.py              # 表情符号反应状态管理器（防抖）
    chunker.py             # 支持代码围栏和表格的消息分割
    embeds.py              # Discord embed 构建器
    ask_view.py            # AskUserQuestion 的 Discord 按钮/Select Menu
    ask_bus.py             # 持久化 AskView 按钮的总线路由（重启后仍存活）
    thread_dashboard.py    # 显示每个线程会话状态的 live 固定 embed
  ext/
    api_server.py          # REST API 服务器（可选，需要 aiohttp）
                           # 包含 SchedulerCog 的 /api/tasks 端点
  utils/
    logger.py              # 日志配置
```

### 设计理念

- **CLI 生成，而非 API** — 调用 `claude -p --output-format stream-json`，免费获得完整的 Claude Code 功能（CLAUDE.md、技能、工具、记忆）
- **Discord 作为粘合剂** — Discord 提供 UI、线程、通知和 webhook 基础设施
- **框架，而非应用** — 作为包安装，向现有 Bot 添加 Cog，通过代码配置
- **简单即安全** — 约 2500 行可审计的 Python，无 Shell 执行，无任意代码路径

## 测试

```bash
uv run pytest tests/ -v --cov=claude_discord
```

473 个测试覆盖解析器、分块器、仓库、运行器、流式传输、webhook 触发器、自动升级、REST API、AskUserQuestion UI、线程状态仪表盘、SchedulerCog 和任务仓库。

## 本项目的构建方式

**整个代码库由 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**——Anthropic 的 AI 编码代理——编写。人类作者（[@ebibibi](https://github.com/ebibibi)）用自然语言提供了需求和方向，但未手动阅读或编辑源代码。

这意味着：

- **所有代码均由 AI 生成** — 架构、实现、测试、文档
- **人类作者无法在代码层面保证正确性** — 如需确保请审查源代码
- **欢迎 Bug 报告和 PR** — Claude Code 可能也会被用来处理它们
- **这是 AI 创作开源软件的实际案例** — 可作为 Claude Code 能构建什么的参考

本项目于 2026-02-18 启动，并通过与 Claude Code 的迭代对话持续演进。

## 实际案例

**[EbiBot](https://github.com/ebibibi/discord-bot)** — 一个将 claude-code-discord-bridge 作为包依赖的个人 Discord Bot。包含自动文档同步（英文 + 日文）、推送通知、Todoist 看门狗和 GitHub Actions 的 CI/CD 集成。可作为在此框架上构建自己 Bot 的参考。

## 灵感来源

- [OpenClaw](https://github.com/openclaw/openclaw) — 表情符号状态反应、消息防抖、围栏感知分块
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI 生成 + stream-json 方法
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — 权限控制模式
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — 每对话一个线程模型

## 许可证

MIT
