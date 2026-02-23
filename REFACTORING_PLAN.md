# ccbd 大規模リファクタリング計画

## 目標

4つの改善軸:
1. `_run_helper.py` 分割（523行の神ファイルを解体）
2. アーキテクチャ整理（責任の明確化・レイヤー境界の強化）
3. 型安全性の強化（RunConfig導入・Protocol強化）
4. テストの改善（共通fixture・テストファイル分割）

## 現状の問題

### `_run_helper.py` (523行) の問題
- `StreamingMessageManager` — Discord UIコンポーネントなのに `cogs/` にある
- `LiveToolTimer` — 同上
- `_collect_ask_answers()` — AskUserQuestionの完全なサブシステム
- `run_claude_in_thread()` — 8パラメータ、245行の巨大関数

### 型安全性の問題
- `run_claude_in_thread()` に8つのパラメータ（構造体にすべき）
- `SessionState.active_tools` が `discord.Message` 直参照（テスト困難）

### テストの問題
- `test_run_helper.py` が926行（巨大）
- 各テストファイルで `thread` fixtureを重複定義
- `conftest.py` が存在しない

## 新しいファイル構造

```
claude_discord/
├── discord_ui/
│   ├── streaming_manager.py    # NEW: StreamingMessageManager (移動)
│   ├── tool_timer.py           # NEW: LiveToolTimer (移動)
│   ├── ask_handler.py          # NEW: _collect_ask_answers (移動)
│   └── __init__.py             # UPDATED: 新エクスポート追加
│
├── cogs/
│   ├── run_config.py           # NEW: RunConfig dataclass
│   ├── event_processor.py      # NEW: EventProcessor class
│   ├── _run_helper.py          # REFACTORED: ~120行の薄いオーケストレーション層
│   └── __init__.py             # UPDATED
│
└── __init__.py                 # UPDATED: 必要なら公開API調整

tests/
├── conftest.py                 # NEW: 共通fixture (thread, runner, make_event)
├── test_streaming_manager.py   # NEW: StreamingMessageManagerのテスト (移動)
├── test_tool_timer.py          # NEW: LiveToolTimerのテスト (移動)
├── test_event_processor.py     # NEW: EventProcessorのテスト
├── test_ask_handler.py         # NEW: _collect_ask_answersのテスト (移動)
└── test_run_helper.py          # REDUCED: オーケストレーションのみ (~150行)
```

## 実装フェーズ

### Phase 1: Discord UI コンポーネントの移動

#### 1-1: `StreamingMessageManager` → `discord_ui/streaming_manager.py`
- `StreamingMessageManager` クラスをそのまま移動
- 定数も一緒に移動: `STREAM_EDIT_INTERVAL`, `STREAM_MAX_CHARS`
- `_run_helper.py` からimportで参照

#### 1-2: `LiveToolTimer` → `discord_ui/tool_timer.py`
- `LiveToolTimer` クラスをそのまま移動
- 定数: `TOOL_TIMER_INTERVAL`
- `_run_helper.py` からimportで参照

#### 1-3: `_collect_ask_answers` → `discord_ui/ask_handler.py`
- `_collect_ask_answers()` と `ASK_ANSWER_TIMEOUT` を移動
- `_run_helper.py` からimportで参照

### Phase 2: `RunConfig` dataclass の導入

```python
# cogs/run_config.py
@dataclass
class RunConfig:
    """Configuration for a single Claude Code execution."""
    thread: discord.Thread
    runner: ClaudeRunner
    prompt: str
    session_id: str | None = None
    repo: SessionRepository | None = None
    status: StatusManager | None = None
    registry: SessionRegistry | None = None
    ask_repo: PendingAskRepository | None = None
    lounge_repo: LoungeRepository | None = None
```

`run_claude_in_thread()` のシグネチャを変更:
```python
# 変更前 (8パラメータ)
async def run_claude_in_thread(thread, runner, repo, prompt, session_id, status, registry, ask_repo, lounge_repo)

# 変更後 (1パラメータ)
async def run_claude_in_thread(config: RunConfig) -> str | None
```

呼び出し側 (`claude_chat.py`, `skill_command.py`, `scheduler.py`, `webhook_trigger.py`) も更新。

### Phase 3: `EventProcessor` クラスの導入

`run_claude_in_thread()` 内の巨大な `if event.message_type == ...` チェーンを
`EventProcessor` クラスに抽出。テスト可能で拡張しやすい設計に。

```python
# cogs/event_processor.py
class EventProcessor:
    """Processes stream events and dispatches to Discord actions."""

    def __init__(self, config: RunConfig) -> None:
        self._config = config
        self._state = SessionState(session_id=config.session_id, thread_id=config.thread.id)
        self._streamer = StreamingMessageManager(config.thread)
        self._session_start_sent: bool = False
        self._assistant_text_sent: bool = False
        self._pending_ask: list[AskQuestion] | None = None

    async def process(self, event: StreamEvent) -> None:
        """Dispatch a single event to the appropriate handler."""
        if event.message_type == MessageType.SYSTEM:
            await self._on_system(event)
        elif event.message_type == MessageType.ASSISTANT:
            await self._on_assistant(event)
        elif event.message_type == MessageType.USER:
            await self._on_tool_result(event)
        elif event.is_complete:
            await self._on_complete(event)

    @property
    def session_id(self) -> str | None:
        return self._state.session_id

    @property
    def pending_ask(self) -> list[AskQuestion] | None:
        return self._pending_ask

    # 各ハンドラは個別テスト可能
    async def _on_system(self, event: StreamEvent) -> None: ...
    async def _on_assistant(self, event: StreamEvent) -> None: ...
    async def _on_tool_result(self, event: StreamEvent) -> None: ...
    async def _on_complete(self, event: StreamEvent) -> None: ...
    async def finalize(self) -> None: ...  # タイマーキャンセル等のクリーンアップ
```

`_run_helper.py` はこれを使う薄い層になる (~120行):
```python
async def run_claude_in_thread(config: RunConfig) -> str | None:
    # プロンプト前処理 (lounge context + concurrency notice)
    prompt = await _prepare_prompt(config)

    processor = EventProcessor(config._replace(prompt=prompt))

    try:
        async for event in config.runner.run(prompt, session_id=config.session_id):
            if processor.pending_ask is not None:
                continue
            await processor.process(event)
    except Exception:
        ...
    finally:
        await processor.finalize()

    # AskUserQuestion ハンドリング
    if processor.pending_ask and processor.session_id:
        ...

    return processor.session_id
```

### Phase 4: 型安全性の強化

- `RunConfig` の導入 (Phase 2) で関数シグネチャが大幅改善
- `SessionState.active_tools` の型を明示的に保持 (`dict[str, discord.Message]`)
- `EventProcessor` 内部の状態を明示的に typed field で表現
- `_run_helper.py` の `_make_error_embed` と `_truncate_result` を
  より適切な場所 (`embeds.py` / `event_processor.py`) に移動
- `protocols.py` に `EventHandler` Protocol を追加（将来の拡張用）

### Phase 5: テストの改善

#### 5-1: `tests/conftest.py` 作成
全テストで使える共通fixture:
```python
@pytest.fixture
def thread() -> MagicMock:
    """Standard mock Discord thread."""
    t = MagicMock(spec=discord.Thread)
    msg = MagicMock(spec=discord.Message)
    t.send = AsyncMock(return_value=msg)
    msg.edit = AsyncMock()
    return t

@pytest.fixture
def make_event() -> Callable[..., StreamEvent]:
    """Factory for creating test StreamEvents."""
    ...

@pytest.fixture
def mock_runner() -> MagicMock:
    """Mock ClaudeRunner."""
    ...
```

#### 5-2: `test_run_helper.py` の分割
- `TestStreamingMessageManager` → `test_streaming_manager.py`
- `TestLiveToolTimer` → `test_tool_timer.py`
- `TestCollectAskAnswers` → `test_ask_handler.py`
- `TestEventProcessor` (新規) → `test_event_processor.py`
- `test_run_helper.py` は統合テスト的なものだけ残す

### Phase 6: デッドコード削除

`.reports/dead-code-analysis.md` に記録済みの3項目を削除:
1. `AskAnswerBus.has_waiter()` — 呼び出し箇所ゼロ
2. `PendingAskRepository.update_question_idx()` — 呼び出し箇所ゼロ
3. `CoordinationService.post_session_start()` — AI Loungeで置き換え済み

## 実装順序

```
Phase 6 (デッドコード削除) → 最初にやる (簡単・リスク低)
Phase 1 (Discord UI移動) → 機械的な移動、テスト通れば安全
Phase 2 (RunConfig) → シグネチャ変更、全呼び出し元を更新
Phase 3 (EventProcessor) → 最も複雑、慎重に
Phase 4 (型安全性) → Phase 2-3 と並行して対応
Phase 5 (テスト改善) → 全フェーズで継続的に
```

## 不変条件 (リファクタリング中に守ること)

- 全テストを通し続ける (`pytest --cov -x`)
- `ruff check` をパスし続ける
- 公開API (`__init__.py` のエクスポート) は変えない
- セキュリティ: `runner.py` の subprocess 安全策は変えない
