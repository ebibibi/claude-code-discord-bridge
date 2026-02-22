> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **참고:** 이 문서는 영어 원본 문서의 자동 번역본입니다.
> 내용이 다를 경우 [영어 버전](../../README.md)이 우선합니다.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Discord를 통해 여러 Claude Code 세션을 안전하게 병렬로 실행합니다.**

각 Discord 스레드는 격리된 Claude Code 세션이 됩니다. 필요한 만큼 스레드를 열 수 있습니다: 한 스레드에서 기능을 개발하고, 다른 스레드에서 PR을 리뷰하고, 세 번째 스레드에서 예약 작업을 실행하세요. 브리지가 자동으로 조정하여 동시 세션들이 서로 충돌하지 않습니다.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **면책 조항:** 이 프로젝트는 Anthropic과 제휴하거나 승인받거나 공식적으로 연결되어 있지 않습니다. "Claude"와 "Claude Code"는 Anthropic, PBC의 상표입니다. 이것은 Claude Code CLI와 인터페이스하는 독립적인 오픈소스 도구입니다.

> **Claude Code로 완전히 구축되었습니다.** 아키텍처, 구현, 테스트, 문서 — 이 전체 코드베이스는 Claude Code 자체에 의해 작성되었습니다. 인간 저자는 요구 사항과 방향을 자연어로 제공했습니다. 자세한 내용은 [이 프로젝트가 구축된 방법](#이-프로젝트가-구축된-방법)을 참조하세요.

---

## 핵심 아이디어: 두려움 없는 병렬 세션

별도의 Discord 스레드에서 Claude Code에 작업을 보내면, 브리지가 자동으로 4가지를 수행합니다:

1. **동시성 지시 자동 주입** — 모든 세션의 시스템 프롬프트에 필수 지시를 포함합니다: git worktree를 생성하고, 그 안에서만 작업하고, 메인 작업 디렉토리에 직접 접근하지 않을 것.

2. **활성 세션 레지스트리** — 실행 중인 각 세션이 다른 세션들을 알고 있습니다. 두 세션이 같은 레포지토리에 접근하려 할 때, 충돌 대신 조율할 수 있습니다.

3. **협조 채널** — 세션의 시작/종료 이벤트를 브로드캐스트하는 공유 Discord 채널. Claude와 인간 모두 모든 활성 스레드에서 무슨 일이 일어나고 있는지 한눈에 확인할 수 있습니다.

4. **AI Lounge** — 모든 세션 프롬프트에 주입되는 세션 간 "휴게실". 시작하기 전에 각 세션은 다른 세션들이 무엇을 하고 있는지 확인하기 위해 최근 라운지 메시지를 읽습니다. 파괴적인 작업(force push, bot 재시작, DB 삭제)을 하기 전에 세션들이 서로의 작업을 방해하지 않도록 라운지를 먼저 확인합니다.

```
스레드 A (기능개발)  ──→  Claude Code (worktree-A)  ─┐
스레드 B (PR 리뷰)   ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
스레드 C (문서)      ──→  Claude Code (worktree-C)  ─┘    "A: auth 리팩토링 진행 중"
              ↓ 라이프사이클 이벤트                        "B: PR #42 리뷰 완료"
    #coordination 채널                                     "C: README 업데이트 중"
    "A: auth 리팩토링 시작"
    "B: PR #42 리뷰 중"
    "C: README 업데이트 중"
```

경쟁 조건 없음. 작업 손실 없음. 머지 충돌 없음.

---

## 할 수 있는 것

### 인터랙티브 채팅 (모바일 / 데스크톱)

Discord가 있는 어떤 기기에서든 — 스마트폰, 태블릿, 데스크톱 — Claude Code를 사용하세요. 각 메시지는 지속적인 Claude Code 세션에 1:1로 매핑된 스레드를 생성하거나 이어갑니다.

### 병렬 개발

여러 스레드를 동시에 열 수 있습니다. 각 스레드는 독립적인 컨텍스트, 작업 디렉토리, git worktree를 가진 독립적인 Claude Code 세션입니다. 유용한 패턴:

- **기능 개발 + 리뷰 병렬**: 한 스레드에서 기능을 시작하면서 Claude가 다른 스레드에서 PR을 리뷰합니다.
- **여러 기여자**: 팀원들이 각자의 스레드를 가집니다; 세션들이 협조 채널을 통해 서로 인식합니다.
- **안전한 실험**: 스레드 B는 안정적인 코드를 유지하면서 스레드 A에서 방법을 시도해봅니다.

### 예약 작업 (SchedulerCog)

코드 변경이나 재배포 없이 Discord 대화나 REST API를 통해 주기적인 Claude Code 작업을 등록합니다. 작업은 SQLite에 저장되고 설정 가능한 일정에 따라 실행됩니다.

```
/skill name:goodmorning         → 즉시 실행
Claude가 POST /api/tasks 호출  → 주기적 작업 등록
SchedulerCog (30초 마스터 루프) → 예정된 작업 자동 실행
```

### CI/CD 자동화

Discord webhook을 통해 GitHub Actions에서 Claude Code 작업을 트리거합니다. Claude가 자율적으로 실행 — 코드 읽기, 문서 업데이트, PR 생성, 자동 머지 활성화.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**실제 사례:** main에 푸시할 때마다 Claude가 diff를 분석하고, 영어 + 일본어 문서를 업데이트하고, 이중 언어 요약이 포함된 PR을 생성하고, 자동 머지를 활성화합니다. 사람의 개입이 필요 없습니다.

### 세션 동기화

이미 직접 Claude Code CLI를 사용하고 있나요? `/sync-sessions`으로 기존 터미널 세션을 Discord 스레드에 동기화하세요. 최근 대화 메시지를 채워서 컨텍스트 손실 없이 스마트폰에서 CLI 세션을 이어갈 수 있습니다.

### AI Lounge

모든 동시 세션이 서로 상태를 알리고, 업데이트를 읽고, 파괴적인 작업 전에 조율하는 공유 "휴게실" 채널입니다.

각 Claude 세션은 시스템 프롬프트에 자동으로 라운지 컨텍스트를 받습니다: 다른 세션의 최근 메시지와 파괴적인 작업 전에 확인해야 하는 규칙.

```bash
# 세션은 시작하기 전에 의도를 게시합니다:
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "feature/oauth에서 auth 리팩토링 시작 — worktree-A", "label": "기능 개발"}'

# 최근 라운지 메시지 읽기 (각 세션에도 자동 주입):
curl "$CCDB_API_URL/api/lounge"
```

라운지 채널은 인간에게 보이는 활동 피드 역할도 합니다 — Discord에서 열어 현재 모든 활성 Claude 세션이 무엇을 하고 있는지 한눈에 확인하세요.

### 프로그래밍 방식의 세션 생성

스크립트, GitHub Actions, 또는 다른 Claude 세션에서 Discord 메시지 상호작용 없이 새 Claude Code 세션을 생성합니다.

```bash
# 다른 Claude 세션이나 CI 스크립트에서:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "레포지토리 보안 스캔 실행", "thread_name": "보안 스캔"}'
# 스레드 생성 직후 즉시 스레드 ID와 함께 반환; Claude는 백그라운드에서 실행
```

### 시작 시 재개

Bot 재시작으로 세션이 중단된 경우, 중단된 Claude 세션이 Bot이 다시 온라인 상태가 되면 자동으로 재개됩니다. 세 가지 방법으로 세션이 재개용으로 표시됩니다:

- **자동 (업그레이드 재시작)** — `AutoUpgradeCog`가 패키지 업그레이드 재시작 직전에 모든 활성 세션을 스냅샷하고 자동으로 표시합니다.
- **자동 (모든 종료)** — `ClaudeChatCog.cog_unload()`가 Bot이 임의의 메커니즘(`systemctl stop`, `bot.close()`, SIGTERM 등)으로 종료될 때마다 실행 중인 모든 세션을 표시합니다.
- **수동** — 모든 세션이 직접 `POST /api/mark-resume`을 호출할 수 있습니다.

---

## 기능

### 인터랙티브 채팅
- **Thread = Session** — Discord 스레드와 Claude Code 세션 1:1 매핑
- **실시간 상태** — 이모지 리액션: 🧠 생각 중, 🛠️ 파일 읽기, 💻 편집 중, 🌐 웹 검색
- **스트리밍 텍스트** — Claude 작업 중 중간 어시스턴트 텍스트가 실시간 표시
- **도구 결과 embeds** — 10초마다 경과 시간이 올라가는 라이브 도구 호출 결과
- **확장 사고** — 스포일러 태그 embeds로 표시된 추론 (클릭하여 열기)
- **세션 지속성** — `--resume`으로 메시지 간 대화 재개
- **스킬 실행** — 자동 완성, 선택적 인수, 스레드 내 재개가 있는 `/skill` 명령
- **핫 리로드** — `~/.claude/skills/`에 추가된 새 스킬이 자동으로 감지됨 (60초 새로고침, 재시작 불필요)
- **동시 세션** — 설정 가능한 제한으로 여러 병렬 세션
- **중지 (지우지 않음)** — `/stop`은 세션을 보존하면서 중단하여 재개 가능
- **첨부 파일 지원** — 텍스트 파일이 프롬프트에 자동 추가 (최대 5개 × 50KB)
- **타임아웃 알림** — 경과 시간과 재개 안내가 포함된 embed로 타임아웃 알림
- **인터랙티브 질문** — `AskUserQuestion`이 Discord 버튼 또는 선택 메뉴로 렌더링; 답변으로 세션 재개; 버튼이 Bot 재시작 후에도 유지
- **스레드 대시보드** — 어떤 스레드가 활성 상태인지 보여주는 실시간 핀된 embed; 입력이 필요할 때 소유자 @멘션
- **토큰 사용량** — 세션 완료 embed에 캐시 적중률 및 토큰 수 표시

### 동시성 및 조율
- **Worktree 지시 자동 주입** — 모든 세션에 파일을 건드리기 전에 `git worktree`를 사용하도록 지시
- **Worktree 자동 정리** — 세션 종료 시 및 Bot 시작 시 세션 worktrees(`wt-{thread_id}`)가 자동으로 제거됨; 더럽혀진 worktrees는 절대 자동 제거 안 됨 (안전 불변)
- **활성 세션 레지스트리** — 인메모리 레지스트리; 각 세션이 다른 세션들의 상태를 확인
- **AI Lounge** — 모든 세션 프롬프트에 주입된 공유 "휴게실" 채널; 세션들이 의도를 게시하고, 서로의 상태를 읽고, 파괴적인 작업 전에 확인함; 인간에게는 라이브 활동 피드로 보임
- **협조 채널** — 세션 간 라이프사이클 브로드캐스트를 위한 선택적 공유 채널
- **협조 스크립트** — Claude가 세션 내에서 `coord_post.py` / `coord_read.py`를 호출하여 이벤트를 게시하고 읽을 수 있음

### 예약 작업
- **SchedulerCog** — 30초 마스터 루프가 있는 SQLite 기반 주기적 작업 실행기
- **자기 등록** — Claude가 채팅 세션 중 `POST /api/tasks`를 통해 작업 등록
- **코드 변경 없음** — 런타임에서 작업 추가, 제거, 수정
- **활성화/비활성화** — 삭제 없이 작업 일시 중지 (`PATCH /api/tasks/{id}`)

### CI/CD 자동화
- **Webhook 트리거** — GitHub Actions나 모든 CI/CD 시스템에서 Claude Code 작업 트리거
- **자동 업그레이드** — 업스트림 패키지가 릴리스되면 Bot 자동 업데이트
- **DrainAware 재시작** — 재시작 전에 활성 세션이 완료될 때까지 대기
- **자동 재개 표시** — 활성 세션이 임의의 종료 시 자동으로 재개용으로 표시됨; Bot 재가동 후 중단된 곳에서 재개
- **재시작 승인** — 업그레이드 적용 전에 확인하는 선택적 게이트

### 세션 관리
- **세션 동기화** — CLI 세션을 Discord 스레드로 가져오기 (`/sync-sessions`)
- **세션 목록** — 출처 (Discord / CLI / 전체) 및 시간 창으로 필터링하는 `/sessions`
- **재개 정보** — `/resume-info`는 터미널에서 현재 세션을 계속하기 위한 CLI 명령을 표시
- **시작 시 재개** — 중단된 세션이 Bot 재부팅 후 자동으로 재시작됨
- **프로그래밍 방식 생성** — `POST /api/spawn`으로 임의의 스크립트나 Claude 서브프로세스에서 새 Discord 스레드 + Claude 세션 생성
- **스레드 ID 주입** — `DISCORD_THREAD_ID` 환경 변수가 모든 Claude 서브프로세스에 전달됨, 세션이 `$CCDB_API_URL/api/spawn`을 통해 하위 세션 생성 가능
- **Worktree 관리** — `/worktree-list`는 clean/dirty 상태와 함께 모든 활성 세션 worktrees를 표시; `/worktree-cleanup`은 고아 clean worktrees 제거

### 보안
- **Shell 주입 없음** — `asyncio.create_subprocess_exec`만 사용, 절대 `shell=True` 사용 안 함
- **세션 ID 검증** — `--resume`에 전달하기 전 엄격한 정규식 검증
- **플래그 주입 방지** — 모든 프롬프트 앞에 `--` 구분자
- **시크릿 격리** — Bot 토큰이 서브프로세스 환경에서 제거됨
- **사용자 인증** — `allowed_user_ids`로 Claude를 호출할 수 있는 사용자 제한

---

## 빠른 시작 — 5분 만에 Discord에서 Claude

### 1단계 — 사전 요구 사항

- **Python 3.10+** 및 **[uv](https://docs.astral.sh/uv/)** 설치
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** 설치 및 인증 (`claude --version`이 작동해야 함)
- 관리자 권한이 있는 **Discord 서버**

### 2단계 — Discord Bot 만들기

1. [discord.com/developers/applications](https://discord.com/developers/applications)으로 이동하여 **New Application** 클릭
2. **Bot** → **Add Bot** 클릭
3. **Privileged Gateway Intents**에서 **Message Content Intent** 활성화
4. Bot **Token** 복사 (곧 필요)
5. **OAuth2 → URL Generator**로 이동:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Create Public Threads`, `Send Messages in Threads`, `Add Reactions`, `Manage Messages`, `Read Message History`
6. 생성된 URL을 브라우저에서 열어 Bot을 서버에 초대

### 3단계 — Discord ID 가져오기

Discord에서 **Developer Mode** 활성화 (설정 → 고급 → 개발자 모드), 그런 다음:

- **Channel ID**: Claude가 들을 채널을 우클릭 → **Channel ID 복사**
- **본인 User ID**: 본인 사용자명을 우클릭 → **User ID 복사**

### 4단계 — 실행

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
cp .env.example .env
```

`.env` 편집:

```env
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=123456789012345678    # 위에서 복사한 채널
DISCORD_OWNER_ID=987654321098765432      # 본인 User ID (@멘션용)
CLAUDE_WORKING_DIR=/path/to/your/project
```

그런 다음 Bot 시작:

```bash
uv run python -m claude_discord.main
```

설정한 채널에 메시지를 보내면 — Claude가 새 스레드에서 응답합니다.

---

### 최소 Bot (패키지로 설치)

이미 discord.py Bot이 있다면, 대신 ccdb를 패키지로 추가하세요:

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

`bot.py` 생성:

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

`setup_bridge()`가 모든 Cog를 자동으로 연결합니다. 최신 버전으로 업데이트:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord Bot 토큰 | (필수) |
| `DISCORD_CHANNEL_ID` | Claude 채팅 채널 ID | (필수) |
| `CLAUDE_COMMAND` | Claude Code CLI 경로 | `claude` |
| `CLAUDE_MODEL` | 사용할 모델 | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI 권한 모드 | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Claude의 작업 디렉토리 | 현재 디렉토리 |
| `MAX_CONCURRENT_SESSIONS` | 최대 병렬 세션 수 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 세션 비활성 타임아웃 | `300` |
| `DISCORD_OWNER_ID` | Claude가 입력이 필요할 때 @멘션할 User ID | (선택) |
| `COORDINATION_CHANNEL_ID` | 세션 간 이벤트 브로드캐스트를 위한 채널 ID | (선택) |
| `CCDB_COORDINATION_CHANNEL_NAME` | 이름으로 협조 채널 자동 생성 | (선택) |
| `WORKTREE_BASE_DIR` | 세션 worktrees 스캔 기본 디렉토리 (자동 정리 활성화) | (선택) |

---

## REST API

알림 및 작업 관리를 위한 선택적 REST API. aiohttp 필요:

```bash
uv add "claude-code-discord-bridge[api]"
```

### 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 헬스 체크 |
| POST | `/api/notify` | 즉시 알림 전송 |
| POST | `/api/schedule` | 알림 예약 |
| GET | `/api/scheduled` | 대기 중인 알림 목록 |
| DELETE | `/api/scheduled/{id}` | 알림 취소 |
| POST | `/api/tasks` | 예약된 Claude Code 작업 등록 |
| GET | `/api/tasks` | 등록된 작업 목록 |
| DELETE | `/api/tasks/{id}` | 작업 제거 |
| PATCH | `/api/tasks/{id}` | 작업 업데이트 (활성화/비활성화, 일정 변경) |
| POST | `/api/spawn` | 새 Discord 스레드 생성 및 Claude Code 세션 시작 (논블로킹) |
| POST | `/api/mark-resume` | 다음 Bot 시작 시 스레드 자동 재개 표시 |
| GET | `/api/lounge` | 최근 AI Lounge 메시지 읽기 |
| POST | `/api/lounge` | AI Lounge에 메시지 게시 (선택적 `label`) |

---

## 테스트

```bash
uv run pytest tests/ -v --cov=claude_discord
```

610개 이상의 테스트가 파서, 청커, 리포지토리, 러너, 스트리밍, webhook 트리거, 자동 업그레이드, REST API, AskUserQuestion UI, 스레드 대시보드, 예약 작업, 세션 동기화, AI Lounge, 시작 시 재개를 커버합니다.

---

## 이 프로젝트가 구축된 방법

**이 코드베이스는 [@ebibibi](https://github.com/ebibibi)의 지휘 하에 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic의 AI 코딩 에이전트에 의해 개발되었습니다. 인간 저자는 요구 사항을 정의하고, 풀 리퀘스트를 검토하고, 모든 변경 사항을 승인합니다 — Claude Code가 구현을 담당합니다.

이것은 다음을 의미합니다:

- **구현은 AI 생성** — 아키텍처, 코드, 테스트, 문서
- **PR 수준에서 인간 검토 적용** — 모든 변경 사항이 GitHub 풀 리퀘스트와 CI를 통과한 후 머지됨
- **버그 리포트와 PR을 환영합니다** — Claude Code가 이를 처리하는 데 사용될 것입니다
- **이것은 인간이 지휘하고 AI가 구현하는 오픈소스 소프트웨어의 실제 사례입니다**

이 프로젝트는 2026-02-18에 시작되어 Claude Code와의 반복적인 대화를 통해 계속 발전하고 있습니다.

---

## 실제 사례

**[EbiBot](https://github.com/ebibibi/discord-bot)** — 이 프레임워크를 기반으로 한 개인 Discord Bot. 자동 문서 동기화 (영어 + 일본어), 푸시 알림, Todoist 감시, 예약된 헬스 체크, GitHub Actions CI/CD를 포함합니다. 자체 Bot을 구축하기 위한 참고 자료로 사용하세요.

---

## 라이선스

MIT
