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

3. **AI Lounge** — 모든 세션 프롬프트에 주입되는 공유 「대기실」 채널. 작업 시작 전 다른 세션의 메시지를 읽어 상황을 파악하고, 파괴적인 작업(force push, 봇 재시작 등) 전에 반드시 확인합니다.

```
스레드 A (기능)   ──→  Claude Code (worktree-A)  ─┐
스레드 B (PR 검토) ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
스레드 C (문서)   ──→  Claude Code (worktree-C)  ─┘    "A: 인증 리팩토링 중"
                                                         "B: PR #42 검토 완료"
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
- **여러 기여자**: 다른 팀원들이 각자 스레드를 가지고; 세션은 AI Lounge를 통해 서로를 인식합니다.
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

#### 🔗 세션 기본
- **Thread = Session** — Discord 스레드와 Claude Code 세션 간 1:1 매핑
- **세션 지속성** — `--resume`을 통해 메시지 전반에 걸쳐 대화 재개
- **동시 세션** — 구성 가능한 한도로 여러 병렬 세션
- **지우지 않고 중지** — `/stop`으로 세션을 중지하면서 재개를 위해 보존
- **세션 중단** — 활성 스레드에 새 메시지를 보내면 실행 중인 세션에 SIGINT 전송 후 새 지시로 새로 시작; 수동 `/stop` 불필요
- **스레드 자동 이름 변경** — `THREAD_AUTO_RENAME=true`일 때, 각 새 스레드가 첫 번째 메시지를 기반으로 Claude가 생성한 제목으로 자동 이름 변경됨 (백그라운드 작업, 세션 시작 지연 없음)

#### 📡 실시간 피드백
- **실시간 상태** — 이모지 반응: 🧠 생각 중, 🛠️ 파일 읽기, 💻 편집, 🌐 웹 검색
- **스트리밍 텍스트** — Claude가 작업하는 동안 중간 어시스턴트 텍스트 표시
- **도구 결과 임베드** — 10초마다 증가하는 경과 시간과 함께 실시간 도구 호출 결과; 한 줄 결과는 인라인으로 표시, 여러 줄 결과는 확장 버튼 뒤에 접혀서 표시
- **확장 사고** — 추론이 스포일러 태그 임베드로 표시 (클릭하여 표시)
- **스레드 대시보드** — 활성 vs. 대기 스레드를 보여주는 실시간 고정 임베드; 입력이 필요할 때 소유자 @멘션

#### 🤝 사람-AI 협업
- **대화형 질문** — `AskUserQuestion`이 Discord 버튼 또는 선택 메뉴로 렌더링됨; 답변으로 세션 재개; 버튼은 봇 재시작 후에도 유지됨
- **Plan Mode** — Claude가 `ExitPlanMode`를 호출하면 Discord embed에 전체 계획과 승인/취소 버튼이 표시됨; 승인 후에만 Claude가 진행; 5분 타임아웃 시 자동 취소
- **도구 권한 요청** — Claude가 도구 실행 권한이 필요할 때 Discord에 도구 이름과 입력이 포함된 허용/거부 버튼 표시; 2분 후 자동 거부
- **MCP Elicitation** — MCP 서버가 Discord를 통해 사용자 입력을 요청할 수 있음 (폼 모드: JSON 스키마에서 최대 5개의 Modal 필드; URL 모드: URL 버튼 + 완료 확인); 5분 타임아웃
- **TodoWrite 실시간 진행상황** — Claude가 `TodoWrite`를 호출하면 단일 Discord embed가 게시되고 각 업데이트마다 in-place로 편집됨; ✅ 완료, 🔄 활성 (`activeForm` 레이블 포함), ⬜ 대기 중 표시

#### 📊 관찰 가능성
- **토큰 사용량** — 세션 완료 임베드에 캐시 히트율과 토큰 수 표시
- **컨텍스트 사용량** — 컨텍스트 윈도우 백분율 (입력 + 캐시 토큰, 출력 제외) 및 자동 압축까지 남은 용량이 세션 완료 embed에 표시됨; 83.5% 초과 시 ⚠️ 경고
- **압축 감지** — 컨텍스트 압축 발생 시 스레드에 알림 (트리거 유형 + 압축 전 토큰 수)
- **하드 정지 알림** — 활동이 없으면 스레드에 메시지 전송 (확장 사고 또는 컨텍스트 압축); Claude가 재개하면 자동 초기화. 임계값은 모델에 따라 자동 조정: 표준 모델 30초, Opus 120초 (더 긴 사고 시간)
- **시간 초과 알림** — 경과 시간과 재개 안내가 포함된 임베드
- **스레드 수신함** — `THREAD_INBOX_ENABLED=true`일 때, 대시보드에 지속적인 📬 수신함 섹션이 표시됨; 각 세션 종료 후 Claude가 경량 `claude -p` 호출로 마지막 메시지를 `waiting`/`done`/`ambiguous`로 분류; 회신을 기다리는 스레드는 봇 재시작 후에도 유지되며 회신할 때까지 표시됨

#### 🔌 입력 및 스킬
- **첨부파일 지원** — 텍스트 파일이 프롬프트에 자동으로 추가됨 (최대 5 × 50KB); 이미지는 `--image` 플래그를 통해 다운로드 및 전달 (최대 4 × 5MB)
- **스킬 실행** — 자동완성, 선택적 인수, 스레드 내 재개를 지원하는 `/skill` 슬래시 명령
- **핫 리로드** — `~/.claude/skills/`에 추가된 새 스킬 자동으로 선택 (60초 새로 고침, 재시작 없음)

### 동시성 & 조율
- **Worktree 지침 자동 주입** — 모든 파일을 건드리기 전에 `git worktree` 사용을 촉구하는 모든 세션
- **자동 worktree 정리** — 세션 worktree (`wt-{thread_id}`)는 세션 종료 시와 봇 시작 시 자동으로 제거됨; 더러운 worktree는 절대 자동으로 제거되지 않음 (안전 불변성)
- **활성 세션 레지스트리** — 인메모리 레지스트리; 각 세션은 다른 세션이 무엇을 하는지 볼 수 있음
- **AI Lounge** — 공유 «휴게실» 채널; `--append-system-prompt`를 통해 컨텍스트 주입 (일시적, 히스토리에 절대 누적되지 않음) 하여 긴 세션이 «Prompt is too long»에 도달하지 않도록 함; 세션이 의도를 게시하고, 서로의 상태를 읽으며, 파괴적 작업 전에 확인; 인간에게는 실시간 활동 피드로 보임
- **조율 채널** — `COORDINATION_CHANNEL_ID` 환경 변수는 AI Lounge 채널의 기본 폴백으로 사용됨 (봇 측 라이프사이클 자동 알림은 제거됨)

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
- **세션 동기화** — CLI 세션을 Discord 스레드로 가져오기 (`/sync-sessions`); `/sync-settings`로 동기화 설정 (스레드 스타일, 시간 범위, 최소 결과 수) 확인 및 변경
- **세션 목록** — 출처 (Discord / CLI / 전체)와 시간 범위로 필터링하는 `/sessions`
- **세션 재개** — `/resume`는 최근 세션 (최대 25개) 선택 메뉴를 표시하고 선택한 세션을 새 스레드에서 재개; 모든 채널이나 스레드에서 사용 가능 — 항상 설정된 메인 채널에 새 스레드 생성
- **재개 정보** — `/resume-info`는 터미널에서 현재 세션을 계속하는 CLI 명령 표시 (스레드 전용)
- **세션 초기화** — `/clear`는 현재 스레드의 Claude Code 세션을 초기화하고 새 스레드를 만들지 않고 처음부터 시작
- **시작 시 재개** — 중단된 세션은 모든 봇 재시작 후 자동으로 재시작됨
- **프로그래밍 방식 생성** — `POST /api/spawn`이 어떤 스크립트나 Claude 서브프로세스에서도 새 Discord 스레드 + Claude 세션 생성
- **스레드 ID 주입** — `DISCORD_THREAD_ID` 환경 변수가 모든 Claude 서브프로세스에 전달됨
- **Worktree 관리** — `/worktree-list` 및 `/worktree-cleanup` 명령
- **대화 되감기** — `/rewind`는 Claude가 생성한 작업 파일을 보존하면서 대화 기록만 초기화; 확인 메시지에 되감기 시점의 컨텍스트 사용률이 표시되어 이유를 파악하기 쉬움
- **대화 포크** — `/fork`는 `--fork-session`을 사용해 현재 세션 상태에서 새 스레드를 생성; 원본 스레드에 영향 없이 다른 방향을 탐색 가능
- **컨텍스트 가시화** — `/context`는 시각적 진행 막대로 현재 컨텍스트 윈도우 사용률 표시; 83.5% 임계값에 가까워지면 ⚠️ 자동 압축 경고 표시
- **속도 제한 모니터링** — `/usage`는 Claude API 속도 제한 사용률을 퍼센트 막대와 각 제한 유형별 초기화까지 남은 시간과 함께 표시
- **내장 도움말** — `/help`는 사용 가능한 모든 슬래시 명령과 기본 사용법을 표시 (일시적, 호출자에게만 보임)
- **런타임 모델 전환** — `/model-show`는 현재 전역 모델과 스레드별 세션 모델 표시; `/model-set`은 재시작 없이 모든 새 세션의 모델 변경
- **런타임 도구 권한** — `/tools-show`는 현재 허용된 도구 표시; `/tools-set`은 도구 켜기/끄기 선택 메뉴 열기; `/tools-reset`은 `.env` 기본값으로 복원 — 모두 재시작 불필요

### 보안
- **Shell 주입 없음** — `asyncio.create_subprocess_exec`만 사용, 절대 `shell=True` 없음
- **세션 ID 검증** — `--resume`에 전달하기 전 엄격한 정규식
- **플래그 주입 방지** — 모든 프롬프트 앞에 `--` 구분자
- **시크릿 격리** — 봇 토큰이 서브프로세스 환경에서 제거됨
- **사용자 인가** — `allowed_user_ids`가 Claude를 호출할 수 있는 사람 제한
- **로그 주입 방지** — 사용자 제공 API 값은 로그에 기록하기 전에 정리됨 (개행 문자 및 ANSI 이스케이프 시퀀스 제거)

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

### systemd 서비스로 실행 (프로덕션)

프로덕션 환경에서는 systemd로 관리하면 부팅 시 자동 시작과 장애 시 자동 재시작이 가능합니다.

리포지토리에는 템플릿 파일 `discord-bot.service`와 `scripts/pre-start.sh`가 포함되어 있습니다. 복사 후 경로와 사용자명을 수정하세요:

```bash
# 1. 서비스 파일 편집 — /home/ebi와 User=ebi를 본인의 경로/사용자로 변경
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service

# 2. 활성화 및 시작
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service

# 3. 상태 확인
sudo systemctl status mybot.service
journalctl -u mybot.service -f
```

**`scripts/pre-start.sh` 동작** (봇 프로세스 시작 전 `ExecStartPre`로 실행):

1. **`git pull --ff-only`** — `origin main`에서 최신 코드 가져오기
2. **`uv sync`** — `uv.lock`에 따라 의존성 동기화
3. **임포트 검증** — `claude_discord.main`이 정상적으로 임포트되는지 확인
4. **자동 롤백** — 임포트 실패 시 이전 커밋으로 되돌리고 재시도. Discord webhook으로 성공/실패 알림 전송
5. **Worktree 정리** — 충돌된 세션이 남긴 git worktree 삭제

스크립트는 `readlink -f $0`을 통해 저장소 루트를 동적으로 감지하므로, 어느 사용자가 어디에 클론해도 스크립트 내 경로를 수정할 필요가 없습니다. `uv` 바이너리도 `PATH`에서 자동으로 찾습니다. 커스텀 경로가 필요하면 `CCDB_UV_BIN` 환경 변수로 지정하세요.

`.env`에 `DISCORD_WEBHOOK_URL`을 설정하면 장애 알림을 받을 수 있습니다 (선택사항).

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
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | 모든 권한 검사 건너뛰기 (주의하여 사용) | `false` |
| `CLAUDE_WORKING_DIR` | Claude 작업 디렉토리 | 현재 디렉토리 |
| `MAX_CONCURRENT_SESSIONS` | 최대 동시 세션 수 | `3` |
| `SESSION_TIMEOUT_SECONDS` | 세션 비활성 시간 초과 | `300` |
| `DISCORD_OWNER_ID` | Claude가 입력이 필요할 때 @멘션할 사용자 ID | (선택) |
| `COORDINATION_CHANNEL_ID` | AI Lounge 채널의 기본 폴백 채널 ID | (선택) |
| `WORKTREE_BASE_DIR` | 세션 worktree 스캔 기본 디렉토리 (자동 정리 활성화) | (선택) |
| `CLI_SESSIONS_PATH` | CLI 세션 탐색 경로 (`~/.claude/projects`), `/sync-sessions` 활성화에 필요 | (선택) |
| `MENTION_ONLY_CHANNEL_IDS` | 봇이 @멘션될 때만 응답하는 채널 ID (쉼표로 구분) | (선택) |
| `INLINE_REPLY_CHANNEL_IDS` | 인라인 답장 채널 ID (쉼표로 구분, 스레드 생성 없음) | (선택) |
| `THREAD_INBOX_ENABLED` | 지속적인 스레드 수신함 활성화 (`claude -p`로 세션을 `waiting`/`done`/`ambiguous`로 분류; 스레드 대시보드에 표시) | `false` |
| `THREAD_AUTO_RENAME` | Claude AI를 사용하여 새 스레드 제목 자동 이름 변경 — 백그라운드 `claude -p` 호출로 첫 번째 사용자 메시지에서 짧고 설명적인 제목 생성 (세션 시작 지연 없음) | `false` |

### 권한 모드 — `-p` 모드에서 작동하는 기능

ccdb를 통해 사용할 때 Claude Code CLI는 **`-p`(비대화형) 모드**로 실행됩니다. 이 모드에서 CLI는 **권한 확인을 요청할 수 없으며** — 승인이 필요한 도구는 즉시 거부됩니다. 이는 ccdb의 제한이 아니라 [CLI의 설계 제약](https://code.claude.com/docs/en/headless)입니다.

| 모드 | `-p` 모드에서의 동작 | 권장 |
|------|----------------------|----------------|
| `default` | ❌ **모든 도구 거부** — 사용 불가 | 사용하지 않음 |
| `acceptEdits` | ⚠️ Edit/Write 자동 승인, Bash 거부 (Claude가 파일 작업에 Write로 폴백) | 최소 동작 옵션 |
| `bypassPermissions` | ✅ 모든 도구 승인 | 작동하나, 아래 플래그 권장 |
| **`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`** | ✅ **모든 도구 승인** | **권장** — ccdb가 이미 `allowed_user_ids`로 접근 제한 |

**권장 설정:** `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`를 설정하세요. ccdb가 `allowed_user_ids`를 통해 Claude와의 상호작용을 제어하므로, CLI 수준의 권한 검사는 실질적인 보안 이점 없이 마찰만 추가합니다. 이름의 「dangerously」는 CLI의 범용 경고를 반영한 것이며, 접근이 이미 게이팅된 ccdb 컨텍스트에서는 실용적인 선택입니다.

**세밀한 제어를 위해** `CLAUDE_ALLOWED_TOOLS`를 사용하면 모든 권한을 우회하지 않고 특정 도구만 허용할 수 있습니다:

```env
# 예시: 파일 작업과 코드 실행은 허용하지만 웹 접근은 불허
CLAUDE_ALLOWED_TOOLS=Bash,Read,Write,Edit,Glob,Grep

# 예시: 읽기 전용 모드 — Claude가 탐색할 수 있지만 수정 불가
CLAUDE_ALLOWED_TOOLS=Read,Glob,Grep
```

주요 도구 이름: `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `NotebookEdit`. 이 기능 사용 시 `CLAUDE_PERMISSION_MODE=default`로 설정하세요 (다른 모드에서는 재정의될 수 있습니다).

> **Discord에 권한 버튼이 나타나지 않는 이유?** CLI의 `-p` 모드는 `permission_request` 이벤트를 발생시키지 않으므로 ccdb에 표시할 내용이 없습니다. 표시되는 `AskUserQuestion` 버튼(Claude의 선택 프롬프트)은 다른 메커니즘으로 정상 작동합니다. 자세한 조사는 [#210](https://github.com/ebibibi/claude-code-discord-bridge/issues/210)을 참조하세요.

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

1050+ 테스트가 파서, 분할기, 저장소, 러너, 스트리밍, 웹훅 트리거, 자동 업그레이드(`/upgrade` 슬래시 명령, 스레드 호출 및 승인 버튼 포함), REST API, AskUserQuestion UI, 스레드 대시보드, 예약 작업, 세션 동기화, AI Lounge, 시작 시 재개, 모델 전환, 압축 감지, TodoWrite 진행 embed, 권한/elicitation/plan-mode 이벤트 파싱을 커버합니다.

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
