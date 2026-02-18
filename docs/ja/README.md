> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意:** これは英語のオリジナルドキュメントを自動翻訳したものです。
> 内容に相違がある場合は、[英語版](../../README.md)が優先されます。

# claude-code-discord-bridge

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

スマートフォンから [Claude Code](https://docs.anthropic.com/en/docs/claude-code) を使う。Discord スレッドを通じて **Claude Code CLI へのフルアクセス** を提供する薄いフロントエンド — ターミナルから離れているときのモバイル開発向けに設計されています。

**[English](../../README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免責事項:** このプロジェクトは Anthropic とは無関係であり、Anthropic による承認や公式な関係はありません。「Claude」および「Claude Code」は Anthropic, PBC の商標です。これは Claude Code CLI と連携する独立したオープンソースツールです。

> **Claude Code によって全て構築されました。** このプロジェクトは Anthropic の AI コーディングエージェントである Claude Code 自身によって設計・実装・テスト・ドキュメント化されました。人間の著者はソースコードを手動で読んでいません。詳細は[このプロジェクトの作り方](#このプロジェクトの作り方)をご覧ください。

## なぜこれが存在するのか

私は Claude Code を使って 3〜4 個のプロジェクトを並行して進めています。[Termux](https://termux.dev/) + tmux を使ってスマートフォンから操作していましたが、複数のターミナルセッションの管理が辛くなってきました — どの tmux ウィンドウがどのプロジェクトか？それぞれで何をしていたか？コンテキスト切り替えのオーバーヘッドが生産性を下げていました。

**Discord がこれを完璧に解決します:**

- 各プロジェクトの会話は**名前付きスレッド** — 一目でスキャンできる
- スレッドは全履歴を保持 — 数時間後に戻っても続きから再開できる
- 絵文字リアクションでステータスが一目でわかる — ターミナル出力をスクロールする必要なし
- Discord は無料で、あらゆるスマートフォンで動き、通知もネイティブに処理される

## これが何であるか（そして何でないか）

**これは:** Discord と Claude Code CLI の間に特化したブリッジです。`claude -p --output-format stream-json` をサブプロセスとして起動し、出力を解析して Discord に投稿します。それだけです。

**これではない:** 機能豊富な Discord Bot、AI チャットボットフレームワーク、Claude Code ターミナル体験の代替品。カスタム AI ロジック、プラグインシステム、管理ダッシュボードはありません。

**重い処理は Claude Code 環境が担います。** CLAUDE.md、スキル、ツール、メモリ、MCP サーバー — これらはすべてターミナルと全く同じように動作します。このブリッジは UI レイヤーを提供するだけです。

**セキュリティモデル:** 自分だけがアクセスできるチャンネルで、プライベートな Discord サーバーで実行してください。Bot は意図的にシンプルに設計されています — 機能が少ないほど攻撃面が少ない。自分でビルドすれば、全コードを読むことができ、外部に情報を送信するものは何もありません。

## 比較

| | claude-code-discord-bridge | [OpenClaw](https://github.com/openclaw/openclaw) & 類似 |
|---|---|---|
| **フォーカス** | モバイルファースト Claude Code アクセス | フル機能 Discord AI Bot |
| **AI バックエンド** | Claude Code CLI (subprocess) | 直接 API 呼び出し |
| **機能** | 最小限: スレッド、ステータス、チャンキング | 豊富: プラグイン、管理、マルチモデル |
| **設定** | 既存の Claude Code 設定 | Bot 固有の設定 |
| **スキル/ツール** | Claude Code から継承 | Bot 設定で定義 |
| **対象ユーザー** | すでに Claude Code を使っている開発者 | AI Discord Bot を求める人 |
| **複雑さ** | ~800 行の Python | 数千行 |

**Discord AI チャットボットが欲しい場合は**、OpenClaw や類似プロジェクトを使ってください — それらの方がはるかに機能豊富です。

**スマートフォンから Claude Code を使いたい場合**、既存のプロジェクトコンテキスト、スキル、ツールをすべて持って — それがこのためのものです。

## 機能

- **Thread = Session** — 各タスクが独自の Discord スレッドを持ち、Claude Code セッションと 1:1 でマッピング
- **リアルタイムステータス** — 絵文字リアクションで Claude が何をしているか表示 (🧠 考え中、🛠️ ファイル読み取り、💻 編集中、🌐 Web 検索)
- **ストリーミングテキスト** — Claude が作業中に中間テキストをリアルタイム表示（最後だけでなく）
- **ツール結果表示** — ツール使用の embed がその場で更新され、各ツールが返した内容を表示
- **拡張思考** — Claude の推論がスポイラー形式の embed で表示（クリックで展開）
- **セッション永続化** — `--resume` による複数メッセージをまたいだ会話継続
- **スキル実行** — スラッシュコマンドとオートコンプリートで Claude Code スキルを実行 (`/skill goodmorning`)
- **フェンス対応分割** — 長い応答をコードブロックを壊さずに自然な境界で分割
- **並行セッション** — 複数のセッションを並行実行（設定可能な上限）
- **セキュリティ強化** — シェルインジェクションなし、subprocess 環境からシークレットを除去、ユーザー認証

## 仕組み

```
あなた (Discord)  →  Bridge  →  Claude Code CLI
       ↑                                      ↓
       ←──────── stream-json 出力 ────────────←
```

1. 設定した Discord チャンネルにメッセージを送信
2. Bot がスレッドを作成して Claude Code セッションを開始
3. stream-json 出力をリアルタイムで解析してステータスを更新
4. Claude の応答をスレッドに投稿
5. スレッドに返信して会話を継続

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
# .env をボットトークンとチャンネル ID で編集

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
| `DISCORD_BOT_TOKEN` | Discord Bot トークン | (必須) |
| `DISCORD_CHANNEL_ID` | Claude チャット用チャンネル ID | (必須) |
| `CLAUDE_COMMAND` | Claude Code CLI へのパス | `claude` |
| `CLAUDE_MODEL` | 使用するモデル | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI のパーミッションモード | `acceptEdits` |
| `CLAUDE_WORKING_DIR` | Claude の作業ディレクトリ | カレントディレクトリ |
| `MAX_CONCURRENT_SESSIONS` | 最大並行セッション数 | `3` |
| `SESSION_TIMEOUT_SECONDS` | セッション非アクティブタイムアウト | `300` |

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

## アーキテクチャ

```
claude_discord/
  main.py                  # スタンドアロンエントリーポイント
  bot.py                   # Discord Bot クラス
  cogs/
    claude_chat.py         # メイン chat Cog（スレッド作成、メッセージ処理）
    skill_command.py       # /skill スラッシュコマンド（オートコンプリート付き）
    _run_helper.py         # 共有 Claude CLI 実行ロジック
  claude/
    runner.py              # Claude CLI subprocess マネージャー
    parser.py              # stream-json イベントパーサー
    types.py               # SDK メッセージの型定義
  database/
    models.py              # SQLite スキーマ
    repository.py          # セッション CRUD 操作
  discord_ui/
    status.py              # 絵文字リアクションステータスマネージャー（デバウンス付き）
    chunker.py             # フェンス対応メッセージ分割
    embeds.py              # Discord embed ビルダー
  utils/
    logger.py              # ロギング設定
```

### 設計思想

- **カスタム AI ロジックなし** — 推論、ツール使用、コンテキストはすべて Claude Code が処理
- **メモリシステムなし** — Claude Code の組み込みセッション + CLAUDE.md がメモリを担当
- **ツール定義なし** — Claude Code が独自の包括的なツールセットを持つ
- **プラグインシステムなし** — この Bot ではなく Claude Code を設定して機能を追加
- **フレームワークの仕事は純粋に UI** — メッセージを受け取り、ステータスを表示し、応答を届ける

### セキュリティ

- `asyncio.create_subprocess_exec`（シェルなし）でコマンドインジェクションを防止
- セッション ID は使用前に厳格な正規表現で検証
- `--` セパレーターでフラグ解釈によるプロンプトインジェクションを防止
- Bot トークンとシークレットを subprocess 環境から除去
- `allowed_user_ids` で Claude を呼び出せるユーザーを制限
- シンプルなコードベース（~800 LOC）— 自分で監査しやすい

## テスト

```bash
uv run pytest tests/ -v --cov=claude_discord
```

71 件のテストがパーサー、チャンカー、リポジトリ、ランナー、ストリーミング、run-helper ロジックをカバーしています。

## このプロジェクトの作り方

**このコードベース全体は [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic の AI コーディングエージェント — によって書かれました。人間の著者（[@ebibibi](https://github.com/ebibibi)）は自然言語で要件と方向性を提供しましたが、ソースコードを手動で読んだり編集したりしていません。

つまり:

- **すべてのコードは AI 生成** — アーキテクチャ、実装、テスト、ドキュメント
- **人間の著者はコードレベルでの正確性を保証できません** — 確信が必要な場合はソースを確認してください
- **バグレポートと PR を歓迎します** — Claude Code を使って対応することになるでしょう
- **これは AI が著したオープンソースソフトウェアの実世界の例** — Claude Code が何を構築できるかのリファレンスとして使ってください

このプロジェクトは 2026-02-18 の 1 日で、要件から始まり動作するテスト済みのドキュメント付きパッケージとして、Claude Code との反復的な会話を通じて構築されました。

## 実世界の例

**[EbiBot](https://github.com/ebibibi/discord-bot)** — claude-code-discord-bridge をパッケージ依存関係として使っている個人 Discord Bot。プッシュ通知、Todoist ウォッチドッグ、自動ドキュメント同期のカスタム Cog を含みます。このフレームワークの上に自分の Bot を構築する方法のリファレンスとして参照してください。

## インスパイアされたプロジェクト

- [OpenClaw](https://github.com/openclaw/openclaw) — 絵文字ステータスリアクション、メッセージデバウンシング、フェンス対応チャンキング
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI 起動 + stream-json アプローチ
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — パーミッション制御パターン
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — スレッドごとの会話モデル

## ライセンス

MIT
