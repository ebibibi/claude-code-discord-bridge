> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../README.md) takes precedence.
> **注意:** これは英語のオリジナルドキュメントを自動翻訳したものです。
> 内容に相違がある場合は、[英語版](../../README.md)が優先されます。

# Claude & Codex Discord Bridge

*パッケージ名: `claude-code-discord-bridge`（ケバブケース）*

[![CI](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml/badge.svg)](https://github.com/ebibibi/claude-code-discord-bridge/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**スマホの Discord から Claude Code _または_ OpenAI Codex をガンガン使おう。複数スレッドを同時に回して、本格開発もOK。**

Discord のスレッドを開くだけで、Claude Code または OpenAI Codex のセッションが立ち上がります。スマートフォンから何スレッドでも並行して動かせます — あるスレッドで機能開発、別のスレッドで PR レビュー、さらに別のスレッドでバックグラウンドタスク。スレッドごとにバックエンドを混在させながら、全部同時進行。コンフリクトしないように、ブリッジがセッション間の調整を完全自動化します。

**既存のサブスクリプションをそのまま活用。API キーの設定は不要。** ccdb は公式 CLI の上で動作します — Claude Code（[Claude Pro/Max サブスクリプション](https://claude.ai/pricing)に含まれる）と OpenAI Codex（[ChatGPT Plus/Pro/Business](https://chatgpt.com)に含まれる）。`/backend` でバックエンドを切り替えるか、スレッドごとに設定 — 予測可能なコストで Discord 経由で両方の AI を利用できます。

**[English](../../README.md)** | **[简体中文](../zh-CN/README.md)** | **[한국어](../ko/README.md)** | **[Español](../es/README.md)** | **[Português](../pt-BR/README.md)** | **[Français](../fr/README.md)**

> **免責事項:** このプロジェクトは Anthropic および OpenAI とは無関係であり、承認や公式な関係はありません。「Claude」および「Claude Code」は Anthropic, PBC の商標、「OpenAI」「Codex」「ChatGPT」は OpenAI の商標です。これは Claude Code CLI と OpenAI Codex CLI に連携する独立したオープンソースツールです。

> **Claude Code によって完全構築。** このコードベース全体（アーキテクチャ、実装、テスト、ドキュメント）は Claude Code 自身によって書かれました。人間の著者は自然言語で要件と方向性を提供しましたが、ソースコードを手動で編集していません。詳細は[このプロジェクトの構築方法](#このプロジェクトの構築方法)をご覧ください。

---

## 基本的なアイデア: 競合なしの並行セッション

複数の Discord スレッドで Claude Code または OpenAI Codex にタスクを送ると、ブリッジは自動的に 4 つのことを行います — どのバックエンドを選んでも同じです:

1. **並行処理指示の自動注入** — すべてのセッションのシステムプロンプトに必須指示を含めます: git worktree を作成し、その中だけで作業し、メイン作業ディレクトリに直接触れないこと。

2. **アクティブセッションレジストリ** — 実行中の各セッションは他のセッションの存在を把握します。2 つのセッションが同じリポジトリを触ろうとした場合、競合ではなく協調できます。

3. **AI Lounge** — すべてのセッションのプロンプトに注入される「控え室」チャンネル。作業を始める前に他のセッションのメッセージを読んで状況を把握し、これから触るリポジトリ・Issue・ファイルを宣言（[リソースクレーム](#リソースクレーム)を参照）することで、2 つ目のセッションが同じ作業を重複して始める前に弾かれます。破壊的な操作（force push、Bot 再起動、DB 操作など）の前には必ずラウンジを確認します。

4. **バックエンド非依存のサーフェス** — Discord UI、スラッシュコマンド、スケジューラー、API、Lounge は、スレッドが Claude で動いていても Codex で動いていても同じように機能します。スレッドごとにバックエンドを混在できます — 例: Claude でリファクタリング、Codex でコードレビュー — `/backend` でスレッド単位に設定。

```
スレッド A (機能開発)    ──→  Claude Code  (worktree-A)  ─┐
スレッド B (PR レビュー)  ──→  OpenAI Codex (worktree-B)   ├─→  #ai-lounge
スレッド C (ドキュメント) ──→  Claude Code  (worktree-C)  ─┘    "A: auth リファクタリング中"
                                                               "B: PR #42 レビュー完了 (codex)"
                                                               "C: README 更新中"
```

競合なし。作業の損失なし。マージの驚きなし。バックエンドの縛りなし。

---

## できること

### インタラクティブチャット（モバイル / デスクトップ）

Discord が動く場所ならどこでも Claude Code _または_ OpenAI Codex を使用 — スマートフォン、タブレット、デスクトップ。各メッセージがスレッドを作成または継続し、永続的な AI セッションと 1:1 でマッピングされます。`/backend claude` または `/backend codex` でいつでもバックエンドを切り替えられます — スレッドごとに設定するか、グローバルに新しいデフォルトとして設定。

### 並行開発

複数のスレッドを同時に開きます。各スレッドは独自のコンテキスト、作業ディレクトリ、git worktree を持つ独立した AI セッション（Claude Code または Codex）です。よくある使い方:

- **機能開発 + レビューの並行**: あるスレッドで Claude が機能を開発しながら、別のスレッドで Codex が PR をレビュー。
- **複数の開発者**: チームメンバーそれぞれが自分のスレッドを持ち（好みのバックエンドも選べる）、AI Lounge でセッションが互いの状況を把握。
- **安全な実験**: スレッド A でアプローチを試しながら、スレッド B を安定したコードで維持。
- **両 AI で同じプロンプトを A/B テスト**: 同じタスクで 2 つのスレッドを立ち上げ、一方を `/backend claude`、もう一方を `/backend codex` に設定し、diff を並べて比較。

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

すべての並行セッションが互いに状況を伝え合える「控え室」チャンネルです。各セッションはラウンジのコンテキストを、バックエンド固有の一時的なシステム／開発者指示（Claude は `--append-system-prompt`、Codex は `developer_instructions`）として自動的に受け取ります。会話履歴には含まれないためターンをまたいで蓄積されず、長時間のセッションで発生していた「Prompt is too long」エラーを防止します。注入されるコンテキストには、他のセッションからの最近のメッセージと、破壊的な操作前に確認するルールが含まれます。

```bash
# セッションは作業を始める前に意図を投稿します:
curl -X POST "$CCDB_API_URL/api/lounge" \
  -H "Content-Type: application/json" \
  -d '{"message": "feature/oauth で auth リファクタリング開始 — worktree-A", "label": "機能開発"}'

# 最近のラウンジメッセージを確認（各セッションにも自動注入）:
curl "$CCDB_API_URL/api/lounge"
```

ラウンジチャンネルは人間が見るアクティビティフィードとしても機能します — Discord で開けば、すべてのアクティブな Claude セッションが今何をしているかを一目で確認できます。

### クロスセッション可観測性

ラウンジのメモが伝えられるのは「他のスレッドが存在すること」だけです。この 2 つの読み取り専用エンドポイントを使えば、セッションは実際に見に行けます — 同じ作業を始めてしまった 2 つのセッションが、両方とも突き進む前に重複に気づけるようになります。

```bash
# 他に誰が動いていて、どこで作業していて、最後に何を宣言したか?
curl "$CCDB_API_URL/api/sessions?exclude_thread=$DISCORD_THREAD_ID"

# そのスレッドの実際の会話を読む
curl "$CCDB_API_URL/api/threads/1529338965000192110/messages?limit=30"
```

`/api/sessions` は 3 つの情報源をマージします: `sessions` テーブル（created_at、作業ディレクトリ、バックエンド）、インメモリレジストリ（各ライブセッションが*今まさに*何をしているか）、そして各スレッドの最新のラウンジメモです。ターンの実行中のセッションは `"state": "running"` として現れます — ラウンジに一度も投稿していないセッションも含まれ、まさにそういうときこそこの機能が効きます。セッション自身は Discord トークンを持たないため、読み取りは Bot が代行し、エンドポイントは localhost のコントロールプレーン上に留まります。

### リソースクレーム

可観測性が教えてくれるのは、衝突が*起きた*という事実です。クレーム（claim）はそれを未然に防ぎます — 読み取りも交渉も LLM の往復も不要です。セッションはこれから作業する対象を宣言し、同じ対象を要求した次のセッションは作業を始める前に拒否されます。

```bash
# 作業開始前に宣言する
curl -X POST "$CCDB_API_URL/api/claims" \
  -H "Content-Type: application/json" \
  -d '{"resource": "repo:ccdb#issue-123", "thread_id": "'$DISCORD_THREAD_ID'", "note": "パーサーを修正中"}'
# 201 {"status": "acquired", ...}

# 2 つ目のセッションが同じリソースを要求した場合:
# 409 {"status": "held", "claim": {"thread_id": ..., "note": "パーサーを修正中",
#      "holder_state": "running", "holder_thread_name": "..."}}

# 完了したら解放する
curl -X DELETE "$CCDB_API_URL/api/claims?resource=repo:ccdb%23issue-123&thread_id=$DISCORD_THREAD_ID"
```

クレームは**アドバイザリ（勧告的）な仕組み**です — git やファイルシステムのレベルで強制されるわけではありません — また、すべてのクレームに TTL（既定 2 時間、最大 24 時間）が付くため、セッションが異常終了してもリソースが永久に占有されることはありません。409 のレスポンスボディには保持者がまだ実行中かどうかが含まれるので、呼び出し側は「待つ」「別の作業をする」「`force=true` で奪い取る」のいずれかを判断できます。リソース名は自由形式で、正規化（大文字小文字と空白）されるため `repo:ccdb` と `Repo: CCDB` は同一のクレームとして扱われます。

ラウンジのプロンプトは、すべてのセッションに対して「開始前にクレームし、終了時に解放する」よう指示します。

### プログラム的なセッション作成

スクリプト、GitHub Actions、または他の Claude セッションから Discord のメッセージ操作なしで新しい Claude Code セッションを起動できます。

```bash
# 別の Claude セッションや CI スクリプトから:
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "リポジトリのセキュリティスキャンを実行", "thread_name": "Security Scan"}'
# スレッド作成後すぐに返答し、Claude はバックグラウンドで実行
```

**遅延起動 (`auto_start=false`)** — スレッドを作成してシードメッセージを投稿するが、Claude をすぐには起動しない。ユーザーが返信したときに初めて Claude が起動し、シードメッセージのコンテキストを自動的に受け取ります。

```bash
# 通知を投稿し、ユーザーが返信したときに Claude を起動
curl -X POST "$CCDB_API_URL/api/spawn" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "おはようございます！本日のサマリーです: ...",
    "thread_name": "モーニングブリーフィング",
    "auto_start": false
  }'
```

デイリーブリーフィングや CI アラートなど、情報を先に表示してユーザーが Claude に問いかけるかどうかを判断するワークフローに便利です。

Claude のサブプロセスには `DISCORD_THREAD_ID` 環境変数が渡されるため、実行中のセッションから子セッションを起動して作業を並列化できます。

### 認証済み外部インジェストと結果取得 (`/api/ingest`)

`POST /api/ingest` は、信頼できない外部クライアント（ブラウザ拡張機能、モバイルショートカット、webhook）向けの**認証済み、添付ファイル対応スポーン**です。`/api/spawn`（信頼済み、localhost）とは異なり、専用の `ingest_token`（`CCDB_INGEST_TOKEN` で設定。`api_secret` とは独立）が必要で、base64 ファイル添付をディスクに書き込み、スポーンされたセッションが読み取れるようにします。実際の Discord スレッドを作成するため、すべてのやり取りが観察可能です。

セッションは**インタラクティブ**（返信し続けられる本物の Discord スレッド）ですが、最終回答をプログラム的に取得することもできます。結果取得が設定されている場合（`setup_bridge()` 経由で自動接続）、レスポンスに `result_id` が含まれ、`GET /api/ingest/{result_id}` でセッションの最終返信をポーリングできます。同じ最終回答は Discord スレッドにも `ccdb-answer.md` として添付されるため、外部連携は添付ファイルを回答本文の正本として扱えます。これがラウンドトリップパターンです: スレッド + 添付ファイルを投稿 → 待機 → 回答ファイルまたはポーリング結果を読む → 自分のシステム（Teams スレッドなど）に書き戻す。一方で Discord が履歴を保持します。

```bash
# 作業を投稿（添付ファイルも可能）。すぐに返す
curl -X POST "$CCDB_API_URL/api/ingest" \
  -H "Authorization: Bearer $CCDB_INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "このスレッドを要約して返信草案を作成して",
       "attachments": [{"filename": "thread.txt", "data": "<base64>"}]}'
# → {"status": "spawned", "thread_id": "…", "result_id": "ab12…", "attachments_saved": 1}

# 最終返信をポーリング
curl "$CCDB_API_URL/api/ingest/ab12…" -H "Authorization: Bearer $CCDB_INGEST_TOKEN"
# → {"status": "done", "result": "…", "error": null, "thread_id": "…", "thread_name": "…"}
```

このエンドポイントはオプトイン方式です。`ingest_token` が設定されていない場合、`POST` は `503` を返します。結果取得が利用できない場合、`POST` は `result_id` を省略し、`GET /api/ingest/{id}` は `503` を返します — スポーン動作は変わりません。リクエスト本文と添付ファイルは結果ストアに保存されません（状態、最終テキスト、スレッド ID のみ）。結果は最大 200 件です。

### スタートアップリジューム

Bot の再起動中にセッションが中断された場合、Bot が再起動したときに自動的に再開されます。リジューム登録の方法は 3 つあります:

- **自動（アップグレード再起動）** — `AutoUpgradeCog` がパッケージアップグレードによる再起動直前にアクティブなセッションをすべてスナップショットし、自動でリジューム登録します。
- **自動（任意のシャットダウン）** — `ClaudeChatCog.cog_unload()` が任意のシャットダウン方法（`systemctl stop`、`bot.close()`、SIGTERM 等）でも実行中のセッションを自動登録します。
- **手動** — `POST /api/mark-resume` を直接呼び出して登録することもできます。

### バックエンド切り替え — Claude / Codex をオンデマンドで

ccdb 3.0 では、Bot を再起動せずにどの AI が次のセッションを処理するかを切り替える 3 つのスラッシュコマンドが追加されました:

- `/backend [name] [scope]` — バックエンドの表示または切り替え。`name` は `claude` または `codex`。`scope` は `thread`（このスレッドのみ）または `global`（サーバー全体のデフォルト）。`scope` を省略すると自動解決: スレッド内ではそのスレッドにスコープ、それ以外ではグローバルデフォルトを設定。
- `/model [name] [scope]` — **現在の**バックエンドで使用するモデルの表示または切り替え。各バックエンドは独自のモデル設定を記憶するため、バックエンドを切り替えても好みのモデルが保持されます。バックエンドのモデルを未設定にすると、その CLI 自身のデフォルトに委ねられます（たとえば Codex は `~/.codex/config.toml` の `model` を使用するため、ccdb が特定バージョンに固定せずコンソールのデフォルトに追従します）。
- `/effort [level] [scope]` — 現在のバックエンドで使用する**推論の強度**の表示または切り替え。有効なレベルはバックエンドごとに異なり、Claude は `low/medium/high/max`、Codex は `minimal/low/medium/high/xhigh`（CLI の `model_reasoning_effort` にマッピング）を受け付けます。未設定にすると CLI のデフォルトに委ねられます。

3 つのコマンドはいずれも `SettingsRepository` 経由で SQLite に永続化されるため、Bot を再起動しても設定が保持されます。引数なしで呼び出すと、現在のグローバルデフォルトとスレッドごとのオーバーライドを表示します。

**すでにセッションを持つスレッドはどうなる?** セッション ID は 2 つの CLI 間で互換性がありません — Codex の rollout ID を `claude --resume` に渡す（あるいは Claude の UUID を `codex exec resume` に渡す）と CLI レベルで失敗します。ccdb は各セッション ID をどちらのバックエンドが発行したかを記録しているため、切り替えでスレッドが取り残されることはありません:

- **スレッドスコープの切り替え** — 保存済みのセッション ID は破棄され、次のメッセージは新しいバックエンドで新規セッションとして始まります。ただし、そのレコードが切り替え**先**のバックエンドのものだと分かっている場合は保持されます。つまり元のバックエンドに戻せば、そのスレッドの以前の会話を再開できます。
- **グローバルな切り替え** — スレッドごとのレコードは意図的にそのまま残されます。スレッドがもう一方のバックエンドのセッション ID を保持したままの場合、次のメッセージはリジュームせずに新規セッションで開始し、その理由を 1 行の通知として投稿します。

ccdb がバックエンド情報を記録する前に作成されたレコードには発行元の情報がありません。グローバルな切り替えでは従来どおりリジュームされ、スレッドスコープの切り替えではリジューム失敗のリスクを避けるため破棄されます。

どちらの AI と話しているかを常に把握できるビジュアルキュー:

- **Claude セッション** は "🤖 Claude Code session started" というタイトルのブルーパープル embed で開始。
- **Codex セッション** は "🌀 OpenAI Codex session started" というタイトルの OpenAI ティール embed で開始。
- 完了 embed には通常の実行時間 / コスト / トークン / コンテキストメトリクスと並んで `🧠 Claude · sonnet` / `🧠 Codex · gpt-5.6-sol` チップが表示されます（バックエンドのモデルを CLI デフォルトのままにした場合、チップにはバックエンド名だけが表示されます）。

使用例:

```text
/backend codex                        # global → codex (next new sessions use codex)
/model gpt-5-codex                    # global → codex uses gpt-5-codex
/effort xhigh                          # global → codex reasons at xhigh effort
                                       # …open a thread, send a message…
/backend claude scope:thread          # this thread only → switch back to claude
/model opus scope:thread              # this thread only → claude/opus
/effort max scope:thread              # this thread only → claude reasons at max
                                       # other threads keep the global codex defaults
```

内部の仕組み:

- `BackendFactory` — 起動時に静的な設定（バックエンドごとのコマンドパス、パーミッションモード、作業ディレクトリ、許可ツール、タイムアウト、append-system-prompt、effort、api_port、api_secret）を取り込み、必要に応じて `ClaudeRunner` または `CodexRunner` を新規生成。`api_port` は REST API サーバー起動後に `setup_bridge` が自動で設定するため、Factory 経由で生成されたランナーは常に `CCDB_API_URL` がサブプロセス環境に注入される。
- `BackendSettings` — **スレッド > グローバル > 環境変数**の優先順位でアクティブなバックエンドを解決し、スラッシュコマンドからの書き込みを永続化する `SettingsRepository` の薄いラッパー。
- `SessionBackend` プロトコル — 両方のランナーが満たす抽象インターフェース。内部配管（Cog、embed、ビュー、スケジューラー、Webhook トリガー）は `SessionBackend` を受け取り、具体的なランナークラスには依存しない。

**各バックエンドの認証方法:** Claude Code は `claude login` で認証した Claude Pro/Max サブスクリプションを使用。Codex は `codex login` で認証した ChatGPT Plus/Pro/Business サブスクリプションを使用。ccdb が生の API キーを見ることは一切なく、選択された CLI を呼び出すだけです。

---

## 機能

### インタラクティブチャット

#### 🔗 セッションの基本
- **チャットのみモード** — `CHAT_ONLY_CHANNEL_IDS` にチャンネルを設定すると、Claude のテキスト応答のみを表示。ツール embed、思考ブロック、セッション開始/完了 embed、Todo リストはすべて非表示。許可リクエストと `AskUserQuestion` は常に表示。技術的な詳細を見せたくないパブリックチャンネルに最適。
- **Thread = Session** — Discord スレッドと Claude Code セッションの 1:1 マッピング
- **ゴール追跡** — `/goal <条件>` で完了条件を設定。Claude は条件を満たすまで継続して作業します。条件を省略するとステータス確認、`clear` を渡すとキャンセル
- **セッション永続化** — `--resume` で複数メッセージをまたいだ会話を継続
- **Codex リジュームの自動復旧** — リジュームした Codex セッションで出力開始前に WebSocket 切断が繰り返された場合、ccdb は以前の会話からサイズを制限したテキストのみの会話履歴を引き継いで代替セッションを開始。画像やツールのデータは除外
- **並行セッション** — 設定可能な上限での複数並行セッション
- **削除せず停止** — `/stop` でセッションを保持したまま停止し、リジューム可能
- **セッション割り込み** — アクティブなスレッドに新しいメッセージを送ると実行中のセッションに SIGINT を送り、新しい指示で即座に再開。手動での `/stop` 不要
- **スレッド自動リネーム** — `THREAD_AUTO_RENAME=true` のとき、最初のメッセージをもとに Claude が生成した短いタイトルでスレッドを自動リネーム（バックグラウンドタスクのためセッション開始を遅延させない）

#### 📡 リアルタイムフィードバック
- **リアルタイムステータス** — 絵文字リアクション: 🧠 思考中、🛠️ ファイル読み取り、💻 編集中、🌐 Web 検索
- **ストリーミングテキスト** — Claude の作業中に中間テキストがリアルタイムで表示
- **ツール結果 embed** — ライブツール呼び出し結果（開始直後に 0s を表示し、5 秒ごとに経過時間を更新）；1 行の出力はインライン表示、複数行の出力は展開ボタンで折りたたみ表示
- **拡張思考** — 推論をスポイラータグ付き embed で表示（クリックで展開）
- **スレッドダッシュボード** — アクティブ/待機スレッドを表示するライブピン embed。入力が必要なときはオーナーを @mention

#### 🤝 ヒューマンインザループ
- **インタラクティブな質問** — `AskUserQuestion` を Discord ボタンまたは Select Menu でレンダリング。回答でセッション再開。ボタンは Bot 再起動後も有効；入力が必要なときはリクエスターを @mention
- **Plan Mode** — Claude が `ExitPlanMode` を呼び出すと、プラン全文と Approve/Cancel ボタンを含む Discord embed を表示；承認後にのみ実行を開始；承認を求める際はリクエスターを @mention；5 分でタイムアウト（自動キャンセル）
- **ツール実行許可リクエスト** — Claude がツールを実行するために許可が必要な場合、ツール名と入力内容を示した Allow/Deny ボタンを Discord に表示；リクエスターを @mention；2 分間応答なしで自動拒否
- **MCP Elicitation** — MCP サーバーが Discord 経由でユーザー入力を要求（form-mode: JSON スキーマから最大 5 フィールドの Modal；url-mode: URL ボタン + Done 確認）；リクエスターを @mention；5 分でタイムアウト
- **TodoWrite ライブ進捗** — Claude が `TodoWrite` を呼び出すと Discord embed を一度投稿し、以降の更新はその embed をインプレースで編集；✅ 完了、🔄 実行中（`activeForm` ラベル付き）、⬜ 保留中の各状態を表示

#### 📊 オブザーバビリティ
- **トークン使用量** — セッション完了 embed にキャッシュヒット率とトークン数を表示
- **コンテキスト使用率** — セッション完了 embed にコンテキストウィンドウの使用率（入力＋キャッシュトークン。出力トークンは除外）と自動コンパクトまでの残容量を表示。83.5% 以上で ⚠️ 警告
- **コンパクト検出** — コンテキスト圧縮が発生した際にスレッド内で通知（トリガー種別 + 圧縮前のトークン数）
- **長時間停止通知** — アクティビティが途絶えた際にスレッドメッセージを送信（長考やコンテキスト圧縮中の可能性を通知）。Claude が再開すると自動リセット。閾値はモデルに応じて自動調整：標準モデルは 30 秒、Opus は 120 秒（長考時間が長いため）
- **タイムアウト通知** — 経過時間とリジューム手順付きの embed 表示
- **StatusLine 表示** — Claude が `statusLine` を設定している場合（`/statusline-setup` で設定）、各セッション完了後に現在のステータスを Discord に表示
- **スレッドインボックス** — `THREAD_INBOX_ENABLED=true` を設定すると、ダッシュボードに永続的な 📬 インボックスセクションが表示されます。セッション終了後、軽量な `claude -p` 呼び出しで最終メッセージを `waiting`（返信待ち）/ `done`（完了）/ `ambiguous`（不明）に分類。返信が必要なスレッドは Bot 再起動後も保持され、あなたが返信するまでサーフェスされます

#### 🔌 入力とスキル
- **添付ファイル対応** — テキストファイルをプロンプトに自動追加（最大 5 ファイル、1 ファイルあたり 200 KB / 合計 500 KB まで；上限を超えたファイルはスキップせずに先頭部分を切り取って通知付きで追加）；画像は Discord CDN URL として `--input-format stream-json` 経由で送信（最大 4 枚 × 5 MB）；Discord が長文貼り付けを自動的にファイル添付（`content_type` なし）に変換した場合も、拡張子ベースの検出で正しく処理
- **オンデマンドファイル配信** — 「送って」「添付して」などと指示すると Claude が `.ccdb-attachments` にパスを書き込み、セッション完了時に Bot がファイルを Discord に添付して送信。ローカル指示で、作り込んだ文章をMarkdown保存して添付する運用も指定できます
- **スキル実行** — `/skill` コマンド（オートコンプリート付き）、オプション引数、スレッド内リジューム。インストール済みプラグインのスキルも自動検出
- **ホットリロード** — `~/.claude/skills/` に追加した新スキルを自動検出（60 秒更新、再起動不要）

### 並行処理と協調
- **Worktree 指示の自動注入** — すべてのセッションに `git worktree` を使うよう指示
- **Worktree の自動クリーンアップ** — セッション終了時および Bot 起動時に `wt-{thread_id}` ディレクトリを自動削除。未コミットの変更がある場合は絶対に削除しない（安全性保証）
- **アクティブセッションレジストリ** — インメモリレジストリ。各セッションが他のセッションの状況を把握
- **AI Lounge** — 共有「控え室」チャンネル。コンテキストはバックエンド固有のシステム／開発者指示として注入（履歴に蓄積しないため長期セッションでも「Prompt is too long」が発生しない）。セッションが意図を投稿し、互いのステータスを確認し、破壊的な操作前にチェックします。人間には live アクティビティフィードとして見えます
- **クロスセッション可観測性** — `GET /api/sessions` がすべてのセッション（ライブ・保存済みの両方）を状態・作業ディレクトリ・最新のラウンジメモとともに一覧表示。`GET /api/threads/{thread_id}/messages` で他スレッドの会話を読める。読み取り専用なので、編集する前に見に行ける — ラウンジに一度も投稿していないセッションも対象
- **リソースクレーム** — `POST /api/claims` で作業開始前にリポジトリ・Issue・ファイルを予約。同じリソースを要求した 2 つ目のセッションには、保持者のスレッド・メモ・実行状態を含む 409 が返ります。アドバイザリかつ TTL 付き（既定 2 時間、最大 24 時間）なので、異常終了したセッションがリソースを永久占有することはありません
- **協調チャンネル** — `COORDINATION_CHANNEL_ID` 環境変数は AI Lounge チャンネルのデフォルトフォールバックとして使用（Bot 側のライフサイクル自動通知は廃止）

### スケジュールタスク
- **SchedulerCog** — 30 秒マスターループを持つ SQLite バックエンドの定期タスク実行エンジン
- **自己登録** — チャットセッション中に `POST /api/tasks` でタスクを登録
- **コード変更不要** — ランタイムでタスクを追加・削除・変更
- **有効/無効切り替え** — 削除せずにタスクを一時停止（`PATCH /api/tasks/{id}`）

### CI/CD 自動化
- **Webhook トリガー** — GitHub Actions や任意の CI/CD システムから Claude Code タスクをトリガー
- **自動アップグレード** — 上流パッケージリリース時に Bot を自動更新
- **DrainAware 再起動** — 再起動前にアクティブセッションの完了を待機
- **自動リジューム登録** — アップグレード再起動（`AutoUpgradeCog`）または任意のシャットダウン（`ClaudeChatCog.cog_unload()`）でアクティブセッションを自動登録。Bot 再起動後、Claude は前の状態を報告し、実装作業を再開する前に必ずユーザーに確認を取る
- **再起動承認** — アップグレード適用前の確認ゲート（オプション）。アップグレードスレッドへの ✅ リアクション、または親チャンネルに投稿されるボタンのどちらでも承認可能。新しいメッセージが届いてもボタンが流れないよう、チャンネル最下部へ自動で再投稿される
- **手動アップグレードトリガー** — `/upgrade` スラッシュコマンドで Discord から直接アップグレードパイプラインを実行（`slash_command_enabled=True` でオプトイン）

### セッション管理
- **組み込みヘルプ** — `/help` で利用可能な全スラッシュコマンドと基本的な使い方を表示（エフェメラル表示、呼び出し者のみ表示）
- **セッション同期** — CLI セッションを Discord スレッドにインポート（`/sync-sessions`）。`/sync-settings` で同期設定（スレッドスタイル、時間範囲、最小件数）の表示・変更が可能
- **セッション一覧** — 起動元（Discord / CLI / 全て）と時間範囲でフィルタリング（`/sessions`）
- **セッションリジューム** — `/resume` で直近のセッション一覧（最大 25 件）をセレクトメニューで表示し、選択したセッションを新スレッドで再開。オプションの `query` パラメータでキーワード検索（サマリーと作業ディレクトリにマッチ）、`filter=orphaned` で削除済みスレッドのセッションのみ表示。任意のチャンネルやスレッドから実行可能 — 常に設定されたメインチャンネルに新スレッドを作成
- **リジューム情報** — 現在のセッションをターミナルで継続する CLI コマンドを表示（`/resume-info`、スレッド内限定）
- **セッションクリア** — `/clear` で現在のスレッドの Claude Code セッションをリセットし、新スレッドを作成せずにゼロから再開
- **スタートアップリジューム** — 任意のBot 再起動後に中断セッションを自動再開。`AutoUpgradeCog`（アップグレード再起動）および `ClaudeChatCog.cog_unload()`（その他すべてのシャットダウン）が自動登録、または `POST /api/mark-resume` で手動登録
- **プログラム的スポーン** — `POST /api/spawn` でスクリプトや Claude サブプロセスから新しい Discord スレッド + Claude セッションを作成。スレッド作成後すぐに非ブロッキング 201 を返す
- **スレッド ID 注入** — すべての Claude サブプロセスに `DISCORD_THREAD_ID` 環境変数を渡し、セッションから `$CCDB_API_URL/api/spawn` で子セッションを起動可能
- **StatusLine 表示** — Claude Code の `settings.json` に `statusLine` が設定されている場合、各セッション返信後に Discord に表示
- **Worktree 管理** — `/worktree-list` でアクティブなセッション Worktree を clean/dirty ステータス付きで表示、`/worktree-cleanup` で孤立した clean な Worktree を削除（`dry_run` プレビューあり）
- **実行時モデル切り替え** — `/model-show` で現在のグローバルモデルとスレッドごとのセッションモデルを表示、`/model-set` で再起動不要のまま全新規セッションのモデルを変更
- **実行時ツールパーミッション** — `/tools-show` で現在の許可ツールを表示、`/tools-set` でトグルメニューからツールのオン/オフを切り替え、`/tools-reset` で `.env` デフォルト設定に戻す — すべて再起動不要
- **コンテキスト使用率** — `/context` でコンテキストウィンドウの使用率をビジュアルプログレスバーで表示。83.5% の自動コンパクトしきい値に近づくと ⚠️ 警告。エフェメラル表示（呼び出し者のみ）
- **レート制限使用率** — `/usage` で Claude API のレート制限使用率をパーセントバーとリセットまでのカウントダウン付きで表示（5 時間・7 日間ウィンドウ）。使用率 80% 以上で ⚠️ フラグ
- **会話の巻き戻し** — `/rewind` で過去のユーザーターン一覧をセレクトメニューで表示し、選択したターンでセッションの JSONL を切り捨て。そのメッセージ以降をすべて削除し、直前の状態から再開できる。Claude が作成した作業ファイルは保持される。セッションが迷走したときに便利
- **会話のフォーク** — `/fork` で `--fork-session` フラグを使い、現在のセッション状態から独立した新しいセッションコピーとして新スレッドを作成。元のスレッドに影響を与えず、別の方向を探索できる

### セキュリティ
- **シェルインジェクション防止** — `asyncio.create_subprocess_exec` のみ使用、`shell=True` は一切なし
- **セッション ID 検証** — `--resume` に渡す前に厳格な正規表現で検証
- **フラグインジェクション防止** — すべてのプロンプト前に `--` セパレーター
- **シークレット分離** — Bot トークンを subprocess 環境から除去
- **ユーザー認証** — `allowed_user_ids` で Claude を呼び出せるユーザーを制限
- **ログインジェクション防止** — API 経由のユーザー入力値はログ書き込み前に無害化（改行文字除去）

---

## クイックスタート — 5 分で Discord に Claude または Codex を

**前提条件:**

- Python 3.10+
- 以下のうち少なくとも 1 つ:
  - [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) — インストールと認証（`claude login`）。Anthropic Pro/Max サブスクライバーに推奨。
  - [OpenAI Codex CLI](https://github.com/openai/codex) — `npm install -g @openai/codex` の後 `codex login`。既存の ChatGPT Plus/Pro/Business サブスクリプションを使用。
- 両方インストールも可能。実行時に `/backend` でいつでも切り替えられます（[バックエンド切り替え](#バックエンド切り替え--claude--codex-をオンデマンドで) 参照）。

**対応プラットフォーム:** 主に **Linux** で開発・テストされています。macOS と Windows はサポートされ CI は通過しますが、実環境でのテストは限定的 — バグ報告歓迎。

### Step 1 — Discord Bot の作成（一度だけ、約 2 分）

1. [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. **Bot** に移動 → Privileged Gateway Intents の **Message Content Intent** を有効化
3. Bot の **Token** をコピー
4. **OAuth2 → URL Generator** へ: スコープ `bot` + `applications.commands`、権限: Send Messages, Create Public Threads, Send Messages in Threads, Add Reactions, Manage Messages, Read Message History
5. 生成された URL を開いてサーバーに Bot を招待

### Step 2 — セットアップウィザードを実行

クローンや `.env` 編集は不要 — ウィザードがすべて行います:

```bash
# uvx を使う場合（インストール不要）:
uvx --from "git+https://github.com/ebibibi/claude-code-discord-bridge.git" ccdb setup

# または、クローン後:
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv run ccdb setup
```

ウィザードの流れ:
1. Discord API に対して Bot トークンを検証
2. **利用可能なチャンネルを自動一覧表示** — 番号を選ぶだけ（ID のコピー不要）
3. 作業ディレクトリとモデルの選択
4. `.env` を書き込み、すぐに Bot を起動するか確認

```
╔══════════════════════════════════════════════════════╗
║          ccdb setup — interactive wizard             ║
╚══════════════════════════════════════════════════════╝

Step 1 — Claude Code CLI
  ✅  claude found

Step 2 — Discord Bot Token
  Bot Token: [paste here]
  Validating token… ✅  Logged in as MyBot#1234

Step 3 — Discord Channel ID
  Fetching channels via Discord API… ✅  Found 5 text channel(s)

   1. #general        (My Server)
   2. #claude-code    (My Server)
   3. #dev            (My Server)
   ...

  Select channel [1-5]: 2
  ✅  #claude-code (123456789012345678)

  ...

  ✅  Written: .env
  Start the bot now? [Y/n]: y
```

### 起動 / 停止

```bash
ccdb start    # Bot を起動（カレントディレクトリの .env を読む）
ccdb start --env /path/to/.env   # カスタム .env の場所を指定
```

設定したチャンネルにメッセージを送ると、Claude が新しいスレッドで返信します。

### systemd サービスとして運用（本番環境）

本番環境では systemd 管理下で動かすと、起動時の自動開始と障害時の自動再起動が得られます。

リポジトリにはテンプレートとして `discord-bot.service`（サービスファイル）と `scripts/pre-start.sh`（起動前スクリプト）が同梱されています。コピーしてパスやユーザー名を書き換えてください:

```bash
# 1. サービスファイルを編集 — /home/ebi と User=ebi をご自身のパス/ユーザーに変更
sudo cp discord-bot.service /etc/systemd/system/mybot.service
sudo nano /etc/systemd/system/mybot.service

# 2. 有効化して起動
sudo systemctl daemon-reload
sudo systemctl enable mybot.service
sudo systemctl start mybot.service

# 3. 状態確認
sudo systemctl status mybot.service
journalctl -u mybot.service -f
```

**`scripts/pre-start.sh` の動作**（ボットプロセス起動前に `ExecStartPre` として実行）:

1. **`git pull --ff-only`** — `origin main` から最新コードを取得
2. **`uv sync`** — `uv.lock` に従って依存関係を最新の状態に同期
3. **インポート検証** — `claude_discord.main` が正常にインポートできるか確認
4. **自動ロールバック** — インポートに失敗した場合は前のコミットに戻して再試行。Discord webhook に成功/失敗を通知
5. **Worktree クリーンアップ** — クラッシュしたセッションが残した git worktree を削除

スクリプトはリポジトリのルートを自動検出（`$0` に対する `readlink -f`）するため、どのユーザーがどの場所にクローンしてもパスの書き換えは不要です。`uv` のパスも `PATH` から自動検出します。カスタムパスを使う場合は `CCDB_UV_BIN` 環境変数で指定してください。

`.env` に `DISCORD_WEBHOOK_URL` を設定すると障害通知が届きます（任意）。

#### ツールチェーンの PATH — `.env` に設定する

systemd はユニットを最小限の `PATH`（通常は `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`）で起動し、`~/.bashrc` や `~/.profile` を一切読み込みません。Bot はその `PATH` を引き継ぎ、Bot が起動する Claude / Codex の各セッションも同じ環境（除去されるシークレットを除く）を継承します。

そのため、ターミナルでは成功するビルドが Discord セッションの中では失敗したり、気づかないうちに古いシステム側のバイナリで実行されたりします。`~/.local/bin` や `~/.npm-global/bin` にインストールしたツールがサービスからは見えないためです。

サービスは `EnvironmentFile=` で `.env` を読み込むため、そこに `PATH` を設定すれば Bot と全セッションを一度に修正できます。

```bash
# .env — 対話シェルの PATH に合わせる
PATH=/home/you/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin
```

サービスを再起動し（`sudo systemctl restart mybot.service`）、Discord セッションで Claude に `which node && node --version` を実行させて確認してください。

### カスタム Cog（フォーク不要で機能拡張）

Python ファイルをディレクトリに追加するだけで独自機能を追加できます — フォーク不要、サブクラス不要、パッケージ不要:

```bash
ccdb start --cogs-dir ./my-cogs/
# または: CUSTOM_COGS_DIR=./my-cogs ccdb start
```

ディレクトリ内の各 `.py` ファイルは `async def setup(bot, runner, components)` を公開する必要があります:

```python
from discord.ext import commands

class GreeterCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel = self.bot.get_channel(self.bot.channel_id)
        await channel.send(f"Welcome {member.mention}!")

async def setup(bot, runner, components):
    await bot.add_cog(GreeterCog(bot))
```

`_` で始まるファイルはスキップされます。1 つの Cog の読み込みが失敗しても、他は正常に読み込まれます。

リマインダー、Todoist ウォッチドッグ、自動アップグレード、ドキュメント同期を含む実例は [`examples/ebibot/`](../../examples/ebibot/) を参照してください。

**`examples/ebibot/cogs/` に含まれる組み込みサンプル:**

| Cog | 用途 |
|-----|------|
| `ReminderCog` | Discord ベースのリマインダースケジューリング |
| `WatchdogCog` | Todoist / 外部サービスウォッチドッグ |
| `AutoUpgradeCog` | Webhook トリガーによるパッケージ自動アップグレード |
| `DocsSyncCog` | プッシュ時の自動ドキュメント同期 |
| `AlertResponderCog` | 汎用アラート監視 — 監視システムからのアラートを Discord に転送し、Claude Code による調査セッションをトリガー |

---

### ミニマル Bot（パッケージとしてインストール）

すでに discord.py Bot を動かしている場合は、ccdb をパッケージとして追加します:

```bash
uv add git+https://github.com/ebibibi/claude-code-discord-bridge.git
```

`bot.py` を作成します:

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

`setup_bridge()` はすべての Cog を自動的に配線します。最新版へのアップデート:

```bash
uv lock --upgrade-package claude-code-discord-bridge && uv sync
```

#### マルチチャンネル設定

複数の Discord チャンネルに Bot を展開するには、`claude_channel_id` に加えて（または代わりに）`claude_channel_ids` を指定します:

```python
await setup_bridge(
    bot,
    runner,
    claude_channel_id=YOUR_CHANNEL_ID,       # プライマリ（スレッド作成のフォールバック）
    claude_channel_ids={
        YOUR_CHANNEL_ID,
        YOUR_CHANNEL_ID_2,
    },
    allowed_user_ids={YOUR_USER_ID},
)
```

設定されたチャンネルはそれぞれ完全に独立して動作します。どのチャンネルへのメッセージも新しい Claude セッションスレッドを起動し、`/skill` コマンドもすべてのチャンネルで機能します。`claude_channel_id` は後方互換性のために残されており、`/skill` コマンドが設定外チャンネルから実行された場合のフォールバック先として使用されます。

#### メンション専用チャンネル

**@メンションされたときだけ**応答するチャンネルを設定できます（共有チャンネルなどで全メッセージに反応させたくない場合に便利）:

```python
await setup_bridge(
    bot,
    runner,
    claude_channel_ids={111, 222},
    mention_only_channel_ids={222},  # #222 では @メンションされた時だけ応答
    allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
)
```

環境変数でも設定可能（カンマ区切りのチャンネル ID）:

```
MENTION_ONLY_CHANNEL_IDS=222,333
```

スレッドは**親チャンネルのポリシーを継承**します。メンション専用チャンネル内で人間が作成したスレッドでは、Claude セッションは起動しません（そうでなければ、スレッドを作るだけで設定を回避できてしまいます）。そうしたスレッドで Claude が応答するのは、次のいずれかの場合だけです:

- メッセージ内で Bot が明示的に **@メンション**されている
- ccdb が**すでにそのスレッドを所有している** — Bot が作成したセッションスレッド、または `/api/spawn` で作成されたスレッド。セッションが存在すれば、以降の返信はメンションなしで通常通り処理されます。

`mention_only_channel_ids` に**含まれていない**チャンネル配下のスレッドは影響を受けず、これまで通り常に処理されます。

#### インライン返信チャンネル

特定のチャンネルで**スレッドを作らずにチャンネル内に直接返信**させることができます（個人コマンドチャンネルなど、スレッドが煩わしい場合に便利）:

```python
await setup_bridge(
    bot,
    runner,
    claude_channel_ids={111, 333},
    inline_reply_channel_ids={333},  # #333 ではスレッドを作らずインライン返信
    allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
)
```

環境変数でも設定可能（カンマ区切りのチャンネル ID）:

```
INLINE_REPLY_CHANNEL_IDS=333,444
```

インライン返信モードでは、Claude の返信は新しいスレッドではなくチャンネル内のメッセージとして直接送信されます。セッションは内部で追跡されているため、その後のメッセージも同じ Claude セッションとして継続します。

#### チャットのみチャンネル

特定のチャンネルで技術的な UI（ツール埋め込み、thinking ブロック、セッション開始/完了通知、Todo リスト）を非表示にし、**Claude のテキスト返信のみ**を表示する — 非技術系ユーザーが見ている公開チャンネルに便利です:

```python
await setup_bridge(
    bot,
    runner,
    claude_channel_ids={111, 444},
    chat_only_channel_ids={444},  # #444 ではテキストのみ表示、ツール詳細は非表示
    allowed_user_ids={int(os.environ["DISCORD_OWNER_ID"])},
)
```

環境変数でも設定可能（カンマ区切りのチャンネル ID）:

```
CHAT_ONLY_CHANNEL_IDS=444,555
```

チャットのみモードでも、パーミッションリクエストと `AskUserQuestion` プロンプトは**常に表示**されます — 人間の入力が必要なため、必ず表示する必要があります。

---

## 設定

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `DISCORD_BOT_TOKEN` | Discord Bot トークン | （必須） |
| `DISCORD_CHANNEL_ID` | Claude チャット用チャンネル ID | （必須） |
| `CCDB_BACKEND` | 使用する CLI バックエンド: `claude`（Claude Code CLI）または `codex`（OpenAI Codex CLI） | `claude` |
| `CCDB_COMMAND` | CLI バイナリのパスまたは名前（`CLAUDE_COMMAND` より優先）。`CCDB_BACKEND` で選択された初期ランナーに使用され、実行時に `/backend` で切り替えた際は以下の 2 つのバックエンド別変数が優先されます。 | _（自動: `claude` or `codex`）_ |
| `CCDB_CLAUDE_COMMAND` | Claude CLI バイナリの明示的なパス。`/backend claude` がアクティブなとき `BackendFactory` が使用（`CCDB_BACKEND` の初期値に依存しない）。`CLAUDE_COMMAND`、次に `claude`（PATH）へのフォールバックあり。 | （オプション） |
| `CCDB_CODEX_COMMAND` | OpenAI Codex CLI バイナリの明示的なパス。systemd 下で Bot を実行する場合に必須（デフォルトのサービス PATH に `~/.npm-global/bin` が含まれない）。`codex`（PATH）へのフォールバックあり。 | （オプション） |
| `PATH` | Bot **と Bot が起動する全 CLI セッション**のバイナリ検索パス（セッションは Bot の環境を継承）。systemd はユニットを最小限の PATH で起動し `~/.bashrc` / `~/.profile` を読まないため、systemd 運用時は `.env` に設定する。[ツールチェーンの PATH](#ツールチェーンの-path--env-に設定する) 参照 | （親プロセスから継承） |
| `CCDB_MODEL` | 使用するモデル（`CLAUDE_MODEL` より優先） | `sonnet` |
| `CCDB_PERMISSION_MODE` | CLI のパーミッションモード（`CLAUDE_PERMISSION_MODE` より優先） | `acceptEdits` |
| `CCDB_DANGEROUSLY_SKIP_PERMISSIONS` | 全パーミッションチェックをスキップ（`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` より優先） | `false` |
| `CCDB_WORKING_DIR` | CLI の作業ディレクトリ（`CLAUDE_WORKING_DIR` より優先） | カレントディレクトリ |
| `CCDB_ALLOWED_TOOLS` | 許可するツールのカンマ区切りリスト（`CLAUDE_ALLOWED_TOOLS` より優先） | （オプション） |
| `CCDB_CHANNEL_IDS` | マルチチャンネル設定用の追加チャンネル ID（`CLAUDE_CHANNEL_IDS` より優先） | （オプション） |
| `CLAUDE_COMMAND` | Claude CLI バイナリのパスまたは名前（旧名 — `CCDB_COMMAND` を推奨）。特定バージョンを固定する場合に使用（例: `CLAUDE_COMMAND=/usr/local/lib/node_modules/@anthropic-ai/claude-code@2.1.77/cli.js`）— 新バージョンのリグレッション回避に便利。 | `claude` |
| `CLAUDE_MODEL` | 使用するモデル（旧名 — `CCDB_MODEL` を推奨） | `sonnet` |
| `CLAUDE_PERMISSION_MODE` | CLI のパーミッションモード（旧名 — `CCDB_PERMISSION_MODE` を推奨） | `auto` |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | 全パーミッションチェックをスキップ（旧名 — `CCDB_DANGEROUSLY_SKIP_PERMISSIONS` を推奨） | `false` |
| `CLAUDE_WORKING_DIR` | Claude の作業ディレクトリ（旧名 — `CCDB_WORKING_DIR` を推奨） | カレントディレクトリ |
| `MAX_CONCURRENT_SESSIONS` | 最大並行 Claude CLI セッション数（チャット・スキル・スケジューラ・Webhook の全パスに適用） | `3` |
| `SESSION_TIMEOUT_SECONDS` | セッション非アクティブタイムアウト | `300` |
| `DISCORD_OWNER_ID` | Claude が入力待ちのとき @mention する Discord ユーザー ID | （オプション） |
| `COORDINATION_CHANNEL_ID` | AI Lounge チャンネルのデフォルトフォールバック用チャンネル ID | （オプション） |
| `MENTION_ONLY_CHANNEL_IDS` | @メンション時のみ応答するチャンネル ID（カンマ区切り。配下のスレッドもポリシーを継承） | （オプション） |
| `INLINE_REPLY_CHANNEL_IDS` | インライン返信チャンネル ID（カンマ区切り、スレッドを作成しない） | （オプション） |
| `CHAT_ONLY_CHANNEL_IDS` | チャットのみモードのチャンネル ID（カンマ区切り）— Claude のテキスト応答のみ表示。ツール embed・思考・セッション情報・Todo はすべて非表示 | （オプション） |
| `WORKTREE_BASE_DIR` | セッション Worktree のスキャン対象ディレクトリ（自動クリーンアップを有効化） | （オプション） |
| `CLI_SESSIONS_PATH` | CLI セッション検出用のパス（`~/.claude/projects`）。`/sync-sessions` の有効化に必要 | （オプション） |
| `CUSTOM_COGS_DIR` | 起動時に読み込むカスタム Cog ファイルを含むディレクトリ（[カスタム Cog](#カスタム-cogフォーク不要で機能拡張) 参照） | （オプション） |
| `CLAUDE_ALLOWED_TOOLS` | Claude CLI に許可するツールのカンマ区切りリスト（旧名 — `CCDB_ALLOWED_TOOLS` を推奨） | （オプション） |
| `CLAUDE_CHANNEL_IDS` | マルチチャンネル設定用の追加チャンネル ID（旧名 — `CCDB_CHANNEL_IDS` を推奨） | （オプション） |
| `THREAD_INBOX_ENABLED` | 永続スレッドインボックスを有効化（`claude -p` でセッションを `waiting`/`done`/`ambiguous` に分類し、スレッドダッシュボードに表示） | `false` |
| `THREAD_AUTO_RENAME` | 新しいスレッドのタイトルを Claude AI で自動リネーム — 最初のユーザーメッセージをもとにバックグラウンドの `claude -p` 呼び出しで短く分かりやすいタイトルを生成（セッション開始を遅延させない） | `false` |
| `CCDB_CLI_ENV_FILE` | CLI サブプロセス起動時に毎回環境変数へマージする `KEY=VALUE` ファイルのパス。Bot を再起動せずに即座に反映される。一時的な API ルーティング（Azure Foundry への切り替えなど）に便利 | （オプション） |
| `CCDB_LOG_FILE` | ログファイルのパス。設定するとデフォルトの stdout ハンドラに加えてローテーティングファイルハンドラ（10 MB × 5 バックアップ）が追加される。監視・アラートに便利 | （オプション） |
| `API_HOST` | REST API バインドアドレス | `127.0.0.1` |
| `API_PORT` | REST API ポート（設定すると REST API が有効になる） | （オプション） |

### パーミッションモード — `-p` モードで動作するもの

ccdb を通じて使用する場合、Claude Code CLI は **`-p`（非インタラクティブ）モード** で動作します。このモードでは、CLI は **権限の確認ができない** ため、承認が必要なツールは即座に拒否されます。これは ccdb の制限ではなく、[CLI の設計上の制約](https://code.claude.com/docs/en/headless)です。

| モード | `-p` モードでの動作 | 推奨 |
|------|----------------------|----------------|
| `default` | ❌ **すべてのツールが拒否される** — 使用不可 | 使用しないこと |
| `acceptEdits` | ⚠️ Edit/Write は自動承認、Bash は拒否（Claude はファイル操作に Write にフォールバック） | 最低限動作するオプション |
| `bypassPermissions` | ✅ すべてのツールが承認される | 動作するが、以下を推奨 |
| **`auto`** | ✅ **AI による安全性分類** — 安全な操作は自動承認、危険な操作はブロック | **推奨** — 安全性と使いやすさのベストバランス |
| `plan` | ✅ AI による分類（読み取り優先）— auto と同様だが、より保守的 | 読み取り中心のワークフロー向け |
| **`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`** | ✅ **すべてのツールが承認される（安全チェックなし）** | レガシー「yolo」モード — auto モードで制限が強すぎる場合に使用 |

**推奨設定:** `CLAUDE_PERMISSION_MODE=auto` を設定してください。auto モードは AI 分類器を使用して、安全な操作（ファイル編集、ローカルテスト、作業ブランチへの git push）を自動承認しつつ、危険な操作（force push、本番デプロイ、認証情報の漏洩）をブロックします。yolo モードの「何でも許可」リスクなしで、通常の開発作業において Claude に完全な自律性を与えられます。

**yolo モードへのフォールバック:** auto モードで必要な操作がブロックされる場合は、代わりに `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true` を設定してください。ccdb が `allowed_user_ids` で Claude との対話を制御しているため、CLI レベルのパーミッションチェックは意味のあるセキュリティ上の利点なしに摩擦を生むだけです。名前に含まれる「dangerously（危険）」は CLI の汎用的な警告を反映したものですが、アクセスがすでにゲートされている ccdb の文脈では、実用的な選択肢です。

> **注意:** `CLAUDE_PERMISSION_MODE` を `auto` または `plan` に設定した場合、`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` は自動的に無視されます — これらのモードは独自の安全分類器を持っており、yolo フラグによってオーバーライドされてしまいます。

**細かい制御を行うには**、`CLAUDE_ALLOWED_TOOLS` を使用して、すべてのパーミッションをバイパスせずに特定のツールのみを許可できます：

```env
# 例：ファイル操作とコード実行を許可するが、Web アクセスは不許可
CLAUDE_ALLOWED_TOOLS=Bash,Read,Write,Edit,Glob,Grep

# 例：読み取り専用モード — Claude は探索できるが変更は不可
CLAUDE_ALLOWED_TOOLS=Read,Glob,Grep
```

主なツール名：`Bash`、`Read`、`Write`、`Edit`、`Glob`、`Grep`、`WebFetch`、`WebSearch`、`NotebookEdit`。この設定を使用する場合は `CLAUDE_PERMISSION_MODE=default` にしてください（他のモードではオーバーライドされる場合があります）。

**Discord からの実行時変更：** `/tools-set` を使用すると、Bot を再起動せずに実行時に許可ツールを変更できます。設定は永続化され、以降のすべての新規セッションに即座に反映されます。現在の設定を確認するには `/tools-show`、`.env` デフォルトに戻すには `/tools-reset` を使用してください。

> **Discord のパーミッションボタン：** `CLAUDE_PERMISSION_MODE=default` の場合、Claude は `permission_request` イベントを発行し、ccdb はスレッドに許可／拒否ボタンを表示します。stdin は常時開放（stream-json 入力モード）されているため、Bot が Claude へ応答を返すことができます。`auto` または `plan` モードを使用している場合、Claude はユーザーの操作なしに自動でパーミッションを処理します。`CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true`（yolo モード）の場合、ccdb は `permission_request` イベントを**即座に自動承認**します — 許可／拒否ボタンは表示されません。これは CLI のリグレッション（v2.1.78+、upstream [#35895](https://github.com/anthropics/claude-code/issues/35895)）の回避策で、`--dangerously-skip-permissions` がファイルレベルの機密パスチェックをバイパスできない問題に対処しています。

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
    restart_approval=True,       # スレッドの ✅ リアクション、またはチャンネルのボタンで承認
    slash_command_enabled=True,  # /upgrade スラッシュコマンドを有効化（オプトイン、デフォルト False）
)

await bot.add_cog(AutoUpgradeCog(bot, config))
```

#### `/upgrade` スラッシュコマンドによる手動トリガー

`slash_command_enabled=True` の場合、認可されたユーザーが Discord から `/upgrade` を実行することで、Webhook なしで同じアップグレードパイプラインをトリガーできます。テキストチャンネルとスレッドの両方から実行でき（スレッド内から実行した場合は親チャンネルにアップグレードスレッドを作成します）。`upgrade_approval` および `restart_approval` のゲートが適用され、進捗スレッドが作成されます。すでにアップグレードが実行中の場合はエフェメラルで通知します。

再起動前に `AutoUpgradeCog` は以下の手順を実行します:

1. **アクティブセッションのスナップショット** — `_active_runners` を持つ Cog からアクティブなスレッド ID を収集（duck-typed で自動検出）。
2. **ドレイン** — アクティブセッションが自然に完了するまで待機。
3. **リジューム登録** — アクティブなスレッド ID を保留リジュームテーブルに保存。次回起動時に安全優先のプロンプトで再開：Claude は何をしていたかを報告し、実装作業（コード変更・コミット・PR 作成など）を再開する前に必ずユーザーに確認を取ります。これにより、コンテキスト圧縮でタスクの承認状態が消えた後に意図しない操作が実行されるのを防ぎます。
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
| POST | `/api/spawn` | 新しい Discord スレッドを作成し Claude Code セッションを起動（非ブロッキング）。`auto_start: false` を指定するとユーザーの最初の返信まで Claude の起動を延期できる |
| POST | `/api/ingest` | 認証済み外部スポーン（ブラウザ拡張機能 / webhook）。base64 添付ファイル対応。結果取得が設定されている場合 `result_id` を返す |
| GET | `/api/ingest/{result_id}` | スポーンされたセッションの最終返信をポーリング（`status`/`result`/`error`/`thread_id`） |
| POST | `/api/mark-resume` | 次回 Bot 起動時のスレッド自動リジュームを登録 |
| GET | `/api/lounge` | AI Lounge の最近のメッセージを取得 |
| POST | `/api/lounge` | AI Lounge にメッセージを投稿（`label` オプション） |
| GET | `/api/sessions` | すべてのセッション（ライブ・保存済み）を状態・作業ディレクトリ・最新のラウンジメモ付きで一覧（`state=running`、`exclude_thread`、`limit`） |
| GET | `/api/threads/{thread_id}/messages` | 他スレッドの会話を古い順に取得（`limit`） |
| POST | `/api/claims` | 作業開始前にリソースを宣言 — 取得成功で 201、取得済みなら保持者情報付きで 409 |
| GET | `/api/claims` | 有効なクレームの一覧（`resource` フィルター任意） |
| DELETE | `/api/claims` | クレームの解放（`resource`、`thread_id`、任意で `force=true`） |

```bash
# 通知の送信（埋め込み形式、デフォルト）
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "ビルド成功！", "title": "CI/CD"}'

# プレーンテキスト通知の送信（埋め込みなし）
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"message": "デプロイ完了！", "format": "text"}'

# Discord Poll の送信
curl -X POST http://localhost:8080/api/notify \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "投票してください",
    "poll": {
      "question": "次のリリーストラックは？",
      "answers": ["安定版", "ベータ版", "ナイトリー"],
      "duration_hours": 24,
      "allow_multiselect": false
    }
  }'

# 定期タスクの登録
curl -X POST http://localhost:8080/api/tasks \
  -H "Authorization: Bearer your-secret" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "デイリースタンドアップ要約", "interval_seconds": 86400}'
```

---

## アーキテクチャ

```
claude_code_core/          # バックエンド非依存のコアライブラリ
  backend.py               # SessionBackend プロトコル + create_backend() ファクトリー
  codex_runner.py          # OpenAI Codex CLI バックエンド
  runner.py                # Claude CLI subprocess マネージャー
  parser.py                # stream-json イベントパーサー
  types.py                 # SDK メッセージの型定義
  models.py                # SQLite スキーマ
  session_repo.py          # セッション CRUD
  lounge_repo.py           # AI Lounge メッセージ CRUD
  rewind.py                # セッションリワインドヘルパー
claude_discord/
  main.py                  # スタンドアロンエントリーポイント（setup_bridge + カスタム Cog ローダー）
  cli.py                   # CLI エントリーポイント（ccdb setup/start コマンド）
  setup.py                 # setup_bridge() — 1 行で Cog を配線
  cog_loader.py            # 動的カスタム Cog ローダー（CUSTOM_COGS_DIR）
  bot.py                   # Discord Bot クラス
  protocols.py             # 共有プロトコル（DrainAware）
  concurrency.py           # Worktree 指示 + アクティブセッションレジストリ
  lounge.py                # AI Lounge プロンプトビルダー
  session_view.py          # GET /api/sessions 用のクロスセッションビュー（純粋なマージロジック）
  session_sync.py          # CLI セッションの検出とインポート
  worktree.py              # WorktreeManager — git worktree の安全なライフサイクル管理
  cogs/
    claude_chat.py         # インタラクティブチャット（スレッド作成、メッセージ処理）
    skill_command.py       # /skill スラッシュコマンド（オートコンプリート付き）
    session_manage.py      # /sessions, /sync-sessions, /resume, /resume-info, /sync-settings
    session_sync.py        # sync-sessions のスレッド作成・メッセージ投稿ロジック
    prompt_builder.py      # build_prompt_and_images() — 純粋関数、Cog/Bot 状態に非依存
    scheduler.py           # 定期 Claude Code タスク実行エンジン
    webhook_trigger.py     # Webhook → Claude Code タスク実行（CI/CD）
    auto_upgrade.py        # Webhook → パッケージアップグレード + DrainAware 再起動
    event_processor.py     # EventProcessor — stream-json イベントのステートマシン
    run_config.py          # RunConfig データクラス — CLI 実行パラメーターをまとめる
    _run_helper.py         # 薄いオーケストレーション層（run_claude_with_config + shim）
  claude/
    runner.py              # claude_code_core からの ClaudeRunner 再エクスポート
    parser.py              # claude_code_core からの parse_line 再エクスポート
    types.py               # claude_code_core からの型定義再エクスポート
  database/
    models.py              # SQLite スキーマ
    repository.py          # セッション CRUD
    task_repo.py           # スケジュールタスク CRUD
    ask_repo.py            # 保留中 AskUserQuestion CRUD
    notification_repo.py   # スケジュール通知 CRUD
    lounge_repo.py         # AI Lounge メッセージ CRUD
    claims_repo.py         # アドバイザリなリソースクレーム CRUD（TTL 付き）
    resume_repo.py         # スタートアップリジューム CRUD（Bot 再起動をまたいだ保留リジューム）
    settings_repo.py       # ギルドごとの設定
    inbox_repo.py          # スレッドインボックス CRUD（THREAD_INBOX_ENABLED）
  discord_ui/
    status.py              # 絵文字リアクションステータスマネージャー（デバウンス付き）
    chunker.py             # フェンス・テーブル対応メッセージ分割
    embeds.py              # Discord embed ビルダー
    views.py               # 停止ボタンと共有 UI コンポーネント
    mentions.py            # user_mention_kwargs() — Claude が入力待ちのときリクエスターに通知
    ask_bus.py             # AskUserQuestion 通信用イベントバス
    ask_view.py            # AskUserQuestion 用 Discord ボタン / Select Menu
    ask_handler.py         # collect_ask_answers() — AskUserQuestion UI + DB ライフサイクル
    streaming_manager.py   # StreamingMessageManager — デバウンス付きインプレース編集
    tool_timer.py          # LiveToolTimer — 長時間ツール実行の経過時間カウンター
    thread_dashboard.py    # スレッドのセッション状態を表示する live ピン embed
    plan_view.py           # Plan Mode 承認ボタン（Approve/Cancel）
    permission_view.py     # ツール実行許可ボタン（Allow/Deny）
    elicitation_view.py    # MCP Elicitation 用 Discord UI（Modal フォームまたは URL ボタン）
    file_sender.py         # .ccdb-attachments 経由のファイル配信
    inbox_classifier.py    # classify() — セッションにラベルを付ける軽量 claude -p 呼び出し
    thread_renamer.py      # suggest_title() — スレッド自動リネーム用バックグラウンド claude -p 呼び出し
  ext/
    api_server.py          # REST API サーバー（オプション、aiohttp が必要）
  utils/
    logger.py              # ロギング設定
examples/
  ebibot/                  # 実例: カスタム Cog を使った個人 Bot
    cogs/
      reminder.py          # /remind スラッシュコマンド + スケジュール通知
      watchdog.py          # Todoist 期限切れタスクモニター
      auto_upgrade.py      # GitHub webhook 経由の自己更新
      docs_sync.py         # push 時のドキュメント自動翻訳
```

### 設計思想

- **CLI スポーン、API ではない** — `claude -p --output-format stream-json` を呼び出し、Claude Code の全機能（CLAUDE.md、スキル、ツール、メモリ）を利用。Claude Pro/Max サブスクリプションで動作 — API キー不要、トークン課金なし
- **並行処理ファースト** — 複数の同時セッションが例外ではなく期待値。すべてのセッションに worktree 指示を注入し、レジストリと AI Lounge が残りを処理
- **Discord を接着剤として** — Discord が UI、スレッディング、リアクション、Webhook、永続的な通知を提供。カスタムフロントエンド不要
- **フレームワーク、アプリケーションではない** — パッケージとしてインストールし、既存の Bot に Cog を追加し、コードで設定
- **ゼロコード拡張性** — ソースを変更せずにスケジュールタスクと Webhook トリガーを追加
- **シンプルさによるセキュリティ** — 約 8000 行の監査可能な Python。subprocess exec のみ、シェル展開なし

---

## テスト

```bash
uv run pytest tests/ -v --cov=claude_discord
```

1670 件以上のテストがパーサー、チャンカー、リポジトリ、ランナー、ストリーミング、Webhook トリガー、自動アップグレード（`/upgrade` スラッシュコマンド、スレッド内実行、承認ボタン含む）、REST API、AskUserQuestion UI、スレッドダッシュボード、スケジュールタスク、セッション同期、AI Lounge、クロスセッション可観測性、リソースクレーム、スタートアップリジューム、モデル切り替え、コンパクト検出、TodoWrite 進捗 embed、カスタム Cog ローダー、許可／Elicitation／Plan Mode イベントパース、スレッドインボックス分類、スレッドごとのロック動作、SessionBackend プロトコル、CodexRunner、バックエンドファクトリー、バックエンドをまたぐセッション所有権をカバーしています。

---

## このプロジェクトの構築方法

**このコードベースは [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Anthropic の AI コーディングエージェント — によって、[@ebibibi](https://github.com/ebibibi) の指揮のもとで開発されています。人間の著者は要件を定義し、PR をレビューし、すべての変更を承認します — 実装は Claude Code が行います。

つまり:

- **実装は AI 生成** — アーキテクチャ、コード、テスト、ドキュメント
- **PR レベルでの人間によるレビューが行われています** — すべての変更は GitHub のプルリクエストと CI を経てマージされます
- **バグレポートと PR を歓迎します** — Claude Code を使って対応することになるでしょう
- **これは人間が指揮し AI が実装するオープンソースソフトウェアの実例です**

このプロジェクトは 2026-02-18 に開始され、Claude Code との反復的な会話を通じて進化し続けています。

---

## 実例

**[`examples/ebibot/`](../../examples/ebibot/)** — このフレームワーク上に構築された個人 Discord Bot がこのリポジトリに同梱されています。カスタム Cog ローダーを以下のもので実演しています:

- **ReminderCog** — `/remind HH:MM "メッセージ"` スラッシュコマンド + 30 秒送信ループ
- **WatchdogCog** — Todoist 期限切れタスクモニター（30 分チェック、デイリー重複排除、重要度別アラート）
- **AutoUpgradeCog** — GitHub webhook + systemctl restart による自己更新
- **DocsSyncCog** — push 時の Webhook 経由でドキュメントを自動翻訳
- **AlertResponderCog** — 汎用アラート監視 Cog。設定可能なソースを監視し、重要度付き通知を Discord に投稿

実行方法: `ccdb start --cogs-dir examples/ebibot/cogs/`

> EbiBot のカスタム Cog は以前は[別のリポジトリ](https://github.com/ebibibi/discord-bot)で管理されていましたが、現在はここに同梱されています。これにより Claude Code がフレームワークとカスタマイズの両方について完全なコンテキストを持てるようになり、機能の重複実装を防ぎます。

---

## インスパイアされたプロジェクト

- [OpenClaw](https://github.com/openclaw/openclaw) — 絵文字ステータスリアクション、メッセージデバウンシング、フェンス対応チャンキング
- [claude-code-discord-bot](https://github.com/timoconnellaus/claude-code-discord-bot) — CLI スポーン + stream-json アプローチ
- [claude-code-discord](https://github.com/zebbern/claude-code-discord) — パーミッション制御パターン
- [claude-sandbox-bot](https://github.com/RhysSullivan/claude-sandbox-bot) — スレッドごとの会話モデル

---

## ライセンス

MIT
