> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意：** 这是原始英文文档的自动翻译版本。
> 如有任何差异，以[英文版](../../README.md)为准。

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

将 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 连接到 Discord 和 GitHub。一个将 Claude Code CLI 与 Discord 桥接的框架，用于**交互式聊天、CI/CD 自动化和 GitHub 工作流集成**。

Claude Code 在终端中表现出色 - 但它能做的远不止这些。这个桥接器让你可以**在 GitHub 开发工作流中使用 Claude Code**：自动同步文档、审查和合并 PR、通过 GitHub Actions 触发任何 Claude Code 任务。所有这一切都通过 Discord 作为通用粘合剂来实现。

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免责声明：** 本项目与 Anthropic 无关，未获得 Anthropic 的认可或官方关联。"Claude"和"Claude Code"是 Anthropic, PBC 的商标。这是一个与 Claude Code CLI 交互的独立开源工具。

> **完全由 Claude Code 构建。** 本项目由 Anthropic 的 AI 编程代理 Claude Code 自行设计、实现、测试和编写文档。人类作者没有阅读过源代码。详见[本项目的构建方式](#本项目的构建方式)。

## 两种使用方式

### 1. 交互式聊天（移动端 / 桌面端）

通过手机或任何有 Discord 的设备使用 Claude Code。每个对话成为一个具有完整会话持久性的线程。

```
你 (Discord)  →  Bridge  →  Claude Code CLI
    ↑                              ↓
    ←──── stream-json 输出 ───────←
```

### 2. CI/CD 自动化（GitHub → Discord → Claude Code → GitHub）

通过 Discord webhook 从 GitHub Actions 触发 Claude Code 任务。Claude Code 自主运行 - 读取代码、更新文档、创建 PR 并启用自动合并。

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
- **流式文本** — Claude 工作时中间文本实时显示
- **工具结果显示** — 工具使用结果以 embed 形式实时显示
- **扩展思考** — Claude 的推理以剧透标签 embed 显示（点击展开）
- **会话持久化** — 通过 `--resume` 跨消息继续对话
- **技能执行** — 通过斜杠命令和自动补全执行 Claude Code 技能（`/skill goodmorning`）
- **并发会话** — 并行运行多个会话（可配置上限）

### CI/CD 自动化
- **Webhook 触发** — 从 GitHub Actions 或任何 CI/CD 系统触发 Claude Code 任务
- **自动升级** — 上游包发布时自动更新 Bot
- **REST API** — 从外部工具向 Discord 推送通知（可选，需要 aiohttp）

### 安全性
- **无 Shell 注入** — 仅使用 `asyncio.create_subprocess_exec`，从不使用 `shell=True`
- **会话 ID 验证** — 传递给 `--resume` 前使用严格正则验证
- **标志注入防护** — 所有提示前使用 `--` 分隔符
- **密钥隔离** — Bot 令牌和密钥从子进程环境中移除
- **用户授权** — `allowed_user_ids` 限制可调用 Claude 的用户

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
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

# 初始化
await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

# 添加到现有 Bot
await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```

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

## 测试

```bash
uv run pytest tests/ -v --cov=claude_discord
```

131 个测试覆盖解析器、分块器、仓库、运行器、流式传输、webhook 触发、自动升级和 REST API。

## 本项目的构建方式

**整个代码库由 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic 的 AI 编程代理编写。人类作者（[@ebibibi](https://github.com/ebibibi)）以自然语言提供需求和方向，但没有手动阅读或编辑源代码。

这意味着：

- **所有代码由 AI 生成** — 架构、实现、测试、文档
- **人类作者无法保证代码级别的正确性** — 如需确认请查看源代码
- **欢迎 Bug 报告和 PR** — Claude Code 可能也会被用来处理它们
- **这是 AI 编写的开源软件的真实案例** — 用作 Claude Code 能力的参考

本项目始于 2026-02-18，通过与 Claude Code 的迭代对话持续演进。

## 实际案例

**[EbiBot](https://github.com/ebibibi/discord-bot)** — 使用 claude-code-discord-bridge 作为包依赖的个人 Discord Bot。包括自动文档同步（英文 + 日文）、推送通知、Todoist 看门狗和 GitHub Actions CI/CD 集成。

## 许可证

MIT
