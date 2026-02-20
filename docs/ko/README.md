> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **참고:** 이것은 영문 원본 문서의 자동 번역본입니다.
> 내용에 차이가 있을 경우 [영문판](../../README.md)이 우선합니다.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[Claude Code](https://docs.anthropic.com/en/docs/claude-code)를 Discord와 GitHub에 연결합니다. Claude Code CLI와 Discord를 연결하는 **인터랙티브 채팅, CI/CD 자동화, GitHub 워크플로 통합**을 위한 프레임워크입니다.

Claude Code는 터미널에서 훌륭하지만 훨씬 더 많은 것을 할 수 있습니다. 이 브릿지를 통해 **GitHub 개발 워크플로에서 Claude Code를 사용**할 수 있습니다: 문서 자동 동기화, PR 검토 및 병합, GitHub Actions로 트리거되는 모든 Claude Code 작업 실행. Discord를 범용 접착제로 사용합니다.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **면책 조항:** 이 프로젝트는 Anthropic과 무관하며, Anthropic의 보증이나 공식 연관이 없습니다. "Claude"와 "Claude Code"는 Anthropic, PBC의 상표입니다. 이것은 Claude Code CLI와 인터페이스하는 독립적인 오픈소스 도구입니다.

> **완전히 Claude Code로 제작.** 이 프로젝트는 Anthropic의 AI 코딩 에이전트인 Claude Code 자체에 의해 설계, 구현, 테스트 및 문서화되었습니다. 인간 저자는 소스 코드를 읽지 않았습니다. 자세한 내용은 [이 프로젝트가 구축된 방법](#이-프로젝트가-구축된-방법)을 참조하세요.

## 두 가지 사용 방법

### 1. 인터랙티브 채팅 (모바일 / 데스크탑)

스마트폰이나 Discord가 있는 모든 기기에서 Claude Code를 사용합니다. 각 대화는 완전한 세션 지속성을 가진 Discord 스레드가 됩니다.

```
당신 (Discord)  →  Bridge  →  Claude Code CLI
      ↑                              ↓
      ←──── stream-json 출력 ────────←
```

### 2. CI/CD 자동화 (GitHub → Discord → Claude Code → GitHub)

Discord webhook을 통해 GitHub Actions에서 Claude Code 작업을 트리거합니다. Claude Code가 자율적으로 실행됩니다 — 코드 읽기, 문서 업데이트, PR 생성, 자동 병합 활성화.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (자동 병합)  ←  git push  ←  Claude Code  ←────┘
```

**실제 사례:** main에 푸시할 때마다 Claude Code가 자동으로 변경 사항을 분석하고, 영어와 일본어 문서를 업데이트하고, 이중 언어 요약이 있는 PR을 만들고, 자동 병합을 활성화합니다. 사람의 개입이 필요하지 않습니다.

## 기능

### 인터랙티브 채팅
- **Thread = Session** — 각 작업이 자체 Discord 스레드를 가지며 Claude Code 세션과 1:1로 매핑
- **실시간 상태** — 이모지 반응으로 Claude가 하는 일 표시 (🧠 생각 중, 🛠️ 파일 읽기, 💻 편집 중, 🌐 웹 검색)
- **스트리밍 텍스트** — Claude가 작업하는 동안 중간 텍스트가 실시간으로 표시 (끝날 때만이 아님)
- **도구 결과 표시** — 도구 사용 결과가 embed로 실시간 표시
- **실시간 도구 타이밍** — 장시간 실행 명령(인증 흐름, 빌드 등)에서 10초마다 경과 시간을 업데이트하여 Claude가 여전히 작동 중임을 알 수 있음
- **확장 사고** — Claude의 추론이 스포일러 태그 embed로 표시 (클릭하여 공개)
- **세션 지속성** — `--resume`을 통해 여러 메시지에 걸쳐 대화 계속
- **스킬 실행** — 자동 완성, 선택적 인수, 스레드 내 재개와 함께 `/skill`로 Claude Code 스킬 실행
- **동시 세션** — 여러 세션을 병렬로 실행 (설정 가능한 제한)
- **지우지 않고 중지** — `/stop`으로 실행 중인 세션을 중단하면서 재개를 위해 보존
- **첨부 파일 지원** — 텍스트 파일 첨부가 프롬프트에 자동 추가 (최대 5개 파일, 각 50 KB)
- **타임아웃 알림** — 세션 타임아웃 시 경과 시간과 조치 안내가 포함된 전용 embed
- **인터랙티브 질문** — Claude가 `AskUserQuestion`을 호출하면 Bot이 Discord 버튼 또는 Select Menu를 렌더링하고 답변으로 세션을 재개
- **세션 상태 대시보드** — 메인 채널의 라이브 고정 embed로 어떤 스레드가 처리 중인지 vs. 입력 대기 중인지 표시; Claude가 답변이 필요할 때 소유자를 @mention
- **다중 세션 조율** — `COORDINATION_CHANNEL_ID` 설정 시 각 세션이 공유 채널에 시작/종료 이벤트를 브로드캐스트하여 동시 세션이 서로 인식

### 예약 작업 (SchedulerCog)
- **정기적 Claude Code 작업** — Discord 채팅 또는 REST API를 통해 작업 등록; 설정 가능한 간격으로 실행
- **SQLite 기반** — 작업이 재시작 후에도 유지; `/api/tasks` 엔드포인트로 관리
- **코드 없는 스케줄링** — Claude Code가 세션 중 Bash 도구를 통해 새 작업을 자기 등록 가능; Bot 재시작이나 코드 변경 불필요
- **단일 마스터 루프** — 하나의 30초 `discord.ext.tasks` 루프가 모든 작업을 디스패치하여 오버헤드를 낮게 유지

### CI/CD 자동화
- **Webhook 트리거** — GitHub Actions 또는 모든 CI/CD 시스템에서 Claude Code 작업 트리거
- **자동 업그레이드** — 업스트림 패키지가 릴리스될 때 Bot 자동 업데이트
- **REST API** — 외부 도구에서 알림 푸시 및 예약 작업 관리 (선택적, aiohttp 필요)

### 보안
- **Shell 인젝션 없음** — `asyncio.create_subprocess_exec`만 사용, `shell=True` 절대 없음
- **세션 ID 검증** — `--resume`에 전달 전 엄격한 정규식 검증
- **플래그 인젝션 방지** — 모든 프롬프트 앞에 `--` 구분자
- **비밀 격리** — Bot 토큰과 비밀이 서브프로세스 환경에서 제거
- **사용자 권한** — `allowed_user_ids`로 Claude를 호출할 수 있는 사용자 제한

## 스킬

`/skill` 슬래시 명령을 통해 Discord에서 직접 [Claude Code 스킬](https://docs.anthropic.com/en/docs/claude-code)을 실행합니다.

```
/skill name:goodmorning                      → /goodmorning 실행
/skill name:todoist args:filter "today"      → /todoist filter "today" 실행
/skills                                      → 모든 사용 가능한 스킬 나열
```

**기능:**
- **자동 완성** — 입력하여 필터; 이름과 설명 모두 검색 가능
- **인수** — `args` 매개변수를 통해 추가 인수 전달
- **스레드 내 재개** — 기존 Claude 스레드 내에서 `/skill` 사용 시 새 스레드 대신 현재 세션 내에서 스킬 실행
- **핫 리로드** — `~/.claude/skills/`에 추가된 새 스킬 자동 인식 (60초 갱신 간격, 재시작 불필요)

## 빠른 시작

### 요구 사항

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 설치 및 인증
- Message Content intent가 활성화된 Discord Bot 토큰
- [uv](https://docs.astral.sh/uv/) (권장) 또는 pip

### 독립 실행

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# Bot 토큰과 채널 ID로 .env 편집

uv run python -m claude_discord.main
```

### 패키지로 설치

이미 discord.py Bot이 실행 중인 경우 (Discord는 토큰당 하나의 Gateway 연결만 허용):

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeRunner, setup_bridge

runner = ClaudeRunner(command="claude", model="sonnet")

# 한 번 호출로 모든 Cog 등록 — 새 기능이 자동으로 포함
await setup_bridge(
    bot,
    runner,
    session_db_path="data/sessions.db",
    claude_channel_id=YOUR_CHANNEL_ID,
    allowed_user_ids={YOUR_USER_ID},
)
```

`setup_bridge()`는 `ClaudeChatCog`, `SkillCommandCog`, `SessionManageCog`, `SchedulerCog`를 자동으로 연결합니다. ccdb에 새 Cog가 추가되면 자동으로 포함됩니다 — 소비자 코드 변경 불필요.

<details>
<summary>수동 연결 (고급)</summary>

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```
</details>

최신 버전으로 업데이트:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord Bot 토큰 | (필수) |
| `DISCORD_CHANNEL_ID` | Claude 채팅 채널 ID | (필수) |
| `CLAUDE_COMMAND` | Claude Code CLI 경로 | `claude` |
| `CLAUDE_MODEL` | 사용할 모델 | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI 권한 모드 | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Claude의 작업 디렉토리 | 현재 디렉토리 |
| `MAX_CONCURRENT_SESSIONS` | 최대 동시 세션 수 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 세션 비활성 타임아웃 | `300` |
| `DISCORD_OWNER_ID` | Claude가 입력이 필요할 때 @mention할 Discord 사용자 ID | (선택적) |
| `COORDINATION_CHANNEL_ID` | 다중 세션 조율 브로드캐스트용 채널 ID | (선택적) |

## Discord Bot 설정

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 새 애플리케이션 생성
2. Bot 생성 후 토큰 복사
3. Privileged Gateway Intents에서 **Message Content Intent** 활성화
4. 다음 권한으로 Bot을 서버에 초대:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages (반응 정리용)
   - Read Message History

## GitHub + Claude Code 자동화

Webhook 트리거 시스템으로 Claude Code가 스크립트만 실행하는 것이 아닌 코드 변경을 이해하고 결정을 내리는 지능형 에이전트로 동작하는 완전 자율 CI/CD 워크플로를 구축할 수 있습니다.

### 예시: 자동화된 문서 동기화

main에 푸시할 때마다 Claude Code가:
1. 최신 변경 사항을 가져와 diff 분석
2. 소스 코드가 변경된 경우 영어 문서 업데이트
3. 일본어 (또는 모든 대상 언어)로 번역
4. 이중 언어 요약이 있는 PR 생성
5. 자동 병합 활성화 — CI 통과 시 PR이 자동으로 병합

**GitHub Actions 워크플로:**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    # docs-sync 자체 커밋 건너뛰기 (무한 루프 방지)
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

**Bot 설정:**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="변경 사항 분석, 문서 업데이트, 이중 언어 요약 PR 생성, 자동 병합 활성화.",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
    "🚀 deploy": WebhookTrigger(
        prompt="스테이징 환경에 배포.",
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

**보안:** webhook 메시지만 처리됩니다. 더 엄격한 제어를 위한 선택적 `allowed_webhook_ids`. 프롬프트는 서버 측에서 정의 — webhook은 어떤 트리거를 실행할지만 선택합니다.

### 예시: 소유자 PR 자동 승인

CI 통과 후 자신의 PR을 자동으로 승인하고 자동 병합:

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

## 예약 작업

`SchedulerCog`는 SQLite에 저장된 정기적 Claude Code 작업을 실행합니다. 작업은 런타임에 REST API를 통해 등록됩니다 — 코드 변경이나 Bot 재시작 불필요.

### REST API를 통한 작업 등록

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{
    "name": "daily-standup",
    "prompt": "열린 GitHub 이슈를 확인하고 Discord에 간략한 요약을 게시하세요.",
    "interval_seconds": 86400,
    "channel_id": 123456789
  }'
```

### Claude가 세션 중 자기 등록

Claude Code는 세션 중 Bash 도구를 사용하여 자신의 반복 작업을 등록할 수 있습니다 — 사람의 연결 불필요:

```
# Claude Code 세션 내에서 Claude가 실행:
curl -X POST $CCDB_API_URL/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"name": "health-check", "prompt": "테스트 스위트를 실행하고 결과를 보고하세요.", "interval_seconds": 3600}'
```

`ClaudeRunner`에 `api_port`가 설정되면 `CCDB_API_URL`이 Claude의 서브프로세스 환경에 자동으로 주입됩니다.

## 자동 업그레이드

업스트림 패키지가 릴리스될 때 Bot을 자동으로 업그레이드합니다.

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

**파이프라인:** 업스트림 푸시 → CI webhook → `🔄 bot-upgrade` → `uv lock --upgrade-package` → `uv sync` → 서비스 재시작.

### 우아한 드레인 (DrainAware)

재시작 전에 AutoUpgradeCog는 모든 활성 세션이 완료될 때까지 기다립니다. `active_count` 속성을 구현하는 모든 Cog (`DrainAware` 프로토콜 충족)가 자동으로 발견됩니다 — 수동 `drain_check` 람다 불필요.

내장 DrainAware Cog: `ClaudeChatCog`, `WebhookTriggerCog`.

자신의 Cog를 드레인 지원으로 만들려면 `active_count` 속성만 추가하면 됩니다:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

자동 발견을 재정의하기 위해 명시적 `drain_check` 콜러블을 전달할 수도 있습니다.

### 재시작 승인

자기 업데이트 시나리오 (Bot 자신의 Discord 세션에서 업데이트하는 경우 등)에서 `restart_approval`을 활성화하여 자동 재시작을 방지할 수 있습니다:

```python
config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
)
```

`restart_approval=True`를 사용하면 패키지 업그레이드 후 Bot이 승인을 요청하는 메시지를 게시합니다. ✅로 반응하여 재시작을 트리거합니다. 승인될 때까지 주기적으로 알림을 보냅니다.

## REST API

외부 도구에서 Discord로 알림을 푸시하기 위한 선택적 REST API. aiohttp 필요:

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
    api_secret="your-secret-token",  # 선택적 Bearer 인증
)
await api.start()
```

### 엔드포인트

**알림**

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 헬스 체크 |
| POST | `/api/notify` | 즉시 알림 전송 |
| POST | `/api/schedule` | 나중에 알림 예약 |
| GET | `/api/scheduled` | 대기 중인 알림 나열 |
| DELETE | `/api/scheduled/{id}` | 예약된 알림 취소 |

**예약 작업** (`SchedulerCog` 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/tasks` | 새로운 정기 Claude Code 작업 등록 |
| GET | `/api/tasks` | 모든 등록된 작업 나열 |
| DELETE | `/api/tasks/{id}` | 예약된 작업 제거 |
| PATCH | `/api/tasks/{id}` | 작업 업데이트 (활성화/비활성화, 프롬프트, 간격) |

### 사용 예시

```bash
# 헬스 체크
curl http://localhost:8080/api/health

# 알림 전송
curl -X POST http://localhost:8080/api/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"message": "빌드 성공!", "title": "CI/CD"}'

# 알림 예약
curl -X POST http://localhost:8080/api/schedule \
  -H "Content-Type: application/json" \
  -d '{"message": "PR 검토 시간입니다", "scheduled_at": "2026-01-01T09:00:00"}'
```

## 아키텍처

```
claude_discord/
  main.py                  # 독립 실행 진입점
  bot.py                   # Discord Bot 클래스
  setup.py                 # setup_bridge() — 모든 Cog를 위한 원클릭 팩토리
  cogs/
    claude_chat.py         # 인터랙티브 채팅 (스레드 생성, 메시지 처리)
    skill_command.py       # /skill 슬래시 명령 (자동 완성)
    webhook_trigger.py     # Webhook → Claude Code 작업 실행 (CI/CD)
    auto_upgrade.py        # Webhook → 패키지 업그레이드 + 재시작
    scheduler.py           # 정기 Claude Code 작업 (SQLite 기반, 30초 마스터 루프)
    _run_helper.py         # 공유 Claude CLI 실행 로직
  claude/
    runner.py              # Claude CLI 서브프로세스 관리자
    parser.py              # stream-json 이벤트 파서
    types.py               # SDK 메시지 타입 정의
  database/
    models.py              # SQLite 스키마
    repository.py          # 세션 CRUD 작업
    ask_repo.py            # 대기 중인 AskUserQuestion CRUD (재시작 복구)
    notification_repo.py   # 예약 알림 CRUD
    task_repo.py           # 예약 작업 CRUD (SchedulerCog)
  coordination/
    service.py             # CoordinationService — 공유 채널에 세션 라이프사이클 이벤트 게시
  discord_ui/
    status.py              # 이모지 반응 상태 관리자 (디바운스)
    chunker.py             # 코드 펜스 및 테이블 인식 메시지 분할
    embeds.py              # Discord embed 빌더
    ask_view.py            # AskUserQuestion용 Discord 버튼/Select Menu
    ask_bus.py             # 영구 AskView 버튼을 위한 버스 라우팅 (재시작 후에도 유지)
    thread_dashboard.py    # 스레드별 세션 상태를 표시하는 라이브 고정 embed
  ext/
    api_server.py          # REST API 서버 (선택적, aiohttp 필요)
                           # SchedulerCog용 /api/tasks 엔드포인트 포함
  utils/
    logger.py              # 로깅 설정
```

### 설계 철학

- **CLI 생성, API 아님** — `claude -p --output-format stream-json` 호출로 전체 Claude Code 기능 (CLAUDE.md, 스킬, 도구, 메모리) 무료 사용
- **Discord를 접착제로** — Discord가 UI, 스레딩, 알림, webhook 인프라 제공
- **프레임워크, 애플리케이션 아님** — 패키지로 설치하고, 기존 Bot에 Cog 추가, 코드로 설정
- **단순함에 의한 보안** — 약 2500줄의 감사 가능한 Python, Shell 실행 없음, 임의 코드 경로 없음

## 테스트

```bash
uv run pytest tests/ -v --cov=claude_discord
```

473개 테스트가 파서, 청커, 리포지토리, 러너, 스트리밍, webhook 트리거, 자동 업그레이드, REST API, AskUserQuestion UI, 스레드 상태 대시보드, SchedulerCog 및 작업 리포지토리를 커버합니다.

## 이 프로젝트가 구축된 방법

**이 전체 코드베이스는 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**——Anthropic의 AI 코딩 에이전트에 의해 작성되었습니다. 인간 저자([@ebibibi](https://github.com/ebibibi))는 자연어로 요구 사항과 방향을 제공했지만, 소스 코드를 직접 읽거나 편집하지 않았습니다.

이것은 다음을 의미합니다:

- **모든 코드가 AI 생성** — 아키텍처, 구현, 테스트, 문서
- **인간 저자는 코드 수준의 정확성을 보장할 수 없음** — 확신이 필요하면 소스를 검토하세요
- **버그 보고와 PR을 환영합니다** — Claude Code가 이것들도 처리하는 데 사용될 가능성이 높습니다
- **이것은 AI가 저술한 오픈소스 소프트웨어의 실제 예시** — Claude Code가 무엇을 만들 수 있는지의 참고 자료로 사용하세요

이 프로젝트는 2026-02-18에 시작되었으며 Claude Code와의 반복적인 대화를 통해 계속 발전하고 있습니다.

## 실제 사례

**[EbiBot](https://github.com/ebibibi/discord-bot)** — claude-code-discord-bridge를 패키지 의존성으로 사용하는 개인 Discord Bot. 자동 문서 동기화 (영어 + 일본어), 푸시 알림, Todoist 감시견, GitHub Actions와의 CI/CD 통합을 포함합니다. 이 프레임워크 위에 자신의 Bot을 구축하는 참고 자료로 활용하세요.

## 영감을 준 프로젝트

- [OpenClaw](https://github.com/openclaw/openclaw) — 이모지 상태 반응, 메시지 디바운싱, 펜스 인식 청킹
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI 생성 + stream-json 접근
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — 권한 제어 패턴
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — 대화별 스레드 모델

## 라이선스

MIT
