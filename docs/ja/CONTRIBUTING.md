> **Note:** This is an auto-translated version of the original English documentation.
> If there are any discrepancies, the [English version](../../CONTRIBUTING.md) takes precedence.
> **注意:** これは英語のオリジナルドキュメントを自動翻訳したものです。
> 内容に相違がある場合は、[英語版](../../CONTRIBUTING.md)が優先されます。

# claude-code-discord-bridge へのコントリビューション

コントリビューションに興味を持っていただきありがとうございます！このプロジェクトは Claude Code によって構築されており、人間と AI エージェント両方からのコントリビューションを歓迎します。

## ブランチワークフロー

シンプルな PR ベースのワークフローである **GitHub Flow** を使用しています:

```
main（常にリリース可能）
  ├── feature/add-xxx   → PR → CI 通過 → レビュー → マージ
  ├── fix/issue-123     → PR → CI 通過 → レビュー → マージ
  └── （main への直接プッシュは禁止）
```

### 手順

1. リポジトリを **Fork**（書き込み権限がある場合はブランチを作成）
2. `main` から**ブランチを作成**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **変更を加える** — コードを書き、テストを追加
4. ブランチを **Push** して `main` に対して **PR を開く**
5. **CI が自動実行** — Python 3.10/3.11/3.12 でテスト + lint
6. CI が通過しレビューされたら、`main` に**マージ**

### ブランチ命名

- `feature/description` — 新機能
- `fix/description` または `fix/issue-123` — バグ修正
- `docs/description` — ドキュメントのみ
- `refactor/description` — 動作変更なしのコード整理

## 開発環境のセットアップ

```bash
git clone https://github.com/ebibibi/claude-code-discord-bridge.git
cd claude-code-discord-bridge
uv sync --dev
```

## テストの実行

```bash
uv run pytest tests/ -v --cov=claude_discord
```

PR を提出する前にすべてのテストが通過している必要があります。

## コードスタイル

- **フォーマッター**: `ruff format`
- **リンター**: `ruff check`
- **型ヒント**: すべての関数シグネチャに必須
- **Python**: 3.10+（モダンな構文のために `from __future__ import annotations` を使用）

```bash
uv run ruff check claude_discord/
uv run ruff format claude_discord/
```

## プロジェクト構造

- `claude_discord/claude/` — Claude Code CLI との連携（runner、parser、types）
- `claude_discord/cogs/` — Discord.py の Cog（chat、skill コマンド、webhook トリガー、自動アップグレード）
- `claude_discord/database/` — SQLite セッションおよび通知の永続化
- `claude_discord/discord_ui/` — Discord UI コンポーネント（status、chunker、embeds）
- `claude_discord/ext/` — オプション拡張（REST API サーバー — aiohttp が必要）
- `tests/` — pytest テストスイート

## 変更の提出

1. リポジトリを Fork してフィーチャーブランチを作成
2. 新機能のテストを書く
3. プッシュ前にローカルで実行:
   ```bash
   uv run ruff check claude_discord/
   uv run ruff format --check claude_discord/
   uv run pytest tests/ -v
   ```
4. 何を・なぜという明確な説明を付けて PR を提出
5. CI が自動実行 — すべてのチェックが通過する必要があります

## 新しい Cog の追加

1. `claude_discord/cogs/your_cog.py` を作成
2. Claude CLI 実行には `_run_helper.run_claude_with_config(RunConfig(...))` を使用
   （旧 `run_claude_in_thread()` shim も引き続き使えるが、新規コードは `run_claude_with_config` を優先）
3. `claude_discord/cogs/__init__.py` からエクスポート
4. `claude_discord/__init__.py` のパブリック API に追加
5. `tests/test_your_cog.py` にテストを書く

## AI 生成コードについて

このプロジェクトは Claude Code によって書かれました。コントリビューションに Claude Code や他の AI ツールを使うのは全く問題ありません — コードが動作し、テストされており、意味を成すことを確認してください。
