> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **참고:** 이 문서는 영어 원본 문서의 자동 번역본입니다.
> 내용이 다를 경우 [영어 버전](../../README.md)이 우선합니다.

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[Claude Code](https://docs.anthropic.com/en/docs/claude-code)를 Discord와 GitHub에 연결합니다. **인터랙티브 채팅, CI/CD 자동화, GitHub 워크플로우 통합**을 위해 Claude Code CLI와 Discord를 브릿지하는 프레임워크입니다.

Claude Code는 터미널에서 훌륭하지만 — 더 많은 것이 가능합니다. 이 브릿지를 사용하면 **GitHub 개발 워크플로우에서 Claude Code를 활용**할 수 있습니다: 문서 자동 동기화, PR 리뷰 및 머지, GitHub Actions에서 트리거되는 모든 Claude Code 작업 실행. Discord를 범용 접착제로 사용합니다.

**[English](../../README.md)** | **[日本語](../ja/README.md)** | **[简体中文](../zh-CN/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **면책 조항:** 이 프로젝트는 Anthropic과 제휴하거나 승인받거나 공식적으로 연결되어 있지 않습니다. "Claude"와 "Claude Code"는 Anthropic, PBC의 상표입니다. 이것은 Claude Code CLI와 인터페이스하는 독립적인 오픈소스 도구입니다.

> **Claude Code로 완전히 구축되었습니다.** 이 프로젝트는 Anthropic의 AI 코딩 에이전트인 Claude Code 자체에 의해 설계, 구현, 테스트 및 문서화되었습니다. 인간 저자는 소스 코드를 읽지 않았습니다. 자세한 내용은 [이 프로젝트가 구축된 방법](#이-프로젝트가-구축된-방법)을 참조하세요.

## 두 가지 사용 방법

### 1. 인터랙티브 채팅 (모바일 / 데스크톱)

스마트폰이나 Discord가 있는 어떤 기기에서든 Claude Code를 사용하세요. 각 대화는 완전한 세션 지속성을 가진 스레드가 됩니다.

```
사용자 (Discord)  →  Bridge  →  Claude Code CLI
       ↑                                ↓
       ←──── stream-json 출력 ─────────←
```

### 2. CI/CD 자동화 (GitHub → Discord → Claude Code → GitHub)

Discord webhook을 통해 GitHub Actions에서 Claude Code 작업을 트리거합니다. Claude Code는 자율적으로 동작합니다 — 코드를 읽고, 문서를 업데이트하고, PR을 생성하고, 자동 머지를 활성화합니다.

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (자동 머지)  ←  git push  ←  Claude Code  ←──┘
```

**실제 사례:** main에 푸시할 때마다 Claude Code가 자동으로 변경 사항을 분석하고, 영어와 일본어 문서를 업데이트하고, 이중 언어 요약이 포함된 PR을 생성하고, 자동 머지를 활성화합니다. 사람의 개입이 필요 없습니다.

## 기능

### 인터랙티브 채팅
- **Thread = Session** — 각 작업이 고유한 Discord 스레드를 가지며, Claude Code 세션과 1:1 매핑
- **실시간 상태** — 이모지 리액션으로 Claude의 활동 표시 (🧠 생각 중, 🛠️ 파일 읽기, 💻 편집 중, 🌐 웹 검색)
- **스트리밍 텍스트** — Claude가 작업하는 동안 중간 텍스트가 실시간으로 표시
- **도구 결과 표시** — 도구 사용 결과가 실시간으로 embed로 표시
- **확장 사고** — Claude의 추론이 스포일러 태그 embed로 표시 (클릭하여 펼치기)
- **세션 지속성** — `--resume`을 통한 메시지 간 대화 계속
- **스킬 실행** — 슬래시 커맨드와 자동 완성으로 Claude Code 스킬 실행 (`/skill goodmorning`)
- **동시 세션** — 여러 세션을 병렬로 실행 (구성 가능한 제한)

### CI/CD 자동화
- **Webhook 트리거** — GitHub Actions 또는 모든 CI/CD 시스템에서 Claude Code 작업 트리거
- **자동 업그레이드** — 업스트림 패키지가 릴리스되면 Bot 자동 업데이트
- **REST API** — 외부 도구에서 Discord로 푸시 알림 (선택 사항, aiohttp 필요)

### 보안
- **Shell 주입 방지** — `asyncio.create_subprocess_exec`만 사용, `shell=True` 절대 사용 안 함
- **세션 ID 검증** — `--resume`에 전달하기 전 엄격한 정규식으로 검증
- **플래그 주입 방지** — 모든 프롬프트 앞에 `--` 구분자
- **시크릿 격리** — Bot 토큰과 시크릿을 서브프로세스 환경에서 제거
- **사용자 인증** — `allowed_user_ids`로 Claude를 호출할 수 있는 사용자 제한

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

이미 discord.py Bot을 실행 중인 경우 (Discord는 토큰당 하나의 Gateway 연결만 허용):

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

# 초기화
await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

# 기존 Bot에 추가
await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```

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
| `SESSION_TIMEOUT_SECONDS` | 세션 비활성 시간 초과 | `300` |

## 테스트

```bash
uv run pytest tests/ -v --cov=claude_discord
```

131개의 테스트가 파서, 청커, 리포지토리, 러너, 스트리밍, webhook 트리거, 자동 업그레이드 및 REST API를 커버합니다.

## 이 프로젝트가 구축된 방법

**이 전체 코드베이스는 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic의 AI 코딩 에이전트에 의해 작성되었습니다. 인간 저자([@ebibibi](https://github.com/ebibibi))는 자연어로 요구 사항과 방향을 제공했지만, 소스 코드를 직접 읽거나 편집하지 않았습니다.

이것은 다음을 의미합니다:

- **모든 코드가 AI 생성** — 아키텍처, 구현, 테스트, 문서
- **인간 저자는 코드 수준의 정확성을 보장할 수 없습니다** — 확인이 필요하면 소스를 검토하세요
- **버그 리포트와 PR을 환영합니다** — Claude Code가 이를 처리하는 데 사용될 것입니다
- **이것은 AI가 작성한 오픈소스 소프트웨어의 실제 사례입니다** — Claude Code가 무엇을 구축할 수 있는지의 참조로 사용하세요

이 프로젝트는 2026-02-18에 시작되어 Claude Code와의 반복적인 대화를 통해 계속 발전하고 있습니다.

## 실제 사례

**[EbiBot](https://github.com/ebibibi/discord-bot)** — claude-code-discord-bridge를 패키지 의존성으로 사용하는 개인 Discord Bot. 자동 문서 동기화 (영어 + 일본어), 푸시 알림, Todoist 감시, GitHub Actions CI/CD 통합을 포함합니다.

## 라이선스

MIT
