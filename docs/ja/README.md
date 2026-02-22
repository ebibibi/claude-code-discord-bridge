> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意:** これは英語のオリジナルドキュメントを自動翻訳したものです。
> 内容に相違がある場合は、[英語版](../../README.md)が優先されます。

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**複数の Claude Code セッションを安全に Discord 経由で並列実行するフレームワーク。**

各 Discord スレッドが独立した Claude Code セッションになります。必要なだけスレッドを立ち上げ、あるスレッドで機能開発、別のスレッドで PR レビュー、さらに別のスレッドでスケジュールタスクを実行できます。並行セッションの調整はブリッジが自動的に処理します。

**[English](../../README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免責事項:** このプロジェクトは Anthropic とは無関係であり、承認や公式な関係はありません。「Claude」および「Claude Code」は Anthropic, PBC の商標です。これは Claude Code CLI と連携する独立したオープンソースツールです。

> **Claude Code によって完全構築。** このコードベース全体（アーキテクチャ、実装、テスト、ドキュメント）は Claude Code 自身によって書かれました。人間の著者は自然言語で要件と方向性を提供しましたが、ソースコードを手動で編集していません。詳細は[このプロジェクトの構築方法](#このプロジェクトの構築方法)をご覧ください。

---

## 基本的なアイデア: 競合なしの並行セッション

複数の Discord スレッドで Claude Code にタスクを送ると、ブリッジは自動的に 4 つのことを行います:

1. **並行処理指示の自動注入** — すべてのセッションのシステムプロンプトに必須指示を含めます: git worktree を作成し、その中だけで作業し、メイン作業ディレクトリに直接触れないこと。

2. **アクティブセッションレジストリ** — 実行中の各セッションは他のセッションの存在を把握します。2 つのセッションが同じリポジトリを触ろうとした場合、競合ではなく協調できます。

3. **協調チャンネル** — セッションの開始/終了イベントをブロードキャストする共有 Discord チャンネル。Claude と人間の両方が、すべてのアクティブスレッドで何が起きているかを一目で確認できます。

4. **AI Lounge** — すべてのセッションのプロンプトに注入される「控え室」チャンネル。作業を始める前に他のセッションのメッセージを読んで状況を把握し、破壊的な操作（force push、Bot 再起動、DB 操作など）の前には必ずラウンジを確認します。

```
スレッド A (機能開発)    ──→  Claude Code (worktree-A)  ─┐
スレッド B (PR レビュー)  ──→  Claude Code (worktree-B)   ├─→  #ai-lounge
スレッド C (ドキュメント) ──→  Claude Code (worktree-C)  ─┘    "A: auth リファクタリング中"
              ↓ ライフサイクルイベント                          "B: PR #42 レビュー完了"
     #coordination チャンネル                                   "C: README 更新中"
     "A: auth リファクタリング開始"
     "B: PR #42 レビュー中"
     "C: README 更新中"
```

競合なし。作業の損失なし。マージの驚きなし。

---

## できること

### インタラクティブチャット（モバイル / デスクトップ）

Discord が動く場所ならどこでも Claude Code を使用 — スマートフォン、タブレット、デスクトップ。各メッセージがスレッドを作成または継続し、永続的な Claude Code セッションと 1:1 でマッピングされます。

### 並行開発

複数のスレッドを同時に開きます。各スレッドは独自のコンテキスト、作業ディレクトリ、git worktree を持つ独立した Claude Code セッションです。よくある使い方:

- **機能開発 + レビューの並行**: あるスレッドで機能を開発しながら、別のスレッドで Claude が PR をレビュー。
- **複数の開発者**: チームメンバーそれぞれが自分のスレッドを持ち、協調チャンネルでセッションが互いの状況を把握。
- **安全な実験**: スレッド A でアプローチを試しながら、スレッド B を安定したコードで維持。

### スケジュールタスク（SchedulerCog）

コード変更なし、再デプロイなしで、Discord の会話または REST API から定期的な Claude Code タスクを登録。タスクは SQLite に保存され、設定可能なスケジュールで実行されます。Claude はセッション中に `POST /api/tasks` で自己登録できます。

```
/skill name:goodmorning         → 即時実行
Claude が POST /api/tasks 呼び出し → 定期タスクを登録
SchedulerCog（30 秒マスターループ）  → 期限のタスクを自動実行
```

### CI/CD 自動化

GitHub Actions から Discord webhook 経由で Claude Code タスクをトリガー。Claude が自律的に動作 — コードを読み、ドキュメントを更新し、PR を作成し、自動マージを有効化します。

```
GitHub Actions → Discord Webhook → Bridge → Claude Code CLI
                                                  ↓
GitHub PR ←── git push ←── Claude Code ──────────┘
```

**実例:** main へのプッシュごとに、Claude が diff を分析し、英語・日本語ドキュメントを更新し、バイリンガル PR を作成し、自動マージを有効化します。人間の操作は不要。

### セッション同期

Claude Code CLI を直接使っている場合は `/sync-sessions` で既存のターミナルセッションを Discord スレッドに同期。最近の会話メッセージを補完するので、スマートフォンから CLI セッションの続きを開けます。

### AI Lounge

すべての並行セッションが互いに状況を伝え合える「控え室」チャンネルです。各 Claude セッションはシステムプロンプトにラウンジのコンテキストを自動的に受け取ります — 他のセッションからの最近のメッセージと、破壊的な操作前に確認するルールが含まれます。

```bash
# セッションは作業を始める前に意図を投稿します:
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "feature/oauth で auth リファクタリング開始 — worktree-A", "label": "機能開発"}'

# 最近のラウンジメッセージを確認（各セッションにも自動注入）:
curl "$CCDB_API_URL/api/lounge"
```

ラウンジチャンネルは人間が見るアクティビティフィードとしても機能します — Discord で開けば、すべてのアクティブな Claude セッションが今何をしているかを一目で確認できます。

### プログラム的なセッション作成

スクリプト、GitHub Actions、または他の Claude セッションから Discord のメッセージ操作なしで新しい Claude Code セッションを起動できます。

```bash
# 別の Claude セッションや CI スクリプトから:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "リポジトリのセキュリティスキャンを実行", "thread_name": "Security Scan"}'
# スレッド作成後すぐに返答し、Claude はバックグラウンドで実行
```

Claude のサブプロセスには `DISCORD_THREAD_ID` 環境変数が渡されるため、実行中のセッションから子セッションを起動して作業を並列化できます。

### スタートアップリジューム

Bot の再起動中にセッションが中断された場合、Bot が再起動したときに自動的に再開されます。リジューム登録の方法は 3 つあります:

- **自動（アップグレード再起動）** — `AutoUpgradeCog` がパッケージアップグレードによる再起動直前にアクティブなセッションをすべてスナップショットし、自動でリジューム登録します。
- **自動（任意のシャットダウン）** — `ClaudeChatCog.cog_unload()` が任意のシャットダウン方法（`systemctl stop`、`bot.close()`、SIGTERM 等）でも実行中のセッションを自動登録します。
- **手動** — `POST /api/mark-resume` を直接呼び出して登録することもできます。

---

## 機能

### インタラクティブチャット
- **Thread = Session** — Discord スレッドと Claude Code セッションの 1:1 マッピング
- **リアルタイムステータス** — 絵文字リアクション: 🧠 思考中、🛠️ ファイル読み取り、💻 編集中、🌐 Web 検索
- **ストリーミングテキスト** — Claude の作業中に中間テキストがリアルタイムで表示
- **ツール結果 embed** — ライブツール呼び出し結果（10 秒ごとに経過時間を更新）
- **拡張思考** — 推論をスポイラータグ付き embed で表示（クリックで展開）
- **セッション永続化** — `--resume` で複数メッセージをまたいだ会話を継続
- **スキル実行** — `/skill` コマンド（オートコンプリート付き）、オプション引数、スレッド内リジューム
- **ホットリロード** — `~/.claude/skills/` に追加した新スキルを自動検出（60 秒更新、再起動不要）
- **並行セッション** — 設定可能な上限での複数並行セッション
- **削除せず停止** — `/stop` でセッションを保持したまま停止し、リジューム可能
- **添付ファイル対応** — テキストファイルをプロンプトに自動追加（最大 5 ファイル × 50 KB）
- **タイムアウト通知** — 経過時間とリジューム手順付きの embed 表示
- **インタラクティブな質問** — `AskUserQuestion` を Discord ボタンまたは Select Menu でレンダリング。回答でセッション再開。ボタンは Bot 再起動後も有効
- **スレッドダッシュボード** — アクティブ/待機スレッドを表示するライブピン embed。入力が必要なときはオーナーを @mention
- **トークン使用量** — セッション完了 embed にキャッシュヒット率とトークン数を表示

### 並行処理と協調
- **Worktree 指示の自動注入** — すべてのセッションに `git worktree` を使うよう指示
- **Worktree の自動クリーンアップ** — セッション終了時および Bot 起動時に `wt-{thread_id}` ディレクトリを自動削除。未コミットの変更がある場合は絶対に削除しない（安全性保証）
- **アクティブセッションレジストリ** — インメモリレジストリ。各セッションが他のセッションの状況を把握
- **AI Lounge** — すべてのセッションプロンプトに注入される共有「控え室」チャンネル。セッションが意図を投稿し、互いのステータスを確認し、破壊的な操作前にチェックします。人間には live アクティビティフィードとして見えます
- **協調チャンネル** — セッション間のライフサイクルブロードキャスト用オプション共有チャンネル
- **協調スクリプト** — セッション内から `coord_post.py` / `coord_read.py` を呼び出してイベントを投稿・読み取り可能

### スケジュールタスク
- **SchedulerCog** — 30 秒マスターループを持つ SQLite バックエンドの定期タスク実行エンジン
- **自己登録** — チャットセッション中に `POST /api/tasks` でタスクを登録
- **コード変更不要** — ランタイムでタスクを追加・削除・変更
- **有効/無効切り替え** — 削除せずにタスクを一時停止（`PATCH /api/tasks/{id}`）

### CI/CD 自動化
- **Webhook トリガー** — GitHub Actions や任意の CI/CD システムから Claude Code タスクをトリガー
- **自動アップグレード** — 上流パッケージリリース時に Bot を自動更新
- **DrainAware 再起動** — 再起動前にアクティブセッションの完了を待機
- **自動リジューム登録** — アップグレード再起動（`AutoUpgradeCog`）または任意のシャットダウン（`ClaudeChatCog.cog_unload()`）でアクティブセッションを自動登録。Bot 再起動後に中断した作業を自動的に再開
- **再起動承認** — アップグレード適用前の確認ゲート（オプション）

### セッション管理
- **セッション同期** — CLI セッションを Discord スレッドにインポート（`/sync-sessions`）
- **セッション一覧** — 起動元（Discord / CLI / 全て）と時間範囲でフィルタリング（`/sessions`）
- **リジューム情報** — 現在のセッションをターミナルで継続する CLI コマンドを表示（`/resume-info`）
- **スタートアップリジューム** — 任意のBot 再起動後に中断セッションを自動再開。`AutoUpgradeCog`（アップグレード再起動）および `ClaudeChatCog.cog_unload()`（その他すべてのシャットダウン）が自動登録、または `POST /api/mark-resume` で手動登録
- **プログラム的スポーン** — `POST /api/spawn` でスクリプトや Claude サブプロセスから新しい Discord スレッド + Claude セッションを作成。スレッド作成後すぐに非ブロッキング 201 を返す
- **スレッド ID 注入** — すべての Claude サブプロセスに `DISCORD_THREAD_ID` 環境変数を渡し、セッションから `$CCDB_API_URL/api/spawn` で子セッションを起動可能
- **Worktree 管理** — `/worktree-list` でアクティブなセッション Worktree を clean/dirty ステータス付きで表示、`/worktree-cleanup` で孤立した clean な Worktree を削除（`dry_run` プレビューあり）

### セキュリティ
- **シェルインジェクション防止** — `asyncio.create_subprocess_exec` のみ使用、`shell=True` は一切なし
- **セッション ID 検証** — `--resume` に渡す前に厳格な正規表現で検証
- **フラグインジェクション防止** — すべてのプロンプト前に `--` セパレーター
- **シークレット分離** — Bot トークンを subprocess 環境から除去
- **ユーザー認証** — `allowed_user_ids` で Claude を呼び出せるユーザーを制限

---

## クイックスタート

### 必要条件

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) のインストールと認証
- Message Content Intent が有効な Discord Bot トークン
- [uv](https://docs.astral.sh/uv/)（推奨）または pip

### スタンドアロン

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge

cp .env.example .env
# .env を Bot トークンとチャンネル ID で編集

uv run python -m claude_discord.main
```

### パッケージとしてインストール

すでに discord.py Bot を動かしている場合（Discord はトークンごとに 1 Gateway 接続のみ許可）:

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

`setup_bridge()` はすべての Cog を自動的に配線します。ccdb に追加された新しい Cog はコード変更なしで含まれます。

最新版へのアップデート:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

---

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
| `COORDINATION_CHANNEL_ID` | セッション間イベントブロードキャスト用チャンネル ID | （オプション） |
| `CCDB_COORDINATION_CHANNEL_NAME` | 協調チャンネルを名前で自動作成 | （オプション） |
| `WORKTREE_BASE_DIR` | セッション Worktree のスキャン対象ディレクトリ（自動クリーンアップを有効化） | （オプション） |

---

## Discord Bot のセットアップ

1. [Discord Developer Portal](https://discord.com/developers/applications) で新しいアプリケーションを作成
2. Bot を作成してトークンをコピー
3. Privileged Gateway Intents で **Message Content Intent** を有効化
4. 以下の権限で Bot をサーバーに招待:
   - Send Messages
   - Create Public Threads
   - Send Messages in Threads
   - Add Reactions
   - Manage Messages（リアクション削除のため）
   - Read Message History

---

## GitHub + Claude Code 自動化

### 例: 自動ドキュメント同期

main へのプッシュごとに Claude Code が:
1. 最新の変更をプルして diff を分析
2. 英語ドキュメントを更新
3. 日本語（または任意の対象言語）に翻訳
4. バイリンガルな要約付き PR を作成
5. 自動マージを有効化 — CI 通過後に PR が自動マージ

**GitHub Actions:**

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
}

await bot.add_cog(WebhookTriggerCog(
    bot=bot,
    runner=runner,
    triggers=triggers,
    channel_ids={YOUR_CHANNEL_ID},
))
```

**セキュリティ:** プロンプトはサーバー側で定義。Webhook はどのトリガーを発火するかを選択するだけ — 任意のプロンプトインジェクションはなし。

### 例: オーナー PR の自動承認

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

## スケジュールタスク

コード変更なし、再デプロイなしで、ランタイムに定期的な Claude Code タスクを登録。

Discord セッション内から Claude がタスクを登録:

```bash
# Claude がセッション内で呼び出す:
curl -X POST "$CCDB_API_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "古い依存関係をチェックして見つかったら Issue を開く", "interval_seconds": 604800}'
```

または独自のスクリプトから登録:

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "週次セキュリティスキャン", "interval_seconds": 604800}'
```

30 秒マスターループが期限のタスクを検出し、Claude Code セッションを自動起動します。

---

## 自動アップグレード

新しいリリースが公開されたときに Bot を自動アップグレード:

```python
from claude_discord import AutoUpgradeCog, UpgradeConfig

config = UpgradeConfig(
    package_name="claude-code-discord-bridge",
    trigger_prefix="🔄 bot-upgrade",
    working_dir="/home/user/my-bot",
    restart_command=["sudo", "systemctl", "restart", "my-bot.service"],
    restart_approval=True,  # 再起動確認に ✅ リアクション
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

再起動前に `AutoUpgradeCog` は以下の手順を実行します:

1. **アクティブセッションのスナップショット** — `_active_runners` を持つ Cog からアクティブなスレッド ID を収集（duck-typed で自動検出）。
2. **ドレイン** — アクティブセッションが自然に完了するまで待機。
3. **リジューム登録** — アクティブなスレッド ID を保留リジュームテーブルに保存。次回起動時に「Bot が再起動しました。前の作業の続きを確認してください」プロンプトで自動再開。
4. **再起動** — 設定した再起動コマンドを実行。

`active_count` プロパティを持つ Cog は自動検出されてドレインされます:

```python
class MyCog(commands.Cog):
    @property
    def active_count(self) -> int:
        return len(self._running_tasks)
```

セッションのリジューム登録は完全にオプトイン方式です。`setup_bridge()` でセッション DB を初期化している場合（デフォルト）に有効になります。有効な場合、セッションは `--resume` の継続性を保ちながら再開されるため、Claude Code は中断した会話を正確に再開できます。

> **カバレッジ:** `AutoUpgradeCog` はアップグレードによる再起動を担当します。`systemctl stop`、`bot.close()`、SIGTERM など*その他すべて*のシャットダウンに対しては、`ClaudeChatCog.cog_unload()` が第二の自動セーフネットとして機能します。

---

## REST API

通知とタスク管理のためのオプション REST API。aiohttp が必要:

```bash
uv add "claude-code-discord-bridge[api]"
```

### エンドポイント

| メソッド | パス | 説明 |
|----------|------|------|
| GET | `/api/health` | ヘルスチェック |
| POST | `/api/notify` | 即時通知の送信 |
| POST | `/api/schedule` | 通知のスケジュール |
| GET | `/api/scheduled` | 保留中の通知一覧 |
| DELETE | `/api/scheduled/{id}` | スケジュール済み通知のキャンセル |
| POST | `/api/tasks` | 定期的な Claude Code タスクを登録 |
| GET | `/api/tasks` | 登録済みタスクの一覧 |
| DELETE | `/api/tasks/{id}` | タスクの削除 |
| PATCH | `/api/tasks/{id}` | タスクの更新（有効/無効、スケジュール変更） |
| POST | `/api/spawn` | 新しい Discord スレッドを作成し Claude Code セッションを起動（非ブロッキング） |
| POST | `/api/mark-resume` | 次回 Bot 起動時のスレッド自動リジュームを登録 |
| GET | `/api/lounge` | AI Lounge の最近のメッセージを取得 |
| POST | `/api/lounge` | AI Lounge にメッセージを投稿（`label` オプション） |

```bash
# 通知の送信
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "ビルド成功！", "title": "CI/CD"}'

# 定期タスクの登録
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "デイリースタンドアップ要約", "interval_seconds": 86400}'
```

---

## アーキテクチャ

```
claude_discord/
  main.py                  # スタンドアロンエントリーポイント
  setup.py                 # setup_bridge() — 1 行で Cog を配線
  bot.py                   # Discord Bot クラス
  concurrency.py           # Worktree 指示 + アクティブセッションレジストリ
  cogs/
    claude_chat.py         # インタラクティブチャット（スレッド作成、メッセージ処理）
    skill_command.py       # /skill スラッシュコマンド（オートコンプリート付き）
    session_manage.py      # /sessions, /sync-sessions, /resume-info
    scheduler.py           # 定期 Claude Code タスク実行エンジン
    webhook_trigger.py     # Webhook → Claude Code タスク実行（CI/CD）
    auto_upgrade.py        # Webhook → パッケージアップグレード + DrainAware 再起動
    event_processor.py     # EventProcessor — stream-json イベントのステートマシン
    run_config.py          # RunConfig データクラス — CLI 実行パラメーターをまとめる
    _run_helper.py         # 薄いオーケストレーション層（run_claude_with_config + shim）
  claude/
    runner.py              # Claude CLI subprocess マネージャー
    parser.py              # stream-json イベントパーサー
    types.py               # SDK メッセージの型定義
  coordination/
    service.py             # セッションライフサイクルイベントを共有チャンネルに投稿
  database/
    models.py              # SQLite スキーマ
    repository.py          # セッション CRUD
    task_repo.py           # スケジュールタスク CRUD
    ask_repo.py            # 保留中 AskUserQuestion CRUD
    notification_repo.py   # スケジュール通知 CRUD
    resume_repo.py         # スタートアップリジューム CRUD（Bot 再起動をまたいだ保留リジューム）
    settings_repo.py       # ギルドごとの設定
  discord_ui/
    status.py              # 絵文字リアクションステータスマネージャー（デバウンス付き）
    chunker.py             # フェンス・テーブル対応メッセージ分割
    embeds.py              # Discord embed ビルダー
    ask_view.py            # AskUserQuestion 用 Discord ボタン / Select Menu
    ask_handler.py         # collect_ask_answers() — AskUserQuestion UI + DB ライフサイクル
    streaming_manager.py   # StreamingMessageManager — デバウンス付きインプレース編集
    tool_timer.py          # LiveToolTimer — 長時間ツール実行の経過時間カウンター
    thread_dashboard.py    # スレッドのセッション状態を表示する live ピン embed
  session_sync.py          # CLI セッションの検出とインポート
  worktree.py              # WorktreeManager — git worktree の安全なライフサイクル管理（セッション終了・起動時のクリーンアップ）
  ext/
    api_server.py          # REST API サーバー（オプション、aiohttp が必要）
  utils/
    logger.py              # ロギング設定
```

### 設計思想

- **CLI スポーン、API ではない** — `claude -p --output-format stream-json` を呼び出し、Claude Code の全機能（CLAUDE.md、スキル、ツール、メモリ）を利用
- **並行処理ファースト** — 複数の同時セッションが例外ではなく期待値。すべてのセッションに worktree 指示を注入し、レジストリと協調チャンネルが残りを処理
- **Discord を接着剤として** — Discord が UI、スレッディング、リアクション、Webhook、永続的な通知を提供。カスタムフロントエンド不要
- **フレームワーク、アプリケーションではない** — パッケージとしてインストールし、既存の Bot に Cog を追加し、コードで設定
- **ゼロコード拡張性** — ソースを変更せずにスケジュールタスクと Webhook トリガーを追加
- **シンプルさによるセキュリティ** — 約 3000 行の監査可能な Python。subprocess exec のみ、シェル展開なし

---

## テスト

```bash
uv run pytest tests/ -v --cov=claude_discord
```

610 件以上のテストがパーサー、チャンカー、リポジトリ、ランナー、ストリーミング、Webhook トリガー、自動アップグレード、REST API、AskUserQuestion UI、スレッドダッシュボード、スケジュールタスク、セッション同期、AI Lounge、スタートアップリジュームをカバーしています。

---

## このプロジェクトの構築方法

**このコードベース全体は [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic の AI コーディングエージェント — によって書かれました。人間の著者（[@ebibibi](https://github.com/ebibibi)）は自然言語で要件と方向性を提供しましたが、ソースコードを手動で読んだり編集したりしていません。

つまり:

- **すべてのコードは AI 生成** — アーキテクチャ、実装、テスト、ドキュメント
- **人間の著者はコードレベルでの正確性を保証できません** — 確信が必要な場合はソースを確認してください
- **バグレポートと PR を歓迎します** — Claude Code を使って対応することになるでしょう
- **これは AI が著したオープンソースソフトウェアの実例です**

このプロジェクトは 2026-02-18 に開始され、Claude Code との反復的な会話を通じて進化し続けています。

---

## 実例

**[EbiBot](https://github.com/ebibibi/discord-bot)** — このフレームワーク上に構築された個人 Discord Bot。自動ドキュメント同期（英語 + 日本語）、プッシュ通知、Todoist ウォッチドッグ、スケジュールヘルスチェック、GitHub Actions CI/CD を含みます。自分の Bot を構築する際のリファレンスとしてご利用ください。

---

## インスパイアされたプロジェクト

- [OpenClaw](https://github.com/openclaw/openclaw) — 絵文字ステータスリアクション、メッセージデバウンシング、フェンス対応チャンキング
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI スポーン + stream-json アプローチ
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — パーミッション制御パターン
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — スレッドごとの会話モデル

---

## ライセンス

MIT
