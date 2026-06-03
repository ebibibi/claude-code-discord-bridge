> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **참고:** 이 문서는 원본 영어 문서의 자동 번역본입니다.
> 내용이 다를 경우 [영어 버전](../../README.md)이 우선합니다.

# Claude & Codex Discord Bridge

*패키지명: `claude-code-discord-bridge` (케밥 케이스)*

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**스마트폰에서 Claude Code _또는_ OpenAI Codex를 사용하세요. 멀티 스레드, 동시 진행, 실전 개발까지.**

스마트폰 Discord 앱에서 Claude Code 또는 OpenAI Codex를 실행하고, 여러 스레드를 열어 개발 세션을 병렬로 진행하세요 — 키보드 없이도 가능합니다. 각 Discord 스레드는 완전히 격리된 AI 세션이 됩니다. 한 스레드에서 기능 개발, 다른 스레드에서 PR 리뷰, 세 번째 스레드에서 백그라운드 작업 — 동시에, 심지어 스레드마다 다른 백엔드를 사용할 수도 있습니다. 브리지가 모든 조율을 처리하여 세션들이 서로 충돌하지 않습니다.

**기존 구독을 그대로 활용. API 키 설정 불필요.** ccdb는 공식 CLI 위에서 실행됩니다 — Claude Code([Claude Pro/Max 구독](https://claude.ai/pricing) 포함)와 OpenAI Codex([ChatGPT Plus/Pro/Business](https://chatgpt.com) 포함). `/backend`로 백엔드를 전환하거나 스레드별로 설정하세요 — 예측 가능한 비용으로 Discord를 통해 두 AI를 모두 사용할 수 있습니다.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **면책 조항:** 이 프로젝트는 Anthropic 또는 OpenAI와 제휴, 보증 또는 공식 관계가 없습니다. "Claude"와 "Claude Code"는 Anthropic, PBC의 상표이며, "OpenAI", "Codex", "ChatGPT"는 OpenAI의 상표입니다. 이것은 Claude Code CLI 및 OpenAI Codex CLI와 인터페이스하는 독립적인 오픈소스 도구입니다.

> **Claude Code로 완전히 구축.** 전체 코드베이스 — 아키텍처, 구현, 테스트, 문서 — 는 Claude Code 자체가 작성했습니다. 인간 저자는 자연어로 요구사항과 방향을 제공했습니다. [이 프로젝트의 구축 방법](#이-프로젝트의-구축-방법)을 참조하세요.

---

## 핵심 아이디어: 충돌 없는 병렬 세션

여러 Discord 스레드에서 Claude Code에 작업을 보내면, 브리지는 자동으로 네 가지를 수행합니다:

1. **동시성 알림 주입** — 모든 세션의 시스템 프롬프트에 필수 지침이 포함됩니다: git worktree 생성, 그 안에서만 작업, 메인 작업 디렉토리 직접 수정 금지.

2. **활성 세션 레지스트리** — 실행 중인 각 세션은 다른 세션들의 존재를 알고 있습니다. 두 세션이 같은 저장소를 건드리려 할 경우, 충돌 대신 조율할 수 있습니다.

3. **AI Lounge** — 모든 세션의 프롬프트에 주입되는 "휴게실" 채널. 시작 전에 각 세션은 최근 라운지 메시지를 읽어 다른 세션들의 동향을 파악합니다. 파괴적인 작업(강제 푸시, 봇 재시작, DB 삭제) 전에 세션은 라운지를 먼저 확인합니다.

```
스레드 A (기능)    ──→  Claude Code (worktree-A)  ─┐
스레드 B (PR 리뷰) ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
스레드 C (문서)    ──→  Claude Code (worktree-C)  ─┘    "A: auth 리팩토링 진행 중"
                                                         "B: PR #42 리뷰 완료"
                                                         "C: README 업데이트 중"
```

경쟁 조건 없음. 작업 손실 없음. 머지 충돌 없음.

---

## 할 수 있는 것들

### 인터랙티브 채팅 (모바일 / 데스크탑)

Discord가 실행되는 모든 곳에서 Claude Code 사용 — 스마트폰, 태블릿, 데스크탑. 각 메시지는 스레드를 생성하거나 계속하며, 지속적인 Claude Code 세션과 1:1로 매핑됩니다.

### 병렬 개발

여러 스레드를 동시에 열기. 각 스레드는 독자적인 컨텍스트, 작업 디렉토리, git worktree를 가진 독립적인 Claude Code 세션입니다. 유용한 패턴:

- **기능 + 리뷰 병렬 진행**: 한 스레드에서 기능 개발하면서 Claude가 다른 스레드에서 PR 리뷰.
- **여러 기여자**: 팀원 각자가 자신의 스레드를 가지며, AI Lounge를 통해 세션들이 서로의 동향 파악.
- **안전한 실험**: 스레드 A에서 접근법을 시도하면서 스레드 B는 안정적인 코드 유지.

### 예약 작업 (SchedulerCog)

코드 변경, 재배포 없이 Discord 대화 또는 REST API로 주기적인 Claude Code 작업을 등록. 작업은 SQLite에 저장되고 설정 가능한 일정에 따라 실행됩니다.

```
/skill name:goodmorning         → 즉시 실행
Claude가 POST /api/tasks 호출  → 주기적 작업 등록
SchedulerCog (30초 마스터 루프) → 기한 된 작업 자동 실행
```

### CI/CD 자동화

Discord webhook을 통해 GitHub Actions에서 Claude Code 작업을 트리거. Claude가 자율적으로 실행 — 코드 읽기, 문서 업데이트, PR 생성, 자동 머지 활성화.

**실제 예시:** main에 푸시할 때마다 Claude가 diff를 분석하고, 영문 + 일문 문서를 업데이트하고, 이중 언어 PR을 생성하고, 자동 머지를 활성화합니다. 사람 개입 없음.

### 세션 동기화

이미 Claude Code CLI를 직접 사용 중이라면? `/sync-sessions`으로 기존 터미널 세션을 Discord 스레드로 동기화. 최근 대화 메시지를 백필하여 컨텍스트 손실 없이 스마트폰에서 CLI 세션을 계속할 수 있습니다.

### AI Lounge

모든 동시 세션이 서로 발표하고, 업데이트를 읽고, 파괴적인 작업 전에 조율하는 공유 "휴게실" 채널. 각 Claude 세션은 `--append-system-prompt`를 통해 자동으로 라운지 컨텍스트를 받습니다 — 대화 기록이 아닌 에페메랄 시스템 컨텍스트로 주입되어 장기 세션에서 "Prompt is too long" 오류를 방지합니다.

### 프로그래밍 방식 세션 생성

스크립트, GitHub Actions, 또는 다른 Claude 세션에서 Discord 메시지 상호작용 없이 새로운 Claude Code 세션 생성.

```bash
# 다른 Claude 세션이나 CI 스크립트에서:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "저장소에 보안 스캔 실행", "thread_name": "Security Scan"}'
# 스레드 생성 후 즉시 반환; Claude는 백그라운드에서 실행
```

---

## 기능 목록

### 인터랙티브 채팅

#### 🔗 세션 기본
- **채팅 전용 모드** — `CHAT_ONLY_CHANNEL_IDS`로 Claude 텍스트 응답만 표시; 도구 embed, 사고 블록, 세션 embed, 할 일 목록 숨김
- **스레드 = 세션** — Discord 스레드와 Claude Code 세션 1:1 매핑
- **목표 추적** — `/goal <조건>` 완료 조건 설정; Claude가 조건 충족까지 계속 작업
- **세션 지속성** — `--resume`으로 메시지 간 대화 계속
- **동시 세션** — 설정 가능한 제한으로 여러 병렬 세션
- **지우지 않고 중지** — `/stop`으로 재개 가능하도록 세션 보존하며 중지
- **세션 중단** — 활성 스레드에 새 메시지 전송 시 실행 중인 세션에 SIGINT 전송 후 새 지침으로 시작
- **스레드 자동 이름 변경** — `THREAD_AUTO_RENAME=true`로 Claude 생성 제목으로 자동 이름 변경

#### 📡 실시간 피드백
- **실시간 상태** — 이모지 반응: 🧠 사고 중, 🛠️ 파일 읽기, 💻 편집 중, 🌐 웹 검색
- **스트리밍 텍스트** — Claude가 작업하는 동안 중간 텍스트 실시간 표시
- **도구 결과 embed** — 라이브 도구 호출 결과, 경과 시간 표시
- **확장 사고** — 추론을 스포일러 태그 embed로 표시 (클릭하여 펼치기)
- **스레드 대시보드** — 활성 vs. 대기 스레드 표시하는 라이브 고정 embed

#### 🤝 Human-in-the-Loop
- **인터랙티브 질문** — `AskUserQuestion`을 Discord 버튼 또는 선택 메뉴로 렌더링; 봇 재시작 후에도 버튼 유효; 입력이 필요할 때 요청자를 @mention
- **계획 모드** — `ExitPlanMode` 호출 시 Discord embed에 전체 계획과 승인/취소 버튼 표시; 승인 요청 시 요청자를 @mention; 5분 타임아웃
- **도구 권한 요청** — 허용/거부 버튼; 요청자를 @mention; 2분 무응답 시 자동 거부
- **MCP Elicitation** — MCP 서버가 Discord를 통해 사용자 입력 요청; 요청자를 @mention; 5분 타임아웃
- **TodoWrite 실시간 진행** — 단일 Discord embed 인플레이스 업데이트; ✅ 완료, 🔄 진행 중, ⬜ 대기 표시

#### 📊 관찰 가능성
- **토큰 사용량** — 세션 완료 embed에 캐시 히트율과 토큰 수 표시
- **컨텍스트 사용량** — 컨텍스트 창 백분율 표시; 83.5% 이상 시 ⚠️ 경고
- **압축 감지** — 컨텍스트 압축 발생 시 스레드 내 알림
- **장시간 중단 알림** — 활동 없음 알림 (표준 모델 30초, Opus 120초)
- **타임아웃 알림** — 경과 시간과 재개 안내가 포함된 embed
- **StatusLine 표시** — Claude가 `statusLine` 설정 시 각 세션 후 Discord에 표시
- **스레드 수신함** — `THREAD_INBOX_ENABLED=true`로 📬 수신함 섹션 표시

#### 🔌 입력 및 스킬
- **첨부 파일 지원** — 텍스트 파일 자동 추가 (최대 5개, 각 200 KB); 이미지는 CDN URL로 전송 (최대 4 × 5 MB)
- **주문형 파일 전달** — Claude가 `.ccdb-attachments`에 경로 작성; 세션 완료 시 Discord 첨부 파일로 전송
- **스킬 실행** — 자동완성이 있는 `/skill` 명령; 설치된 플러그인 스킬 자동 검색
- **핫 리로드** — `~/.claude/skills/`에 추가된 새 스킬 자동 감지 (60초 갱신)

### 동시성 및 조율
- **Worktree 지침 자동 주입** — 모든 세션에 파일 건드리기 전 `git worktree` 사용 촉구
- **자동 worktree 정리** — 세션 종료 및 봇 시작 시 자동 삭제; 더티 worktree는 절대 자동 삭제 안 함
- **활성 세션 레지스트리** — 인메모리 레지스트리; 각 세션이 다른 세션 상태 파악
- **AI Lounge** — 공유 "휴게실" 채널; `--append-system-prompt`로 컨텍스트 주입 (기록에 누적 안 됨)
- **조율 채널** — `COORDINATION_CHANNEL_ID`가 AI Lounge 채널의 기본 폴백으로 사용

### 예약 작업
- **SchedulerCog** — SQLite 기반, 30초 마스터 루프
- **자기 등록** — Claude가 채팅 세션 중 `POST /api/tasks`로 작업 등록
- **코드 변경 불필요** — 런타임에 작업 추가, 제거, 수정
- **활성화/비활성화** — 삭제 없이 작업 일시 중지 (`PATCH /api/tasks/{id}`)

### CI/CD 자동화
- **Webhook 트리거** — GitHub Actions 또는 모든 CI/CD 시스템에서 Claude Code 작업 트리거
- **자동 업그레이드** — 업스트림 패키지 릴리스 시 봇 자동 업데이트
- **DrainAware 재시작** — 재시작 전 활성 세션 완료 대기
- **자동 재개 마킹** — 모든 종료 시 활성 세션 자동 마킹
- **수동 업그레이드 트리거** — `/upgrade` 슬래시 명령 (opt-in)

### 세션 관리
- **내장 도움말** — `/help`로 모든 슬래시 명령 표시 (에페메랄)
- **세션 동기화** — `/sync-sessions`으로 CLI 세션을 Discord 스레드로 가져오기
- **세션 목록** — 출처 및 시간 창으로 필터링 (`/sessions`)
- **세션 재개** — `/resume`으로 새 스레드에서 선택한 세션 재개
- **세션 지우기** — `/clear`로 현재 스레드의 세션 초기화
- **시작 재개** — 봇 재부팅 후 중단된 세션 자동 재개
- **프로그래밍 방식 생성** — `POST /api/spawn`으로 스크립트에서 새 스레드 + 세션 생성
- **Worktree 관리** — `/worktree-list` 및 `/worktree-cleanup`
- **런타임 모델 전환** — `/model-show` 및 `/model-set`, 재시작 없이
- **대화 되감기** — `/rewind`로 선택한 사용자 턴으로 세션 JSONL 자르기
- **대화 포크** — `/fork`으로 독립적인 세션 복사본으로 새 스레드 생성

### 보안
- **쉘 주입 없음** — `asyncio.create_subprocess_exec`만 사용, `shell=True` 절대 없음
- **세션 ID 유효성 검사** — `--resume`에 전달 전 엄격한 정규식 검사
- **플래그 주입 방지** — 모든 프롬프트 앞에 `--` 구분자
- **시크릿 격리** — 봇 토큰을 서브프로세스 환경에서 제거
- **사용자 인증** — `allowed_user_ids`로 Claude 호출 가능 사용자 제한
- **로그 주입 방지** — 로그 작성 전 사용자 제공 API 값 정화

---

## 빠른 시작 — 5분 안에 Discord에서 Claude 실행

**전제 조건:** Python 3.10+, 설치 및 인증된 [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code).

**플랫폼 지원:** 주로 **Linux**에서 개발 및 테스트됩니다. macOS와 Windows는 지원되고 CI를 통과하지만, 실제 테스트는 적습니다 — 버그 보고 환영.

### 1단계 — Discord 봇 생성 (일회성, 약 2분)

1. [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**으로 이동
2. **Bot**으로 이동 → Privileged Gateway Intents에서 **Message Content Intent** 활성화
3. 봇 **Token** 복사
4. **OAuth2 → URL Generator**: 범위 `bot` + `applications.commands`, 권한: Send Messages, Create Public Threads, Send Messages in Threads, Add Reactions, Manage Messages, Read Message History
5. 생성된 URL 열기 → 봇을 서버에 초대

### 2단계 — 설정 마법사 실행

클론이나 `.env` 편집 불필요 — 마법사가 모두 처리합니다:

```bash
# uvx 사용 (설치 불필요):
uvx --from "git+https://github.com/ebibibi/claude-code-discord-bridge.git" ccdb setup

# 또는 클론 후:
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv run ccdb setup
```

### 시작 / 중지

```bash
ccdb start    # 봇 시작 (현재 디렉토리의 .env 읽기)
ccdb start --env /path/to/.env   # 사용자 지정 .env 위치
```

설정된 채널에 메시지 전송 — Claude가 새 스레드에서 응답합니다.

### systemd 서비스로 실행 (프로덕션)

```bash
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service
journalctl -u mybot.service -f
```

### 커스텀 Cog (포크 없이 확장)

Python 파일을 디렉토리에 추가하는 것만으로 사용자 지정 기능 추가 — 포크, 서브클래스, 패키지 불필요:

```bash
ccdb start --cogs-dir ./my-cogs/
# 또는: CUSTOM_COGS_DIR=./my-cogs ccdb start
```

각 `.py` 파일은 `async def setup(bot, runner, components)`를 노출해야 합니다.

---

### 최소 봇 (패키지로 설치)

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
| `DISCORD_BOT_TOKEN` | Discord 봇 토큰 | (필수) |
| `DISCORD_CHANNEL_ID` | Claude 채팅 채널 ID | (필수) |
| `CCDB_BACKEND` | 사용할 CLI 백엔드: `claude` 또는 `codex` | `claude` |
| `CCDB_COMMAND` | CLI 바이너리 경로 또는 이름 (`CLAUDE_COMMAND` 재정의) | _(자동)_ |
| `CCDB_MODEL` | 사용할 모델 (`CLAUDE_MODEL` 재정의) | `sonnet` |
| `CCDB_PERMISSION_MODE` | CLI 권한 모드 (`CLAUDE_PERMISSION_MODE` 재정의) | `acceptEdits` |
| `CCDB_DANGEROUSLY_SKIP_PERMISSIONS` | 모든 권한 검사 건너뛰기 | `false` |
| `CCDB_WORKING_DIR` | CLI 작업 디렉토리 | 현재 디렉토리 |
| `CCDB_ALLOWED_TOOLS` | 허용 도구 쉼표 구분 목록 | (선택) |
| `CCDB_CHANNEL_IDS` | 멀티 채널 설정용 추가 채널 ID | (선택) |
| `CLAUDE_COMMAND` | Claude CLI 경로 (구버전 — `CCDB_COMMAND` 권장) | `claude` |
| `CLAUDE_MODEL` | 모델 (구버전 — `CCDB_MODEL` 권장) | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | 권한 모드 (구버전 — `CCDB_PERMISSION_MODE` 권장) | `acceptEdits` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | 권한 건너뛰기 (구버전) | `false` |
| `CLAUDE_WORKING_DIR` | 작업 디렉토리 (구버전) | 현재 디렉토리 |
| `MAX_CONCURRENT_SESSIONS` | 최대 병렬 세션 수 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 세션 비활성 타임아웃 | `300` |
| `DISCORD_OWNER_ID` | Claude가 입력 필요 시 @멘션할 사용자 ID | (선택) |
| `COORDINATION_CHANNEL_ID` | AI Lounge 채널의 기본 폴백 채널 ID | (선택) |
| `MENTION_ONLY_CHANNEL_IDS` | @멘션 시에만 응답하는 채널 ID (쉼표 구분) | (선택) |
| `INLINE_REPLY_CHANNEL_IDS` | 인라인 응답 채널 ID (쉼표 구분, 스레드 미생성) | (선택) |
| `CHAT_ONLY_CHANNEL_IDS` | 채팅 전용 모드 채널 ID (쉼표 구분) | (선택) |
| `WORKTREE_BASE_DIR` | 세션 worktree 스캔 기본 디렉토리 | (선택) |
| `CLI_SESSIONS_PATH` | CLI 세션 검색 경로 (`~/.claude/projects`) | (선택) |
| `CUSTOM_COGS_DIR` | 시작 시 로드할 커스텀 Cog 파일 디렉토리 | (선택) |
| `THREAD_INBOX_ENABLED` | 지속적인 스레드 수신함 활성화 | `false` |
| `THREAD_AUTO_RENAME` | Claude AI로 새 스레드 제목 자동 이름 변경 | `false` |
| `CCDB_CLI_ENV_FILE` | CLI 서브프로세스에 매번 병합할 `KEY=VALUE` 파일 경로 | (선택) |
| `CCDB_LOG_FILE` | 로그 파일 경로. 설정 시 기본 stdout 핸들러에 더해 순환 파일 핸들러(10 MB × 5 백업)가 추가됨. 모니터링 및 알림에 유용 | (선택) |
| `API_HOST` | REST API 바인드 주소 | `127.0.0.1` |
| `API_PORT` | REST API 포트 (설정 시 활성화) | (선택) |

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
| POST | `/api/tasks` | 주기적 Claude Code 작업 등록 |
| GET | `/api/tasks` | 등록된 작업 목록 |
| DELETE | `/api/tasks/{id}` | 작업 삭제 |
| PATCH | `/api/tasks/{id}` | 작업 업데이트 |
| POST | `/api/spawn` | 새 Discord 스레드 생성 및 Claude Code 세션 시작 (논블로킹) |
| POST | `/api/mark-resume` | 다음 봇 시작 시 자동 재개를 위해 스레드 마킹 |
| GET | `/api/lounge` | 최근 AI Lounge 메시지 읽기 |
| POST | `/api/lounge` | AI Lounge에 메시지 게시 |

---

## 아키텍처

```
claude_code_core/          # 백엔드 무관 공유 핵심 라이브러리
  backend.py               # SessionBackend 프로토콜 + create_backend() 팩토리
  codex_runner.py          # OpenAI Codex CLI 백엔드
  runner.py                # Claude CLI 서브프로세스 관리자
  parser.py                # stream-json 이벤트 파서
  types.py                 # SDK 메시지 타입 정의
claude_discord/
  main.py                  # 독립 실행 엔트리포인트
  cli.py                   # CLI 엔트리포인트 (ccdb setup/start)
  setup.py                 # setup_bridge()
  cogs/
    claude_chat.py         # 인터랙티브 채팅
    skill_command.py       # /skill 슬래시 명령
    session_manage.py      # 세션 관리
    scheduler.py           # 주기적 작업 실행기
    webhook_trigger.py     # Webhook → Claude Code 작업 실행
    auto_upgrade.py        # 자동 업그레이드 + 재시작
  ext/
    api_server.py          # REST API (선택)
examples/
  ebibot/                  # 실제 예시: 커스텀 Cog가 있는 개인 봇
```

### 설계 철학

- **CLI 스폰, API 아님** — 완전한 Claude Code 기능 획득, API 키 불필요, 토큰당 요금 없음
- **동시성 우선** — 여러 동시 세션이 예상 사례, 엣지 케이스 아님
- **Discord를 접착제로** — Discord가 UI, 스레딩, 반응, webhook, 지속적인 알림 제공
- **프레임워크, 애플리케이션 아님** — 패키지로 설치, 기존 봇에 Cog 추가
- **코드 없는 확장성** — 소스 변경 없이 예약 작업 및 webhook 트리거 추가
- **단순함으로 보안** — 약 8000줄의 감사 가능한 Python; subprocess exec만, 쉘 확장 없음

---

## 테스트

```bash
uv run pytest tests/ -v --cov=claude_discord
```

파서, 청커, 저장소, 러너, 스트리밍, webhook 트리거, 자동 업그레이드, REST API, AskUserQuestion UI, 스레드 대시보드, 예약 작업, 세션 동기화, AI Lounge, 시작 재개, 모델 전환, 압축 감지, TodoWrite 진행 embed, 커스텀 Cog 로더, SessionBackend 프로토콜, CodexRunner, 백엔드 팩토리를 커버하는 1365+ 테스트.

---

## 이 프로젝트의 구축 방법

**이 코드베이스는 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic의 AI 코딩 에이전트 — 가 [@ebibibi](https://github.com/ebibibi)의 지도 하에 개발했습니다. 인간 저자는 요구사항을 정의하고, PR을 리뷰하고, 모든 변경사항을 승인합니다 — Claude Code가 구현을 담당합니다.

프로젝트는 2026-02-18에 시작되었으며, Claude Code와의 반복적인 대화를 통해 계속 발전하고 있습니다.

---

## 실제 예시

**[`examples/ebibot/`](examples/ebibot/)** — 이 프레임워크 위에 구축된 개인 Discord 봇으로, 커스텀 Cog 로더를 시연합니다:

- **ReminderCog** — `/remind HH:MM "message"` 슬래시 명령 + 30초 전송 루프
- **WatchdogCog** — Todoist 기한 초과 작업 모니터
- **AutoUpgradeCog** — GitHub webhook + systemctl restart로 자가 업데이트
- **DocsSyncCog** — 푸시 시 webhook을 통해 문서 자동 번역
- **AlertResponderCog** — 범용 알림 모니터링 Cog

실행: `ccdb start --cogs-dir examples/ebibot/cogs/`

---

## 영감을 받은 프로젝트

- [OpenClaw](https://github.com/openclaw/openclaw) — 이모지 상태 반응, 메시지 디바운싱, fence 인식 청킹
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI 스폰 + stream-json 접근 방식
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — 권한 제어 패턴
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — 스레드별 대화 모델

---

## 라이선스

MIT
