> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **참고:** 이 문서는 원본 영어 문서의 자동 번역본입니다.
> 내용이 다를 경우 [영어 버전](../../README.md)이 우선합니다.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Discord를 통해 여러 Claude Code 세션을 안전하게 병렬로 실행하세요.**

각 Discord 스레드는 격리된 Claude Code 세션이 됩니다. 필요한 만큼 세션을 실행하세요: 한 스레드에서 기능을 개발하고, 다른 스레드에서 PR을 검토하고, 세 번째 스레드에서 예약된 작업을 실행합니다. 브리지가 자동으로 조율을 처리하므로 동시 세션이 서로 충돌하지 않습니다.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **면책 조항:** 이 프로젝트는 Anthropic과 관련이 없으며 Anthropic의 승인이나 공식 연결을 받지 않았습니다. "Claude"와 "Claude Code"는 Anthropic, PBC의 상표입니다. 이것은 Claude Code CLI와 인터페이스하는 독립적인 오픈 소스 도구입니다.

> **Claude Code로 완전히 구축되었습니다.** 이 전체 코드베이스—아키텍처, 구현, 테스트, 문서—는 Claude Code 자체에 의해 작성되었습니다. 인간 저자는 자연어로 요구사항과 방향을 제공했지만 소스 코드를 직접 읽거나 편집하지 않았습니다. [이 프로젝트가 구축된 방법](#이-프로젝트가-구축된-방법)을 참조하세요.

---

## 핵심 아이디어: 두려움 없는 병렬 세션

별도의 Discord 스레드에서 Claude Code에 작업을 보낼 때, 브리지는 자동으로 세 가지를 수행합니다:

1. **동시성 알림 주입** — 모든 세션의 시스템 프롬프트에 필수 지침이 포함됩니다: git worktree를 만들고, 그 안에서만 작업하고, 메인 작업 디렉토리를 직접 건드리지 마세요.

2. **활성 세션 레지스트리** — 각 실행 중인 세션은 다른 세션들에 대해 알고 있습니다. 두 세션이 같은 저장소를 수정하려 할 경우, 충돌 대신 조율할 수 있습니다.

3. **조율 채널** — 세션이 시작/종료 이벤트를 브로드캐스트하는 공유 Discord 채널. Claude와 사람 모두 모든 활성 스레드에서 일어나는 일을 한눈에 볼 수 있습니다.

```
스레드 A (기능)   ──→  Claude Code (worktree-A)
스레드 B (PR 검토) ──→  Claude Code (worktree-B)
스레드 C (문서)   ──→  Claude Code (worktree-C)
           ↓ 라이프사이클 이벤트
   #조율-채널
   "A: 인증 리팩토링 시작"
   "B: PR #42 검토 중"
   "C: README 업데이트 중"
```

경쟁 조건 없음. 작업 손실 없음. 병합 충돌 없음.

---

## 할 수 있는 것들

### 대화형 채팅 (모바일 / 데스크탑)

Discord가 실행되는 어디서든 Claude Code를 사용하세요—폰, 태블릿, 데스크탑. 각 메시지는 영속적인 Claude Code 세션과 1:1로 매핑되는 스레드를 만들거나 계속합니다.

### 병렬 개발

여러 스레드를 동시에 엽니다. 각각은 자체 컨텍스트, 작업 디렉토리, git worktree를 가진 독립적인 Claude Code 세션입니다. 유용한 패턴:

- **기능 + 검토 병렬**: 한 스레드에서 기능을 시작하는 동안 Claude가 다른 스레드에서 PR을 검토합니다.
- **여러 기여자**: 다른 팀원들이 각자 스레드를 가지고; 세션은 조율 채널을 통해 서로를 인식합니다.
- **안전하게 실험**: 스레드 A에서 방법을 시도하는 동안 스레드 B는 안정적인 코드를 유지합니다.

### 예약된 작업 (SchedulerCog)

Discord 대화 또는 REST API를 통해 주기적인 Claude Code 작업을 등록하세요—코드 변경 없이, 재배포 없이. 작업은 SQLite에 저장되고 구성 가능한 스케줄에 따라 실행됩니다. Claude는 세션 중에 `POST /api/tasks`를 사용하여 작업을 자체 등록할 수 있습니다.

```
/skill name:goodmorning         → 즉시 실행
Claude가 POST /api/tasks 호출  → 주기적 작업 등록
SchedulerCog (30초 마스터 루프) → 만료된 작업 자동 실행
```

### CI/CD 자동화

Discord 웹훅을 통해 GitHub Actions에서 Claude Code 작업을 트리거합니다. Claude는 자율적으로 실행됩니다—코드 읽기, 문서 업데이트, PR 생성, 자동 병합 활성화.

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**실제 예시:** `main`에 푸시할 때마다 Claude가 diff를 분석하고, 영어 + 일본어 문서를 업데이트하고, 이중 언어 요약으로 PR을 만들고, 자동 병합을 활성화합니다. 사람의 개입 없이.

### 세션 동기화

이미 Claude Code CLI를 직접 사용하고 있나요? `/sync-sessions`로 기존 터미널 세션을 Discord 스레드로 동기화하세요. 최근 대화 메시지를 백필하여 컨텍스트를 잃지 않고 폰에서 CLI 세션을 계속할 수 있습니다.

### 프로그래밍 방식 세션 생성

스크립트, GitHub Actions 또는 다른 Claude 세션에서 Discord 메시지 상호작용 없이 새 Claude Code 세션을 생성합니다.

```bash
# 다른 Claude 세션이나 CI 스크립트에서:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "저장소에 보안 스캔 실행", "thread_name": "보안 스캔"}'
# 스레드 ID와 함께 즉시 반환; Claude는 백그라운드에서 실행
```

Claude 서브프로세스는 `DISCORD_THREAD_ID`를 환경 변수로 받으므로, 실행 중인 세션이 자식 세션을 생성하여 작업을 병렬화할 수 있습니다.

### 시작 시 재개

봇이 세션 중에 재시작하면, 중단된 Claude 세션은 봇이 다시 온라인 상태가 될 때 자동으로 재개됩니다. 세션은 세 가지 방법으로 재개 표시됩니다:

- **자동 (업그레이드 재시작)** — `AutoUpgradeCog`가 패키지 업그레이드 재시작 직전에 모든 활성 세션의 스냅샷을 찍고 자동으로 표시합니다.
- **자동 (모든 종료)** — `ClaudeChatCog.cog_unload()`가 어떤 메커니즘으로든 봇이 종료될 때 (`systemctl stop`, `bot.close()`, SIGTERM 등) 모든 실행 중인 세션을 표시합니다.
- **수동** — 어떤 세션이든 `POST /api/mark-resume`을 직접 호출할 수 있습니다.

---

## 기능

### 대화형 채팅
- **Thread = Session** — Discord 스레드와 Claude Code 세션 간 1:1 매핑
- **실시간 상태** — 이모지 반응: 🧠 생각 중, 🛠️ 파일 읽기, 💻 편집, 🌐 웹 검색
- **스트리밍 텍스트** — Claude가 작업하는 동안 중간 어시스턴트 텍스트 표시
- **도구 결과 임베드** — 10초마다 증가하는 경과 시간과 함께 실시간 도구 호출 결과
- **확장 사고** — 추론이 스포일러 태그 임베드로 표시 (클릭하여 표시)
- **세션 지속성** — `--resume`을 통해 메시지 전반에 걸쳐 대화 재개
- **스킬 실행** — 자동완성, 선택적 인수, 스레드 내 재개를 지원하는 `/skill` 슬래시 명령
- **핫 리로드** — `~/.claude/skills/`에 추가된 새 스킬 자동으로 선택 (60초 새로 고침, 재시작 없음)
- **동시 세션** — 구성 가능한 한도로 여러 병렬 세션
- **지우지 않고 중지** — `/stop`으로 세션을 중지하면서 재개를 위해 보존
- **첨부파일 지원** — 텍스트 파일이 프롬프트에 자동으로 추가됨 (최대 5 × 50KB); 이미지는 `--image` 플래그를 통해 다운로드 및 전달 (최대 4 × 5MB)
- **시간 초과 알림** — 경과 시간과 재개 안내가 포함된 임베드
- **대화형 질문** — `AskUserQuestion`이 Discord 버튼 또는 선택 메뉴로 렌더링됨; 답변으로 세션 재개; 버튼은 봇 재시작 후에도 유지됨
- **Plan Mode** — Claude가 `ExitPlanMode`를 호출하면 Discord embed에 전체 계획과 승인/취소 버튼이 표시됨; 승인 후에만 Claude가 진행; 5분 타임아웃 시 자동 취소
- **도구 권한 요청** — Claude가 도구 실행 권한이 필요할 때 Discord에 도구 이름과 입력이 포함된 허용/거부 버튼 표시; 2분 후 자동 거부
- **MCP Elicitation** — MCP 서버가 Discord를 통해 사용자 입력을 요청할 수 있음 (폼 모드: JSON 스키마에서 최대 5개의 Modal 필드; URL 모드: URL 버튼 + 완료 확인); 5분 타임아웃
- **TodoWrite 실시간 진행상황** — Claude가 `TodoWrite`를 호출하면 단일 Discord embed가 게시되고 각 업데이트마다 in-place로 편집됨; ✅ 완료, 🔄 활성 (`activeForm` 레이블 포함), ⬜ 대기 중 표시
- **스레드 대시보드** — 활성 vs. 대기 스레드를 보여주는 실시간 고정 임베드; 입력이 필요할 때 소유자 @멘션
- **토큰 사용량** — 세션 완료 임베드에 캐시 히트율과 토큰 수 표시
- **컨텍스트 사용량** — 컨텍스트 윈도우 백분율 (입력 + 캐시 토큰, 출력 제외) 및 자동 압축까지 남은 용량이 세션 완료 embed에 표시됨; 83.5% 초과 시 ⚠️ 경고
- **압축 감지** — 컨텍스트 압축 발생 시 스레드에 알림 (트리거 유형 + 압축 전 토큰 수)
- **세션 중단** — 활성 스레드에 새 메시지를 보내면 실행 중인 세션에 SIGINT 전송 후 새 지시로 새로 시작; 수동 `/stop` 불필요
- **하드 정지 알림** — 30초 동안 활동이 없으면 (확장 사고 또는 컨텍스트 압축) 스레드에 메시지 전송; Claude가 재개하면 자동 초기화

### 동시성 & 조율
- **Worktree 지침 자동 주입** — 모든 파일을 건드리기 전에 `git worktree` 사용을 촉구하는 모든 세션
- **자동 worktree 정리** — 세션 worktree (`wt-{thread_id}`)는 세션 종료 시와 봇 시작 시 자동으로 제거됨; 더러운 worktree는 절대 자동으로 제거되지 않음 (안전 불변성)
- **활성 세션 레지스트리** — 인메모리 레지스트리; 각 세션은 다른 세션이 무엇을 하는지 볼 수 있음
- **AI Lounge** — 공유 «휴게실» 채널; `--append-system-prompt`를 통해 컨텍스트 주입 (일시적, 히스토리에 절대 누적되지 않음) 하여 긴 세션이 «Prompt is too long»에 도달하지 않도록 함; 세션이 의도를 게시하고, 서로의 상태를 읽으며, 파괴적 작업 전에 확인; 인간에게는 실시간 활동 피드로 보임
- **조율 채널** — 세션 간 라이프사이클 브로드캐스트를 위한 선택적 공유 채널
- **조율 스크립트** — Claude가 세션 내에서 `coord_post.py` / `coord_read.py`를 호출하여 이벤트를 게시하고 읽을 수 있음

### 예약된 작업
- **SchedulerCog** — 30초 마스터 루프를 가진 SQLite 기반 주기적 작업 실행기
- **자체 등록** — Claude가 채팅 세션 중에 `POST /api/tasks`를 통해 작업 등록
- **코드 변경 없음** — 런타임에 작업 추가, 제거 또는 수정
- **활성화/비활성화** — 삭제 없이 작업 일시 중지 (`PATCH /api/tasks/{id}`)

### CI/CD 자동화
- **Webhook 트리거** — GitHub Actions 또는 모든 CI/CD 시스템에서 Claude Code 작업 트리거
- **자동 업그레이드** — 업스트림 패키지 출시 시 봇 자동 업데이트
- **드레인 인식 재시작** — 재시작 전에 활성 세션이 완료될 때까지 대기
- **자동 재개 표시** — 활성 세션은 모든 종료 시 자동으로 재개 표시됨; 봇이 다시 온라인 상태가 된 후 중단된 곳에서 계속
- **재시작 승인** — 업그레이드 적용 전 선택적 확인 게이트

### 세션 관리
- **세션 동기화** — CLI 세션을 Discord 스레드로 가져오기 (`/sync-sessions`)
- **세션 목록** — 출처 (Discord / CLI / 전체)와 시간 범위로 필터링하는 `/sessions`
- **재개 정보** — `/resume-info`는 터미널에서 현재 세션을 계속하는 CLI 명령 표시
- **시작 시 재개** — 중단된 세션은 모든 봇 재시작 후 자동으로 재시작됨
- **프로그래밍 방식 생성** — `POST /api/spawn`이 어떤 스크립트나 Claude 서브프로세스에서도 새 Discord 스레드 + Claude 세션 생성
- **스레드 ID 주입** — `DISCORD_THREAD_ID` 환경 변수가 모든 Claude 서브프로세스에 전달됨
- **Worktree 관리** — `/worktree-list` 및 `/worktree-cleanup` 명령

### 보안
- **Shell 주입 없음** — `asyncio.create_subprocess_exec`만 사용, 절대 `shell=True` 없음
- **세션 ID 검증** — `--resume`에 전달하기 전 엄격한 정규식
- **플래그 주입 방지** — 모든 프롬프트 앞에 `--` 구분자
- **시크릿 격리** — 봇 토큰이 서브프로세스 환경에서 제거됨
- **사용자 인가** — `allowed_user_ids`가 Claude를 호출할 수 있는 사람 제한

---

## 빠른 시작

### 요구사항

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 설치 및 인증
- Message Content intent가 활성화된 Discord 봇 토큰
- [uv](https://docs.astral.sh/uv/) (권장) 또는 pip

### 독립형

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# 봇 토큰과 채널 ID로 .env 편집

uv run python -m claude_discord.main
```

### 패키지로 설치

이미 discord.py 봇이 있는 경우 (Discord는 토큰당 하나의 Gateway 연결만 허용):

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

`setup_bridge()`가 모든 Cog를 자동으로 연결합니다.

최신 버전으로 업데이트:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

## 설정

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `DISCORD_BOT_TOKEN` | Discord 봇 토큰 | (필수) |
| `DISCORD_CHANNEL_ID` | Claude 채팅 채널 ID | (필수) |
| `CLAUDE_COMMAND` | Claude Code CLI 경로 | `claude` |
| `CLAUDE_MODEL` | 사용할 모델 | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI 권한 모드 | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Claude 작업 디렉토리 | 현재 디렉토리 |
| `MAX_CONCURRENT_SESSIONS` | 최대 동시 세션 수 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 세션 비활성 시간 초과 | `300` |
| `DISCORD_OWNER_ID` | Claude가 입력이 필요할 때 @멘션할 사용자 ID | (선택) |
| `COORDINATION_CHANNEL_ID` | 세션 간 이벤트 브로드캐스트 채널 ID | (선택) |
| `CCDB_COORDINATION_CHANNEL_NAME` | 이름으로 조율 채널 자동 생성 | (선택) |
| `WORKTREE_BASE_DIR` | 세션 worktree 스캔 기본 디렉토리 (자동 정리 활성화) | (선택) |

---

## Discord 봇 설정

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 새 애플리케이션 만들기
2. 봇 만들기 및 토큰 복사
3. Privileged Gateway Intents에서 **Message Content Intent** 활성화
4. 다음 권한으로 봇 초대:
   - Send Messages, Create Public Threads, Send Messages in Threads
   - Add Reactions, Manage Messages, Read Message History

---

## 테스트

```bash
uv run pytest tests/ -v --cov=claude_discord
```

700+ 테스트가 파서, 분할기, 저장소, 러너, 스트리밍, 웹훅 트리거, 자동 업그레이드(`/upgrade` 슬래시 명령, 스레드 호출 및 승인 버튼 포함), REST API, AskUserQuestion UI, 스레드 대시보드, 예약 작업, 세션 동기화, AI Lounge, 시작 시 재개, 모델 전환, 압축 감지, TodoWrite 진행 embed, 권한/elicitation/plan-mode 이벤트 파싱을 커버합니다.

---

## 이 프로젝트가 구축된 방법

**이 전체 코드베이스는 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)**에 의해 작성되었습니다. 인간 저자 ([@ebibibi](https://github.com/ebibibi))는 자연어로 요구사항과 방향을 제공했지만 소스 코드를 직접 읽거나 편집하지 않았습니다.

이 프로젝트는 2026-02-18에 시작되었으며 Claude Code와의 반복적인 대화를 통해 계속 발전합니다.

---

## 실제 예시

**[EbiBot](https://github.com/ebibibi/discord-bot)** — 이 프레임워크를 기반으로 구축된 개인 Discord 봇. 자체 봇을 구축하기 위한 참고 자료로 활용하세요.

---

## 라이선스

MIT
