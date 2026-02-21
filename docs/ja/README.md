> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意:** これは英語のオリジナルドキュメントを自動翻訳したものです。
> 内容に相違がある場合は、[英語版](../../README.md)が優先されます。

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) を Discord と GitHub に接続するフレームワーク。**インタラクティブチャット、CI/CD 自動化、GitHub ワークフロー統合**のために Claude Code CLI と Discord をブリッジします。

Claude Code はターミナルでも素晴らしいですが、もっと多くのことができます。このブリッジを使えば、**GitHub の開発ワークフローで Claude Code を活用**できます：ドキュメントの自動同期、PR のレビューとマージ、GitHub Actions からトリガーされる任意の Claude Code タスクの実行。すべて Discord をユニバーサルな接着剤として使います。

**[English](../../README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免責事項:** このプロジェクトは Anthropic とは無関係であり、承認や公式な関係はありません。「Claude」および「Claude Code」は Anthropic, PBC の商標です。これは Claude Code CLI と連携する独立したオープンソースツールです。

> **Claude Code によって完全構築。** このプロジェクトは Anthropic の AI コーディングエージェントである Claude Code 自身によって設計・実装・テスト・ドキュメント化されました。人間の著者はソースコードを読んでいません。詳細は[このプロジェクトの構築方法](#このプロジェクトの構築方法)をご覧ください。

## 2つの使い方

### 1. インタラクティブチャット（モバイル / デスクトップ）

スマートフォンや Discord が使える任意のデバイスから Claude Code を利用。各会話はセッション永続化付きのスレッドになります。

```
あなた (Discord)  →  Bridge  →  Claude Code CLI
       ↑                                ↓
       ←──── stream-json 出力 ─────────←
```

### 2. CI/CD 自動化（GitHub → Discord → Claude Code → GitHub）

GitHub Actions から Discord webhook 経由で Claude Code タスクをトリガー。Claude Code は自律的に動作 — コードを読み、ドキュメントを更新し、PR を作成し、自動マージを有効化します。

```
GitHub Actions  →  Discord Webhook  →  Bridge  →  Claude Code CLI
                                                         ↓
GitHub PR (自動マージ)  ←  git push  ←  Claude Code  ←──┘
```

**実例:** main へのプッシュごとに、Claude Code が自動的に変更を分析し、英語と日本語のドキュメントを更新し、バイリンガルな要約付き PR を作成し、自動マージを有効化します。人間の介入は不要です。

## 機能

### インタラクティブチャット
- **Thread = Session** — 各タスクが独自の Discord スレッドを持ち、Claude Code セッションと 1:1 でマッピング
- **リアルタイムステータス** — 絵文字リアクションで Claude の状態を表示（🧠 思考中、🛠️ ファイル読み取り、💻 編集中、🌐 Web 検索）
- **ストリーミングテキスト** — Claude の作業中にテキストがリアルタイムで表示
- **ツール結果表示** — ツール使用結果がリアルタイムで embed として表示
- **ライブツールタイマー** — 実行中のツール embed が 10 秒ごとに経過時間を更新。認証フローやビルドなど長時間コマンドでも「Claude はまだ動いている」とわかる
- **拡張思考** — Claude の推論がスポイラータグ付き embed で表示（クリックで展開）
- **セッション永続化** — `--resume` による複数メッセージをまたいだ会話継続
- **スキル実行** — スラッシュコマンドとオートコンプリートで Claude Code スキルを実行（`/skill goodmorning`）
- **並行セッション** — 複数セッションを並列実行（設定可能な上限）
- **インタラクティブな質問** — Claude が `AskUserQuestion` を呼び出すと、Discord ボタンまたは Select Menu を表示し、回答を受け取ってセッションを再開
- **セッションステータスダッシュボード** — メインチャンネルにピン留めされた live embed で各スレッドの状態（処理中 / 入力待ち）を一覧表示。Claude が返答を待っているときはオーナーを @mention で通知
- **マルチセッション協調** — `COORDINATION_CHANNEL_ID` を設定すると、各セッションの開始・終了イベントを共有チャンネルにブロードキャストし、並行セッション同士がお互いの状況を把握できる

### CI/CD 自動化
- **Webhook トリガー** — GitHub Actions や任意の CI/CD システムから Claude Code タスクをトリガー
- **自動アップグレード** — 上流パッケージがリリースされたときに Bot を自動更新
- **REST API** — 外部ツールから Discord へのプッシュ通知（オプション、aiohttp が必要）

### セキュリティ
- **シェルインジェクション防止** — `asyncio.create_subprocess_exec` のみ使用、`shell=True` は一切なし
- **セッション ID 検証** — `--resume` に渡す前に厳格な正規表現で検証
- **フラグインジェクション防止** — すべてのプロンプト前に `--` セパレーター
- **シークレット分離** — Bot トークンとシークレットを subprocess 環境から除去
- **ユーザー認証** — `allowed_user_ids` で Claude を呼び出せるユーザーを制限

## クイックスタート

### 必要条件

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) のインストールと認証
- Message Content intent が有効な Discord Bot トークン
- [uv](https://docs.astral.sh/uv/)（推奨）または pip

### スタンドアロンで実行

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# .env を Bot トークンとチャンネル ID で編集

uv run python -m claude_discord.main
```

### パッケージとしてインストール

すでに discord.py Bot を動かしている場合（Discord はトークンごとに 1 つの Gateway 接続しか許可しません）:

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

```python
from claude_discord import ClaudeChatCog, ClaudeRunner, SessionRepository
from claude_discord.database.models import init_db

# 初期化
await init_db("data/sessions.db")
repo = SessionRepository("data/sessions.db")
runner = ClaudeRunner(command="claude", model="sonnet")

# 既存の Bot に追加
await bot.add_cog(ClaudeChatCog(bot, repo, runner))
```

最新版へのアップデート:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

## 設定

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `DISCORD_BOT_TOKEN` | Discord Bot トークン | （必須） |
| `DISCORD_CHANNEL_ID` | Claude チャット用チャンネル ID | （必須） |
| `CLAUDE_COMMAND` | Claude Code CLI へのパス | `claude` |
| `CLAUDE_MODEL` | 使用するモデル | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI のパーミッションモード | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Claude の作業ディレクトリ | カレントディレクトリ |
| `MAX_CONCURRENT_SESSIONS` | 最大並行セッション数 | `3` |
| `SESSION_TIMEOUT_SECONDS` | セッション非アクティブタイムアウト | `300` |
| `DISCORD_OWNER_ID` | Claude が入力待ちのとき @mention する Discord ユーザー ID | （オプション） |
| `COORDINATION_CHANNEL_ID` | マルチセッション協調ブロードキャスト用チャンネル ID | （オプション） |

## Discord Bot のセットアップ

1. [Discord Developer Portal](https://discord.com/developers/applications) で新しいアプリケーションを作成
2. Bot を作成してトークンをコピー
3. Privileged Gateway Intents で **Message Content Intent** を有効化
4. 以下の権限で Bot をサーバーに招待:
   - Send Messages（メッセージ送信）
   - Create Public Threads（パブリックスレッド作成）
   - Send Messages in Threads（スレッドでのメッセージ送信）
   - Add Reactions（リアクション追加）
   - Manage Messages（リアクション削除のため）
   - Read Message History（メッセージ履歴の読み取り）

## GitHub + Claude Code 自動化

Webhook トリガーシステムにより、Claude Code がインテリジェントエージェントとして動作する完全自律型 CI/CD ワークフローを構築できます — スクリプトを実行するだけでなく、コード変更を理解して判断を下します。

### 例: 自動ドキュメント同期

main へのプッシュごとに Claude Code が:
1. 最新の変更をプルして diff を分析
2. ソースコードが変更されていれば英語ドキュメントを更新
3. 日本語（または任意の対象言語）に翻訳
4. バイリンガルな要約付き PR を作成
5. 自動マージを有効化 — CI 通過後に PR が自動マージ

**GitHub Actions ワークフロー:**

```yaml
# .github/workflows/docs-sync.yml
name: Documentation Sync
on:
  push:
    branches: [main]
jobs:
  trigger:
    # docs-sync 自身のコミットをスキップ（無限ループ防止）
    if: "!contains(github.event.head_commit.message, '[docs-sync]')"
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \
            -H "Content-Type: application/json" \
            -d '{"content": "🔄 docs-sync"}'
```

**Bot の設定:**

```python
from claude_discord import WebhookTriggerCog, WebhookTrigger, ClaudeRunner

runner = ClaudeRunner(command="claude", model="sonnet")

triggers = {
    "🔄 docs-sync": WebhookTrigger(
        prompt="変更を分析し、ドキュメントを更新し、バイリンガルな要約付き PR を作成し、自動マージを有効化。",
        working_dir="/home/user/my-project",
        timeout=600,
    ),
    "🚀 deploy": WebhookTrigger(
        prompt="ステージング環境にデプロイ。",
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

**セキュリティ:** webhook メッセージのみ処理されます。より厳格な制御には `allowed_webhook_ids` オプションがあります。プロンプトはサーバー側で定義 — webhook はどのトリガーを発火するかを選択するだけです。

### 例: オーナー PR の自動承認

CI 通過後に自分の PR を自動承認・自動マージ:

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

## 自動アップグレード

上流パッケージがリリースされたときに Bot を自動アップグレード。

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

**パイプライン:** 上流プッシュ → CI webhook → `🔄 bot-upgrade` → `uv lock --upgrade-package` → `uv sync` → サービス再起動。

### グレースフルドレイン（DrainAware）

再起動前に、AutoUpgradeCog はすべてのアクティブセッションの完了を待ちます。`active_count` プロパティを持つ Cog（`DrainAware` プロトコルを満たす）は自動的に検出されます — 手動で `drain_check` ラムダを渡す必要はありません。

組み込みの DrainAware Cog: `ClaudeChatCog`、`WebhookTriggerCog`。

独自の Cog をドレイン対応にするには、`active_count` プロパティを追加するだけです:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

明示的な `drain_check` コーラブルを渡すことで、自動検出を上書きすることもできます。

### 再起動承認

自己更新シナリオ（Bot 自身の Discord セッションから更新する場合など）では、`restart_approval` を有効にして自動再起動を防止できます:

```python
config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,
)
```

`restart_approval=True` にすると、パッケージ更新後に承認を求めるメッセージが投稿されます。✅ でリアクションすると再起動が実行されます。承認されるまで定期的にリマインダーが送信されます。

## REST API

外部ツールから Discord へのプッシュ通知のためのオプション REST API。aiohttp が必要:

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
    api_secret="your-secret-token",  # オプションの Bearer 認証
)
await api.start()
```

### エンドポイント

| メソッド | パス | 説明 |
|----------|------|------|
| GET | `/api/health` | ヘルスチェック |
| POST | `/api/notify` | 即時通知の送信 |
| POST | `/api/schedule` | 後で通知をスケジュール |
| GET | `/api/scheduled` | 保留中の通知一覧 |
| DELETE | `/api/scheduled/{id}` | スケジュール済み通知のキャンセル |

### 使用例

```bash
# ヘルスチェック
curl http://localhost:8080/api/health

# 通知の送信
curl -X POST http://localhost:8080/api/notify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token" \
  -d '{"message": "ビルド成功！", "title": "CI/CD"}'

# 通知のスケジュール
curl -X POST http://localhost:8080/api/schedule \
  -H "Content-Type: application/json" \
  -d '{"message": "PR をレビューする時間です", "scheduled_at": "2026-01-01T09:00:00"}'
```

## アーキテクチャ

```
claude_discord/
  main.py                  # スタンドアロンエントリーポイント
  bot.py                   # Discord Bot クラス
  cogs/
    claude_chat.py         # インタラクティブチャット（スレッド作成、メッセージ処理）
    skill_command.py       # /skill スラッシュコマンド（オートコンプリート付き）
    webhook_trigger.py     # Webhook → Claude Code タスク実行（CI/CD）
    auto_upgrade.py        # Webhook → パッケージアップグレード + 再起動
    event_processor.py     # EventProcessor — stream-json イベントのステートマシン
    run_config.py          # RunConfig データクラス — CLI 実行パラメーターをまとめる
    _run_helper.py         # 薄いオーケストレーション層（run_claude_with_config + 後方互換 shim）
  claude/
    runner.py              # Claude CLI subprocess マネージャー
    parser.py              # stream-json イベントパーサー
    types.py               # SDK メッセージの型定義
  database/
    models.py              # SQLite スキーマ
    repository.py          # セッション CRUD 操作
    notification_repo.py   # スケジュール通知 CRUD
    task_repo.py           # スケジュールタスク CRUD
    ask_repo.py            # 保留中 AskUserQuestion CRUD
    settings_repo.py       # ギルドごとの設定
  coordination/
    service.py             # CoordinationService — セッションライフサイクルイベントを共有チャンネルに投稿
  discord_ui/
    status.py              # 絵文字リアクションステータスマネージャー（デバウンス付き）
    chunker.py             # フェンス・テーブル対応メッセージ分割
    embeds.py              # Discord embed ビルダー
    ask_view.py            # AskUserQuestion 用 Discord ボタン / Select Menu
    ask_handler.py         # collect_ask_answers() — AskUserQuestion UI + DB ライフサイクル
    streaming_manager.py   # StreamingMessageManager — デバウンス付きインプレース編集
    tool_timer.py          # LiveToolTimer — 長時間ツール実行の経過時間カウンター
    thread_dashboard.py    # スレッドごとのセッション状態を表示する live ピン留め embed
  ext/
    api_server.py          # REST API サーバー（オプション、aiohttp が必要）
  utils/
    logger.py              # ロギング設定
```

### 設計思想

- **CLI スポーン、API ではない** — `claude -p --output-format stream-json` を呼び出し、Claude Code の全機能（CLAUDE.md、スキル、ツール、メモリ）を無料で利用
- **Discord を接着剤として** — Discord が UI、スレッディング、通知、webhook インフラを提供
- **フレームワーク、アプリケーションではない** — パッケージとしてインストールし、既存の Bot に Cog を追加、コードで設定
- **シンプルさによるセキュリティ** — 約 2500 行の監査可能な Python、シェル実行なし、任意のコードパスなし

## テスト

```bash
uv run pytest tests/ -v --cov=claude_discord
```

400 件以上のテストがパーサー、チャンカー、リポジトリ、ランナー、ストリーミング、webhook トリガー、自動アップグレード、REST API、AskUserQuestion UI、スレッドステータスダッシュボードをカバーしています。

## このプロジェクトの構築方法

**このコードベース全体は [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic の AI コーディングエージェント — によって書かれました。人間の著者（[@ebibibi](https://github.com/ebibibi)）は自然言語で要件と方向性を提供しましたが、ソースコードを手動で読んだり編集したりしていません。

つまり:

- **すべてのコードは AI 生成** — アーキテクチャ、実装、テスト、ドキュメント
- **人間の著者はコードレベルでの正確性を保証できません** — 確信が必要な場合はソースを確認してください
- **バグレポートと PR を歓迎します** — Claude Code を使って対応することになるでしょう
- **これは AI が著したオープンソースソフトウェアの実例です** — Claude Code が何を構築できるかのリファレンスとして

このプロジェクトは 2026-02-18 に開始され、Claude Code との反復的な会話を通じて進化し続けています。

## 実例

**[EbiBot](https://github.com/ebibibi/discord-bot)** — claude-code-discord-bridge をパッケージ依存関係として使用する個人 Discord Bot。自動ドキュメント同期（英語 + 日本語）、プッシュ通知、Todoist ウォッチドッグ、GitHub Actions との CI/CD 統合を含みます。このフレームワーク上に自分の Bot を構築する際のリファレンスとしてご利用ください。

## インスパイアされたプロジェクト

- [OpenClaw](https://github.com/openclaw/openclaw) — 絵文字ステータスリアクション、メッセージデバウンシング、フェンス対応チャンキング
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI スポーン + stream-json アプローチ
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — パーミッション制御パターン
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — スレッドごとの会話モデル

## ライセンス

MIT
