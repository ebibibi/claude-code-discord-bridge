> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意：** 这是原始英文文档的自动翻译版本。
> 如有任何差异，以[英文版](../../README.md)为准。

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**通过 Discord 安全地并行运行多个 Claude Code 会话。**

每个 Discord 线程都成为一个隔离的 Claude Code 会话。按需启动任意数量的会话：在一个线程中开发功能，在另一个线程中审查 PR，在第三个线程中运行计划任务。桥接器自动处理协调，确保并发会话不会相互干扰。

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免责声明：** 本项目与 Anthropic 无关，未获得 Anthropic 的认可或官方关联。"Claude"和"Claude Code"是 Anthropic, PBC 的商标。这是一个与 Claude Code CLI 交互的独立开源工具。

> **完全由 Claude Code 构建。** 本项目的完整代码库——架构、实现、测试、文档——均由 Claude Code 自行编写。人类作者提供了需求和方向，但未手动阅读或编辑源代码。详见[本项目的构建方式](#本项目的构建方式)。

---

## 核心理念：无忧并行会话

当你在不同 Discord 线程中向 Claude Code 发送任务时，桥接器会自动完成四件事：

1. **并发通知注入** — 每个会话的系统提示中都包含强制指令：创建 git worktree，仅在其中工作，绝不直接修改主工作目录。

2. **活跃会话注册表** — 每个运行中的会话都能了解其他会话的情况。如果两个会话即将操作同一个仓库，它们可以协调而非冲突。

3. **协调频道** — 一个共享的 Discord 频道，会话在此广播启动/结束事件。Claude 和人类都可以一目了然地看到所有活跃线程的状态。

4. **AI Lounge** — 注入每个会话提示的「控え室」频道。开始工作前，每个会话会读取最近的 Lounge 消息来了解其他会话的动态。进行破坏性操作（force push、bot 重启、DB 操作等）前，会话会先确认 Lounge 内容，避免踩踏彼此的工作。

```
线程 A (功能开发)  ──→  Claude Code (worktree-A)  ─┐
线程 B (PR 审查)   ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
线程 C (文档)      ──→  Claude Code (worktree-C)  ─┘    "A: auth 重构进行中"
           ↓ 生命周期事件                                "B: PR #42 审查完成"
   #协调频道                                             "C: README 更新中"
   "A: 开始认证重构"
   "B: 审查 PR #42"
   "C: 更新 README"
```

无竞争条件。无工作丢失。无合并意外。

---

## 功能概览

### 交互式聊天（移动端 / 桌面端）

在任何运行 Discord 的设备上使用 Claude Code——手机、平板或桌面端。每条消息都会创建或继续一个线程，与持久化的 Claude Code 会话 1:1 映射。

### 并行开发

同时打开多个线程。每个都是独立的 Claude Code 会话，有自己的上下文、工作目录和 git worktree。实用模式：

- **功能 + 审查并行**：在一个线程开发功能的同时，让 Claude 在另一个线程审查 PR。
- **多人协作**：不同团队成员各有自己的线程；会话通过协调频道相互感知。
- **安全实验**：在线程 A 尝试某种方案，同时线程 B 保持在稳定代码上。

### 计划任务（SchedulerCog）

通过 Discord 对话或 REST API 注册定期 Claude Code 任务——无需修改代码，无需重新部署。任务存储在 SQLite 中，按可配置的计划运行。Claude 可在会话中通过 `POST /api/tasks` 自行注册任务。

```
/skill name:goodmorning         → 立即运行
Claude 调用 POST /api/tasks    → 注册定期任务
SchedulerCog（30 秒主循环）   → 自动触发到期任务
```

### CI/CD 自动化

通过 Discord webhook 从 GitHub Actions 触发 Claude Code 任务。Claude 自主运行——读取代码、更新文档、创建 PR、启用自动合并。

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**实际案例：** 每次推送到 `main`，Claude 自动分析差异，更新英文和日文文档，创建双语摘要的 PR，并启用自动合并。全程无需人工干预。

### 会话同步

已在直接使用 Claude Code CLI？通过 `/sync-sessions` 将现有终端会话同步到 Discord 线程。回填近期对话消息，让你无需丢失上下文即可从手机继续 CLI 会话。

### AI Lounge

所有并行会话共享的「控え室」频道——会话在此互相告知动态、读取彼此的更新，并在进行破坏性操作前先行确认。

每个 Claude 会话都会在系统提示中自动收到 Lounge 上下文：来自其他会话的最近消息，以及进行破坏性操作前必须确认的规则。

```bash
# 会话在开始前发布意图：
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "feature/oauth 上开始 auth 重构 — worktree-A", "label": "功能开发"}'

# 读取最近的 Lounge 消息（也会自动注入每个会话）：
curl "$CCDB_API_URL/api/lounge"
```

Lounge 频道同时也是人类可见的活动动态——在 Discord 中打开它，即可一眼看清所有活跃 Claude 会话当前在做什么。

### 程序化会话创建

从脚本、GitHub Actions 或其他 Claude 会话中创建新的 Claude Code 会话——无需 Discord 消息交互。

```bash
# 从另一个 Claude 会话或 CI 脚本：
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "对仓库进行安全扫描", "thread_name": "安全扫描"}'
# 立即返回线程 ID；Claude 在后台运行
```

Claude 子进程将 `DISCORD_THREAD_ID` 作为环境变量接收，因此运行中的会话可以创建子会话来并行化工作。

### 启动恢复

如果 bot 在会话中途重启，被中断的 Claude 会话会在 bot 重新上线时自动恢复。会话通过三种方式标记为待恢复：

- **自动（升级重启）** — `AutoUpgradeCog` 在包升级重启前快照所有活跃会话并自动标记。
- **自动（任意关闭）** — `ClaudeChatCog.cog_unload()` 在 bot 通过任何机制关闭时（`systemctl stop`、`bot.close()`、SIGTERM 等）标记所有运行中的会话。
- **手动** — 任何会话都可以直接调用 `POST /api/mark-resume`。

---

## 功能详情

### 交互式聊天

#### 🔗 基础会话
- **Thread = Session** — Discord 线程与 Claude Code 会话 1:1 映射
- **会话持久化** — 通过 `--resume` 跨消息继续对话
- **并发会话** — 多个并行会话，可配置上限
- **不清除内容停止** — `/stop` 停止会话同时保留以便恢复
- **会话中断** — 向活跃线程发送新消息会向正在运行的会话发送 SIGINT 并以新指令重新开始；无需手动 `/stop`

#### 📡 实时反馈
- **实时状态** — 表情反应：🧠 思考中，🛠️ 读取文件，💻 编辑中，🌐 网页搜索
- **流式文本** — Claude 工作时中间助手文本实时显示
- **工具结果显示** — 实时工具调用结果，含每 10 秒更新的耗时计数器；单行输出直接内联显示，多行输出折叠在展开按钮后
- **扩展思考** — 推理以剧透标签 embed 显示（点击展开）
- **线程面板** — 实时置顶 embed，显示各线程活跃/等待状态；需要输入时 @提及所有者

#### 🤝 人机协作
- **交互式问题** — `AskUserQuestion` 渲染为 Discord 按钮或下拉菜单；选择后会话继续；按钮在 bot 重启后仍可用
- **Plan Mode** — Claude 调用 `ExitPlanMode` 时，Discord embed 显示完整计划并附带批准/取消按钮；仅在批准后 Claude 才继续执行；5 分钟超时自动取消
- **工具权限请求** — Claude 需要执行工具权限时，Discord 显示带工具名称和输入的允许/拒绝按钮；2 分钟后自动拒绝
- **MCP Elicitation** — MCP 服务器可通过 Discord 请求用户输入（表单模式：JSON schema 最多 5 个 Modal 字段；URL 模式：URL 按钮 + 完成确认）；5 分钟超时
- **TodoWrite 实时进度** — Claude 调用 `TodoWrite` 时，发布单个 Discord embed 并在每次更新时就地编辑；显示 ✅ 已完成、🔄 进行中（带 `activeForm` 标签）、⬜ 待处理

#### 📊 可观测性
- **Token 使用量** — 会话完成 embed 显示缓存命中率和 token 计数
- **上下文使用量** — 会话完成 embed 中显示上下文窗口百分比（输入 + 缓存 token，不含输出）及自动压缩前剩余容量；超过 83.5% 时显示 ⚠️ 警告
- **压缩检测** — 发生上下文压缩时在线程中通知（触发类型 + 压缩前 token 数）
- **长期停滞通知** — 30 秒无活动（扩展思考或上下文压缩）后发送线程消息；Claude 恢复时自动重置
- **超时通知** — 超时时显示含耗时和恢复指引的 embed

#### 🔌 输入与技能
- **附件支持** — 文本文件自动追加到提示（最多 5 个 × 50 KB）；图片通过 `--image` 标志下载传递（最多 4 × 5 MB）
- **技能执行** — `/skill` 斜杠命令，含自动补全、可选参数、线程内恢复
- **热重载** — `~/.claude/skills/` 中新增的技能自动加载（60 秒刷新，无需重启）

### 并发与协调
- **Worktree 指令自动注入** — 每个会话在操作任何文件前都会收到使用 `git worktree` 的提示
- **自动 worktree 清理** — 会话 worktree（`wt-{thread_id}`）在会话结束时和 bot 启动时自动清理；有未提交更改的 worktree 永远不会被自动删除（安全不变量）
- **活跃会话注册表** — 内存注册表；每个会话都能看到其他会话的状态
- **AI Lounge** — 注入每个会话提示的共享「控え室」频道；会话发布意图、互相确认状态，并在破坏性操作前先行检查；对人类来说是实时活动动态
- **协调频道** — 可选的跨会话生命周期广播共享频道
- **协调脚本** — Claude 可在会话中调用 `coord_post.py` / `coord_read.py` 发布和读取事件

### 计划任务
- **SchedulerCog** — SQLite 支持的定期任务执行器，含 30 秒主循环
- **自注册** — Claude 在聊天会话中通过 `POST /api/tasks` 注册任务
- **无需代码变更** — 运行时添加、删除或修改任务
- **启用/禁用** — 不删除任务即可暂停（`PATCH /api/tasks/{id}`）

### CI/CD 自动化
- **Webhook 触发** — 从 GitHub Actions 或任何 CI/CD 系统触发 Claude Code 任务
- **自动升级** — 上游包发布时自动更新 bot
- **感知排空重启** — 在重启前等待活跃会话完成
- **自动恢复标记** — 活跃会话在任何关闭时自动标记为待恢复（升级重启通过 `AutoUpgradeCog`，其他关闭通过 `ClaudeChatCog.cog_unload()`）；bot 重新上线后从中断处继续
- **重启确认** — 可选的升级确认门控

### 会话管理
- **会话同步** — 将 CLI 会话导入为 Discord 线程（`/sync-sessions`）
- **会话列表** — `/sessions`，可按来源（Discord / CLI / 全部）和时间窗口筛选
- **恢复信息** — `/resume-info` 显示在终端继续当前会话的 CLI 命令
- **启动恢复** — 中断的会话在任意 bot 重启后自动恢复；`AutoUpgradeCog`（升级重启）和 `ClaudeChatCog.cog_unload()`（其他关闭）自动标记，或通过 `POST /api/mark-resume` 手动标记
- **程序化创建** — `POST /api/spawn` 从任意脚本或 Claude 子进程创建新 Discord 线程 + Claude 会话；创建线程后立即返回非阻塞 201
- **线程 ID 注入** — `DISCORD_THREAD_ID` 环境变量传递给每个 Claude 子进程，使会话可通过 `$CCDB_API_URL/api/spawn` 创建子会话
- **Worktree 管理** — `/worktree-list` 显示所有活跃会话 worktree 的干净/脏状态；`/worktree-cleanup` 清理孤立的干净 worktree（支持 `dry_run` 预览）

### 安全性
- **无 Shell 注入** — 仅使用 `asyncio.create_subprocess_exec`，从不使用 `shell=True`
- **会话 ID 验证** — 传递给 `--resume` 前使用严格正则验证
- **标志注入防护** — 所有提示前使用 `--` 分隔符
- **密钥隔离** — Bot token 从子进程环境中移除
- **用户授权** — `allowed_user_ids` 限制可调用 Claude 的用户

---

## 快速开始

### 前置条件

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 已安装并认证
- 启用了 Message Content intent 的 Discord Bot token
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 独立运行

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# 使用你的 Bot token 和频道 ID 编辑 .env

uv run python -m claude_discord.main
```

### 作为包安装

如果你已有运行中的 discord.py Bot（Discord 每个 token 只允许一个 Gateway 连接）：

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from discord.ext import commands
from claude_discord import ClaudeRunner, setup_bridge

bot = commands.Bot(...)
runner = ClaudeRunner(command="claude", model="sonnet")

@bot.event
async def on_ready():
    await setup_bridge(
        bot,
        runner,
        claude_channel_id=YOUR_CHANNEL_ID,
        allowed_user_ids={YOUR_USER_ID},
    )
```

`setup_bridge()` 自动连接所有 Cog。ccdb 新增的 Cog 无需修改消费者代码即可自动包含。

更新到最新版本：

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord Bot token | （必填） |
| `DISCORD_CHANNEL_ID` | Claude 聊天频道 ID | （必填） |
| `CLAUDE_COMMAND` | Claude Code CLI 路径 | `claude` |
| `CLAUDE_MODEL` | 使用的模型 | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI 权限模式 | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | 跳过所有权限检查（谨慎使用） | `false` |
| `CLAUDE_WORKING_DIR` | Claude 的工作目录 | 当前目录 |
| `MAX_CONCURRENT_SESSIONS` | 最大并发会话数 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 会话非活动超时 | `300` |
| `DISCORD_OWNER_ID` | Claude 需要输入时 @提及的用户 ID | （可选） |
| `COORDINATION_CHANNEL_ID` | 跨会话事件广播的频道 ID | （可选） |
| `CCDB_COORDINATION_CHANNEL_NAME` | 按名称自动创建协调频道 | （可选） |
| `WORKTREE_BASE_DIR` | 扫描会话 worktree 的基础目录（启用自动清理） | （可选） |

### 权限模式 — `-p` 模式下的功能说明

通过 ccdb 使用时，Claude Code CLI 以 **`-p`（非交互式）模式** 运行。在此模式下，CLI **无法请求权限确认** — 需要审批的工具会被立即拒绝。这是 [CLI 的设计约束](https://code.claude.com/docs/en/headless)，而非 ccdb 的限制。

| 模式 | `-p` 模式下的行为 | 推荐 |
|------|----------------------|----------------|
| `default` | ❌ **所有工具被拒绝** — 无法使用 | 不要使用 |
| `acceptEdits` | ⚠️ Edit/Write 自动批准，Bash 被拒绝（Claude 回退到 Write 进行文件操作） | 最低可用选项 |
| `bypassPermissions` | ✅ 所有工具均被批准 | 可用，但建议使用下方的环境变量 |
| **`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`** | ✅ **所有工具均被批准** | **推荐** — ccdb 已通过 `allowed_user_ids` 限制访问 |

**我们的推荐：** 设置 `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`。由于 ccdb 通过 `allowed_user_ids` 控制与 Claude 的交互，CLI 级别的权限检查只会增加摩擦而没有实质性的安全收益。名称中的「dangerously」体现了 CLI 的通用警告；在 ccdb 已限制访问的上下文中，这是实际可行的选择。

如需精细控制，`CLAUDE_ALLOWED_TOOLS` 的支持已在计划中（[#217](https://github.com/ebibibi/claude-code-discord-bridge/issues/217)）。

> **为什么 Discord 中不显示权限按钮？** CLI 的 `-p` 模式不会发出 `permission_request` 事件，因此 ccdb 无内容可显示。您看到的 `AskUserQuestion` 按钮（Claude 的选择提示）是不同的机制，可以正常工作。详细调查请参阅 [#210](https://github.com/ebibibi/claude-code-discord-bridge/issues/210)。

---

## Discord Bot 设置

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建新应用
2. 创建 Bot 并复制 token
3. 在 Privileged Gateway Intents 中启用 **Message Content Intent**
4. 使用以下权限邀请 Bot：
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages（用于清理反应）
   - Read Message History

---

## GitHub + Claude Code 自动化

### 示例：自动文档同步

每次推送到 `main`，Claude Code：
1. 拉取最新变更并分析差异
2. 更新英文文档
3. 翻译为日文（或任何目标语言）
4. 创建含双语摘要的 PR
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

**Bot 配置：**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="分析变更，更新文档，创建含双语摘要的 PR，启用自动合并。",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
}

await bot.add_cog(WebhookTriggerCog(
    bot=bot,
    runner=runner,
    triggers=triggers,
    channel_ids={YOUR_CHANNEL_ID},
))
```

**安全性：** 提示在服务端定义。Webhook 只负责触发，不能注入任意提示。

### 示例：自动批准所有者 PR

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

---

## 计划任务

运行时注册定期 Claude Code 任务——无需修改代码，无需重新部署。

在 Discord 会话中，Claude 可以注册任务：

```bash
# Claude 在会话中调用：
curl -X POST "$CCDB_API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "检查过时依赖并在发现时开启 issue", "interval_seconds": 604800}'
```

或从自己的脚本注册：

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "每周安全扫描", "interval_seconds": 604800}'
```

30 秒主循环自动检测到期任务并创建 Claude Code 会话。

---

## 自动升级

当新版本发布时自动升级 bot：

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,  # 通过 ✅ 反应确认重启
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

重启前，`AutoUpgradeCog`：

1. **快照活跃会话** — 收集所有有运行中 Claude 会话的线程（鸭子类型：任何有 `_active_runners` dict 的 Cog 都会被自动发现）。
2. **排空** — 等待活跃会话自然结束。
3. **标记恢复** — 将活跃线程 ID 保存到待恢复表。下次启动时，这些会话会以"bot 已重启，请继续"的提示自动恢复。
4. **重启** — 执行配置的重启命令。

任何有 `active_count` 属性的 Cog 都会被自动发现并排空：

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

> **覆盖范围：** `AutoUpgradeCog` 覆盖升级触发的重启。对于*所有其他*关闭（`systemctl stop`、`bot.close()`、SIGTERM），`ClaudeChatCog.cog_unload()` 提供第二道自动安全网。

---

## REST API

可选的 REST API，用于通知和任务管理。需要 aiohttp：

```bash
uv add "claude-code-discord-bridge[api]"
```

### 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/notify` | 发送即时通知 |
| POST | `/api/schedule` | 计划通知 |
| GET | `/api/scheduled` | 列出待处理通知 |
| DELETE | `/api/scheduled/{id}` | 取消通知 |
| POST | `/api/tasks` | 注册计划 Claude Code 任务 |
| GET | `/api/tasks` | 列出已注册任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| PATCH | `/api/tasks/{id}` | 更新任务（启用/禁用，修改计划） |
| POST | `/api/spawn` | 创建新 Discord 线程并启动 Claude Code 会话（非阻塞） |
| POST | `/api/mark-resume` | 标记线程在下次 bot 启动时自动恢复 |
| GET | `/api/lounge` | 获取 AI Lounge 的最近消息 |
| POST | `/api/lounge` | 向 AI Lounge 发布消息（`label` 可选） |

```bash
# 发送通知
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "构建成功！", "title": "CI/CD"}'

# 注册定期任务
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "每日站会摘要", "interval_seconds": 86400}'
```

---

## 架构

```
claude_discord/
  main.py                  # 独立入口点
  setup.py                 # setup_bridge() — 一键 Cog 连接
  bot.py                   # Discord Bot 类
  concurrency.py           # Worktree 指令 + 活跃会话注册表
  cogs/
    claude_chat.py         # 交互式聊天（线程创建，消息处理）
    skill_command.py       # /skill 斜杠命令，含自动补全
    session_manage.py      # /sessions, /sync-sessions, /resume-info
    scheduler.py           # 定期 Claude Code 任务执行器
    webhook_trigger.py     # Webhook → Claude Code 任务（CI/CD）
    auto_upgrade.py        # Webhook → 包升级 + 感知排空重启
    event_processor.py     # EventProcessor — stream-json 事件状态机
    run_config.py          # RunConfig 数据类 — 打包所有 CLI 执行参数
    _run_helper.py         # 薄编排层（run_claude_with_config + shim）
  claude/
    runner.py              # Claude CLI 子进程管理器
    parser.py              # stream-json 事件解析器
    types.py               # SDK 消息类型定义
  coordination/
    service.py             # 向共享频道发布会话生命周期事件
  database/
    models.py              # SQLite 模式
    repository.py          # 会话 CRUD
    task_repo.py           # 计划任务 CRUD
    ask_repo.py            # 待处理 AskUserQuestion CRUD
    notification_repo.py   # 计划通知 CRUD
    resume_repo.py         # 启动恢复 CRUD（跨 bot 重启的待恢复记录）
    settings_repo.py       # 每公会设置
  discord_ui/
    status.py              # 表情反应管理器（防抖）
    chunker.py             # 感知代码块和表格的消息分割
    embeds.py              # Discord embed 构建器
    ask_view.py            # AskUserQuestion 的按钮/下拉菜单
    ask_handler.py         # collect_ask_answers() — AskUserQuestion UI + DB 生命周期
    streaming_manager.py   # StreamingMessageManager — 防抖就地消息编辑
    tool_timer.py          # LiveToolTimer — 长运行工具的耗时计数器
    thread_dashboard.py    # 显示会话状态的实时置顶 embed
    plan_view.py           # Plan Mode 批准/取消按钮（ExitPlanMode）
    permission_view.py     # 工具权限请求允许/拒绝按钮
    elicitation_view.py    # MCP Elicitation 的 Discord UI（Modal 表单或 URL 按钮）
  session_sync.py          # CLI 会话发现和导入
  worktree.py              # WorktreeManager — 安全 git worktree 生命周期（会话结束和启动时清理）
  ext/
    api_server.py          # REST API（可选，需要 aiohttp）
  utils/
    logger.py              # 日志设置
```

### 设计理念

- **CLI 调用而非 API** — 调用 `claude -p --output-format stream-json`，免费获得完整 Claude Code 功能（CLAUDE.md、技能、工具、内存），无需重新实现
- **并发优先** — 多个同时会话是预期场景而非边缘情况；每个会话都有 worktree 指令，注册表和协调频道处理其余部分
- **Discord 作为粘合剂** — Discord 提供 UI、线程、反应、webhook 和持久通知；无需自定义前端
- **框架而非应用** — 作为包安装，向现有 bot 添加 Cog，通过代码配置
- **零代码扩展性** — 无需修改源代码即可添加计划任务和 webhook 触发器
- **简单即安全** — 约 3000 行可审计的 Python；仅使用 subprocess exec，无 shell 扩展

---

## 测试

```bash
uv run pytest tests/ -v --cov=claude_discord
```

700+ 个测试覆盖解析器、分块器、仓库、运行器、流式传输、webhook 触发、自动升级（含 `/upgrade` 斜杠命令、线程调用和批准按钮）、REST API、AskUserQuestion UI、线程面板、计划任务、会话同步、AI Lounge、启动恢复、模型切换、压缩检测、TodoWrite 进度 embed，以及权限/elicitation/plan-mode 事件解析。

---

## 本项目的构建方式

**整个代码库由 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** 编写——Anthropic 的 AI 编程代理。人类作者（[@ebibibi](https://github.com/ebibibi)）以自然语言提供需求和方向，但未手动阅读或编辑源代码。

这意味着：

- **所有代码由 AI 生成** — 架构、实现、测试、文档
- **人类作者无法保证代码级别的正确性** — 如需确认请查看源代码
- **欢迎 Bug 报告和 PR** — Claude Code 将用于处理它们
- **这是 AI 编写的开源软件的真实案例**

本项目始于 2026-02-18，通过与 Claude Code 的迭代对话持续演进。

---

## 实际案例

**[EbiBot](https://github.com/ebibibi/discord-bot)** — 基于此框架构建的个人 Discord Bot。包括自动文档同步（英文 + 日文）、推送通知、Todoist 看门狗、定期健康检查和 GitHub Actions CI/CD。可作为构建自己 bot 的参考。

---

## 灵感来源

- [OpenClaw](https://github.com/openclaw/openclaw) — 表情状态反应、消息防抖、感知代码块分割
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI 调用 + stream-json 方案
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — 权限控制模式
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — 每对话线程模型

---

## 许可证

MIT
