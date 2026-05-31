> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意：** 这是原始英文文档的自动翻译版本。
> 如有任何差异，以[英文版](../../README.md)为准。

# Claude & Codex Discord Bridge

*包名：`claude-code-discord-bridge`（短横线命名）*

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**在手机上使用 Claude Code _或_ OpenAI Codex。多线程并行。全速开发。**

通过智能手机的 Discord 应用打开 Claude Code 或 OpenAI Codex，启动多个线程，并行运行开发会话——无需触碰键盘。每个 Discord 线程都成为完全隔离的 AI 会话。在一个线程中开发功能，在另一个线程中审查 PR，在第三个线程中运行后台任务——同时进行，甚至可以每个线程使用不同的后端。桥接器处理所有协调，让会话永不冲突。

**使用现有订阅，无需配置 API 密钥。** ccdb 基于官方 CLI 运行——Claude Code（包含在 [Claude Pro/Max 订阅](https://claude.ai/pricing)中）和 OpenAI Codex（包含在 [ChatGPT Plus/Pro/Business](https://chatgpt.com)中）。通过 `/backend` 切换后端或按线程设置——以可预测的费用通过 Discord 使用两种 AI。

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免责声明：** 本项目与 Anthropic 或 OpenAI 没有任何关联、认可或官方关系。"Claude"和"Claude Code"是 Anthropic, PBC 的商标；"OpenAI"、"Codex"和"ChatGPT"是 OpenAI 的商标。这是一个与 Claude Code CLI 和 OpenAI Codex CLI 交互的独立开源工具。

> **完全由 Claude Code 构建。** 整个代码库——架构、实现、测试、文档——均由 Claude Code 本身编写。人类作者提供需求和方向。详见[本项目的构建方式](#本项目的构建方式)。

---

## 核心理念：无冲突并行会话

当您在多个 Discord 线程中向 Claude Code 发送任务时，桥接器会自动完成四件事：

1. **并发指令注入** — 每个会话的系统提示都包含强制指令：创建 git worktree，只在其中工作，不直接修改主工作目录。

2. **活跃会话注册表** — 每个运行中的会话都知道其他会话的存在。如果两个会话将要操作同一个仓库，它们可以协调而非冲突。

3. **AI 休息室（AI Lounge）** — 注入每个会话提示的"休息室"频道。开始前，每个会话读取最近的休息室消息以了解其他会话的动态。在进行破坏性操作（强制推送、重启 Bot、删除数据库）前，会话会先检查休息室。

```
线程 A（功能开发）  ──→  Claude Code (worktree-A)  ─┐
线程 B（PR 审查）   ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
线程 C（文档）      ──→  Claude Code (worktree-C)  ─┘    "A: auth 重构进行中"
                                                         "B: PR #42 审查完成"
                                                         "C: 更新 README"
```

无竞争条件。无工作丢失。无合并意外。

---

## 能做什么

### 交互式聊天（移动端 / 桌面端）

在任何 Discord 运行的地方使用 Claude Code——手机、平板或桌面。每条消息创建或继续一个线程，与持久化的 Claude Code 会话一一对应。

### 并行开发

同时打开多个线程。每个线程都是独立的 Claude Code 会话，拥有自己的上下文、工作目录和 git worktree。常见用法：

- **功能开发 + 同步审查**：在一个线程开发功能，同时 Claude 在另一个线程审查 PR。
- **多人协作**：不同团队成员各有自己的线程；会话通过 AI Lounge 互相了解动态。
- **安全实验**：在线程 A 尝试某种方案，同时线程 B 保持稳定代码。

### 定时任务（SchedulerCog）

无需修改代码、无需重新部署，通过 Discord 对话或 REST API 注册定期 Claude Code 任务。任务存储在 SQLite 中，按可配置的计划运行。Claude 可在会话中通过 `POST /api/tasks` 自我注册任务。

```
/skill name:goodmorning         → 立即执行
Claude 调用 POST /api/tasks    → 注册定期任务
SchedulerCog（30 秒主循环）     → 自动触发到期任务
```

### CI/CD 自动化

通过 Discord webhook 从 GitHub Actions 触发 Claude Code 任务。Claude 自主运行——读取代码、更新文档、创建 PR、启用自动合并。

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**实际案例：** 每次推送到 `main`，Claude 分析差异，更新英文 + 日文文档，创建双语 PR，并启用自动合并。零人工干预。

### 会话同步

已在直接使用 Claude Code CLI？通过 `/sync-sessions` 将现有终端会话同步到 Discord 线程。回填最近的对话消息，让您无需丢失上下文即可从手机继续 CLI 会话。

### AI 休息室（AI Lounge）

所有并发会话互相通报、协调的共享"休息室"频道。每个 Claude 会话通过 `--append-system-prompt` 自动接收休息室上下文——作为临时系统上下文而非对话历史注入，防止跨回合累积（避免长时间会话出现"Prompt is too long"错误）。

```bash
# 会话在开始前发布意图：
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "在 feature/oauth 上开始 auth 重构 — worktree-A", "label": "功能开发"}'

# 读取最近的休息室消息（也自动注入每个会话）：
curl "$CCDB_API_URL/api/lounge"
```

### 程序化会话创建

从脚本、GitHub Actions 或其他 Claude 会话创建新的 Claude Code 会话，无需 Discord 消息交互。

```bash
# 从另一个 Claude 会话或 CI 脚本：
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "对仓库运行安全扫描", "thread_name": "Security Scan"}'
# 线程创建后立即返回；Claude 在后台运行
```

**延迟启动 (`auto_start=false`)** — 创建线程并发布种子消息，但不立即启动 Claude。只有当用户回复时 Claude 才启动，并自动接收种子消息作为上下文。

### 启动恢复

如果 Bot 在会话进行中重启，被中断的 Claude 会话在 Bot 重新上线时会自动恢复。

---

## 功能列表

### 交互式聊天

#### 🔗 会话基础
- **纯聊天模式** — `CHAT_ONLY_CHANNEL_IDS` 只显示 Claude 的文本回复；工具 embed、思维块、会话 embed 和待办列表隐藏。适合公开频道。
- **线程 = 会话** — Discord 线程与 Claude Code 会话 1:1 映射
- **目标跟踪** — `/goal <条件>` 设置完成条件；Claude 持续工作直到满足条件
- **会话持久化** — 通过 `--resume` 跨消息继续对话
- **并发会话** — 可配置限制的多并行会话
- **停止但不清除** — `/stop` 暂停会话同时保留以供恢复
- **会话中断** — 向活跃线程发送新消息时自动发送 SIGINT 并以新指令重新开始
- **自动重命名线程** — `THREAD_AUTO_RENAME=true` 时自动生成描述性标题

#### 📡 实时反馈
- **实时状态** — 表情反应：🧠 思考中，🛠️ 读取文件，💻 编辑中，🌐 网络搜索
- **流式文本** — Claude 工作时中间文本实时显示
- **工具结果 embed** — 实时工具调用结果，含已用时间计时器
- **扩展思维** — 推理以剧透标签 embed 显示（点击展开）
- **线程仪表板** — 实时固定 embed 显示活跃/等待线程状态

#### 🤝 人机协作
- **交互式问题** — `AskUserQuestion` 渲染为 Discord 按钮或下拉菜单
- **计划模式** — `ExitPlanMode` 触发带批准/取消按钮的 Discord embed；5 分钟超时
- **工具权限请求** — 允许/拒绝按钮；2 分钟无响应自动拒绝
- **MCP Elicitation** — MCP 服务器通过 Discord 请求用户输入；5 分钟超时
- **TodoWrite 实时进度** — 单个 Discord embed 原地更新；显示 ✅ 已完成、🔄 进行中、⬜ 待处理

#### 📊 可观测性
- **Token 用量** — 会话完成 embed 中显示缓存命中率和 token 数量
- **上下文用量** — 显示上下文窗口百分比；超过 83.5% 时 ⚠️ 警告
- **压缩检测** — 上下文压缩时在线程内通知
- **长时间停滞通知** — 无活动超过阈值时发送通知（标准模型 30s，Opus 120s）
- **超时通知** — 显示已用时间和恢复指南
- **StatusLine 显示** — 每次会话后显示 Claude 配置的状态行
- **线程收件箱** — `THREAD_INBOX_ENABLED=true` 时显示 📬 收件箱

#### 🔌 输入与技能
- **附件支持** — 文本文件自动追加（最多 5 个文件，每个 200 KB）；图片通过 CDN URL 发送（最多 4 × 5 MB）
- **按需文件发送** — Claude 写入 `.ccdb-attachments` 路径，会话完成时自动发送
- **技能执行** — `/skill` 命令，带自动补全；已安装插件的技能自动发现
- **热重载** — `~/.claude/skills/` 中的新技能自动检测（60 秒刷新）

### 并发与协调
- **Worktree 指令自动注入** — 每个会话被提示使用 `git worktree`
- **自动 worktree 清理** — 会话结束和 Bot 启动时自动清理；脏 worktree 永不自动删除
- **活跃会话注册表** — 内存注册表；每个会话看到其他会话的动态
- **AI Lounge** — 共享"休息室"；上下文通过 `--append-system-prompt` 注入（不在历史中累积）
- **协调频道** — `COORDINATION_CHANNEL_ID` 用作 AI Lounge 的默认回退

### 定时任务
- **SchedulerCog** — SQLite 支持，30 秒主循环
- **自我注册** — Claude 通过 `POST /api/tasks` 注册任务
- **无需修改代码** — 运行时添加、删除或修改任务
- **启用/禁用** — `PATCH /api/tasks/{id}` 暂停任务

### CI/CD 自动化
- **Webhook 触发** — 从 GitHub Actions 或任何 CI/CD 系统触发任务
- **自动升级** — 上游包发布时自动更新 Bot
- **DrainAware 重启** — 重启前等待活跃会话完成
- **自动恢复标记** — 任何关闭时活跃会话自动标记恢复
- **手动升级触发** — `/upgrade` 斜杠命令（可选启用）

### 会话管理
- **内置帮助** — `/help` 显示所有斜杠命令（临时消息）
- **会话同步** — `/sync-sessions` 将 CLI 会话导入为 Discord 线程
- **会话列表** — `/sessions`，按来源和时间窗口过滤
- **会话恢复** — `/resume` 在新线程中恢复选定会话
- **会话清除** — `/clear` 重置当前线程的会话
- **程序化生成** — `POST /api/spawn` 从脚本创建线程 + 会话
- **Worktree 管理** — `/worktree-list` 和 `/worktree-cleanup`
- **运行时模型切换** — `/model-show` 和 `/model-set`，无需重启
- **对话回退** — `/rewind` 截断到选定回合
- **对话分叉** — `/fork` 创建独立会话副本

### 安全性
- **无 shell 注入** — 仅使用 `asyncio.create_subprocess_exec`
- **会话 ID 验证** — 严格正则验证
- **标志注入防护** — `--` 分隔符
- **密钥隔离** — Bot token 从子进程环境中移除
- **用户授权** — `allowed_user_ids` 限制访问
- **日志注入防护** — 用户输入在写入日志前净化

---

## 快速开始 — 5 分钟在 Discord 中运行 Claude

**前提条件：** Python 3.10+，已安装并认证的 [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)。

**平台支持：** 主要在 **Linux** 上开发和测试。macOS 和 Windows 受支持且通过 CI，但实际测试较少。

### 第一步 — 创建 Discord Bot（一次性，约 2 分钟）

1. 前往 [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. 导航到 **Bot** → 在 Privileged Gateway Intents 下启用 **Message Content Intent**
3. 复制 Bot **Token**
4. 前往 **OAuth2 → URL Generator**：作用域 `bot` + `applications.commands`，权限：Send Messages, Create Public Threads, Send Messages in Threads, Add Reactions, Manage Messages, Read Message History
5. 打开生成的 URL → 将 Bot 邀请到您的服务器

### 第二步 — 运行设置向导

无需克隆或编辑 `.env`——向导为您完成一切：

```bash
# 使用 uvx（无需安装）：
uvx --from "git+https://github.com/ebibibi/claude-code-discord-bridge.git" ccdb setup

# 或克隆后：
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv run ccdb setup
```

### 启动 / 停止

```bash
ccdb start    # 启动 Bot（读取当前目录的 .env）
ccdb start --env /path/to/.env   # 自定义 .env 位置
```

在配置的频道发送消息——Claude 将在新线程中回复。

### 作为 systemd 服务运行（生产环境）

```bash
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service
journalctl -u mybot.service -f
```

### 自定义 Cog（无需 fork 即可扩展）

将 Python 文件放入目录即可添加自定义功能：

```bash
ccdb start --cogs-dir ./my-cogs/
# 或：CUSTOM_COGS_DIR=./my-cogs ccdb start
```

每个 `.py` 文件必须暴露 `async def setup(bot, runner, components)`。

详见 [`examples/ebibot/`](examples/ebibot/)，包含提醒、Todoist 看门狗、自动升级和文档同步的完整实例。

---

### 最小化 Bot（作为包安装）

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

创建 `bot.py`：

```python
import asyncio
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from claude_discord import ClaudeRunner, setup_bridge

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
runner = ClaudeRunner(
    command="claude",
    model="sonnet",
    working_dir="/path/to/your/project",
)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
        allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
    )

asyncio.run(bot.start(os.environ["DISCORD_BOT_TOKEN"]))
```

`setup_bridge()` 自动配置所有 Cog。更新到最新版本：

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord Bot token | （必填） |
| `DISCORD_CHANNEL_ID` | Claude 聊天频道 ID | （必填） |
| `CCDB_BACKEND` | 使用的 CLI 后端：`claude` 或 `codex` | `claude` |
| `CCDB_COMMAND` | CLI 二进制文件路径或名称（覆盖 `CLAUDE_COMMAND`） | _（自动）_ |
| `CCDB_MODEL` | 使用的模型（覆盖 `CLAUDE_MODEL`） | `sonnet` |
| `CCDB_PERMISSION_MODE` | CLI 权限模式（覆盖 `CLAUDE_PERMISSION_MODE`） | `acceptEdits` |
| `CCDB_DANGEROUSLY_SKIP_PERMISSIONS` | 跳过所有权限检查 | `false` |
| `CCDB_WORKING_DIR` | CLI 工作目录 | 当前目录 |
| `CCDB_ALLOWED_TOOLS` | 允许工具的逗号分隔列表 | （可选） |
| `CCDB_CHANNEL_IDS` | 多频道设置的额外频道 ID | （可选） |
| `CLAUDE_COMMAND` | Claude CLI 路径（旧名称——推荐 `CCDB_COMMAND`） | `claude` |
| `CLAUDE_MODEL` | 模型（旧名称——推荐 `CCDB_MODEL`） | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | 权限模式（旧名称——推荐 `CCDB_PERMISSION_MODE`） | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | 跳过权限检查（旧名称） | `false` |
| `CLAUDE_WORKING_DIR` | 工作目录（旧名称） | 当前目录 |
| `MAX_CONCURRENT_SESSIONS` | 最大并行会话数 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 会话不活跃超时 | `300` |
| `DISCORD_OWNER_ID` | 需要输入时 @提及 的用户 ID | （可选） |
| `COORDINATION_CHANNEL_ID` | AI Lounge 频道的默认回退 | （可选） |
| `MENTION_ONLY_CHANNEL_IDS` | 仅 @提及 时响应的频道（逗号分隔） | （可选） |
| `INLINE_REPLY_CHANNEL_IDS` | 内联回复频道（逗号分隔） | （可选） |
| `CHAT_ONLY_CHANNEL_IDS` | 纯聊天模式频道（逗号分隔） | （可选） |
| `WORKTREE_BASE_DIR` | 扫描会话 worktree 的基础目录 | （可选） |
| `CLI_SESSIONS_PATH` | CLI 会话发现路径（`~/.claude/projects`） | （可选） |
| `CUSTOM_COGS_DIR` | 自定义 Cog 目录 | （可选） |
| `THREAD_INBOX_ENABLED` | 启用持久线程收件箱 | `false` |
| `THREAD_AUTO_RENAME` | 使用 Claude 自动重命名线程 | `false` |
| `CCDB_CLI_ENV_FILE` | 每次 CLI 调用时合并到环境的 `KEY=VALUE` 文件 | （可选） |
| `CCDB_LOG_FILE` | 日志文件路径。设置后，将在默认 stdout 处理器旁边添加轮转文件处理器（10 MB × 5 个备份），方便监控和告警 | （可选） |
| `API_HOST` | REST API 绑定地址 | `127.0.0.1` |
| `API_PORT` | REST API 端口（设置后启用） | （可选） |

---

## GitHub + Claude Code 自动化

### 示例：自动文档同步

每次推送到 `main`，Claude Code：
1. 拉取最新更改并分析差异
2. 更新英文文档
3. 翻译为目标语言
4. 创建带双语摘要的 PR
5. 启用自动合并——CI 通过后自动合并

**GitHub Actions：**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

---

## 定时任务

无需修改代码即可在运行时注册定期 Claude Code 任务。

```bash
# Claude 在会话中调用：
curl -X POST "$CCDB_API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "检查过期依赖并在发现时开 issue", "interval_seconds": 604800}'
```

30 秒主循环自动检测到期任务并启动 Claude Code 会话。

---

## 自动升级

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
    slash_command_enabled=True,
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

重启前，`AutoUpgradeCog` 会快照活跃会话、等待其完成、标记恢复并执行重启命令。

---

## REST API

可选 REST API，用于通知和任务管理。需要 aiohttp：

```bash
uv add "claude-code-discord-bridge[api]"
```

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/notify` | 发送即时通知 |
| POST | `/api/schedule` | 安排通知 |
| GET | `/api/scheduled` | 列出待处理通知 |
| DELETE | `/api/scheduled/{id}` | 取消通知 |
| POST | `/api/tasks` | 注册定期 Claude Code 任务 |
| GET | `/api/tasks` | 列出已注册任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| PATCH | `/api/tasks/{id}` | 更新任务 |
| POST | `/api/spawn` | 创建新 Discord 线程并启动 Claude Code 会话（非阻塞） |
| POST | `/api/mark-resume` | 标记线程在下次 Bot 启动时自动恢复 |
| GET | `/api/lounge` | 读取最近的 AI Lounge 消息 |
| POST | `/api/lounge` | 向 AI Lounge 发布消息 |

---

## 架构

```
claude_code_core/          # 与后端无关的共享核心库
  backend.py               # SessionBackend 协议 + create_backend() 工厂
  codex_runner.py          # OpenAI Codex CLI 后端
  runner.py                # Claude CLI 子进程管理器
  parser.py                # stream-json 事件解析器
  types.py                 # SDK 消息类型定义
claude_discord/
  main.py                  # 独立入口
  cli.py                   # CLI 入口（ccdb setup/start）
  setup.py                 # setup_bridge()
  cogs/
    claude_chat.py         # 交互式聊天
    skill_command.py       # /skill 命令
    session_manage.py      # 会话管理
    scheduler.py           # 定期任务
    webhook_trigger.py     # CI/CD 触发器
    auto_upgrade.py        # 自动升级
  ext/
    api_server.py          # REST API（可选）
examples/
  ebibot/                  # 真实案例
```

### 设计理念

- **CLI 生成而非 API** — 获得完整 Claude Code 功能，无需 API 密钥，无按 token 计费
- **并发优先** — 多个同时会话是预期情况，而非边缘情况
- **Discord 作为胶水** — Discord 提供 UI、线程、反应、webhook 和持久通知
- **框架而非应用** — 作为包安装，向现有 Bot 添加 Cog
- **零代码可扩展性** — 无需修改源代码即可添加定时任务和 webhook 触发器
- **简单即安全** — 约 8000 行可审计的 Python；仅 subprocess exec，无 shell 扩展

---

## 测试

```bash
uv run pytest tests/ -v --cov=claude_discord
```

1365+ 个测试覆盖解析器、分块器、仓库、运行器、流式传输、webhook 触发器、自动升级、REST API、AskUserQuestion UI、线程仪表板、定时任务、会话同步、AI Lounge、启动恢复、模型切换、压缩检测、TodoWrite 进度 embed、自定义 Cog 加载器、SessionBackend 协议、CodexRunner 和后端工厂。

---

## 本项目的构建方式

**本代码库由 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**（Anthropic 的 AI 编码代理）在 [@ebibibi](https://github.com/ebibibi) 的指导下开发。人类作者定义需求、审查 PR 并批准所有更改——Claude Code 负责实现。

项目于 2026-02-18 启动，并通过与 Claude Code 的迭代对话不断演进。

---

## 实际案例

**[`examples/ebibot/`](examples/ebibot/)** — 基于此框架构建的个人 Discord Bot，展示自定义 Cog 加载器：

- **ReminderCog** — `/remind HH:MM "message"` 斜杠命令 + 30 秒发送循环
- **WatchdogCog** — Todoist 过期任务监控（30 分钟检查，每日去重，按严重程度告警）
- **AutoUpgradeCog** — 通过 GitHub webhook + systemctl restart 自我更新
- **DocsSyncCog** — 推送时自动翻译文档
- **AlertResponderCog** — 通用告警监控 Cog；监视可配置来源并向 Discord 发布带严重程度注释的通知

运行方式：`ccdb start --cogs-dir examples/ebibot/cogs/`

---

## 致谢

- [OpenClaw](https://github.com/openclaw/openclaw) — 表情状态反应、消息防抖、fence 感知分块
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI 生成 + stream-json 方法
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — 权限控制模式
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — 每线程对话模型

---

## 许可证

MIT
