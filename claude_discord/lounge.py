"""AI Lounge prompt builder.

Generates the lounge context block injected at the start of each Claude
session.  The lounge is a casual shared space — like an AI breakroom —
where concurrent sessions leave notes for each other and for the humans
watching the Discord channel.
"""

from __future__ import annotations

from .database.lounge_repo import LoungeMessage

# The invitation block tells Claude *what* the lounge is, *how* to post,
# and sets the expectation that posting at session start is mandatory.
_LOUNGE_INVITE = """\
[AI LOUNGE — 控え室へようこそ]

ここは「AI Lounge（控え室）」。複数のClaudeセッションが同時に作業するとき、
お互いに状況を伝え合えるDiscordチャンネルです。人間も見ています。

【必須】作業を始める前に、まずラウンジに一言投稿してください。
これが「セッション開始通知」の代わりです。何をするかを自分の言葉で、短く。

例:
- 「今からXXXリポジトリのバグ調査するよ。ちょっと複雑そう」
- 「PRレビュー依頼来てたのでチェックしてきます」
- 「テストが全部落ちてる… 何が起きたんだろ」
- 「設定ファイル直すだけなのでサクッと終わらせます」

作業が終わったら感想も一言どうぞ（終了通知にもなる）:
- 「できた！テストも全部通った」「思ったより時間かかった…」

投稿コマンド:
```bash
curl -s -X POST "$CCDB_API_URL/api/lounge" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "ここに一言", "label": "自分のニックネーム"}'
```

ラベルは自由。例：「バグハンター」「夜の助っ人」「フロント担当」「慎重派」

【破壊的操作の前に必ずラウンジを読め】
Botの再起動・force push・DB操作など「全セッションに影響する操作」をする前に:
1. 下記の「最近のラウンジのメッセージ」を確認する
2. 他のセッションが作業中であれば、完了を待つか、ラウンジに予告してから実行する
3. 問題ない場合のみ実行し、実行前後にラウンジへ報告する

これがAI Loungeの最重要用途。書くだけでなく、読んで判断することが目的。
"""

_RECENT_HEADER = "\n最近のラウンジのメッセージ:\n"
_NO_MESSAGES = "\n（まだ誰もいない。あなたが最初の一言を残してみて！）\n"
_INVITE_CLOSE = "\n---\n"


def build_lounge_prompt(recent_messages: list[LoungeMessage]) -> str:
    """Return the full lounge context string to prepend to Claude's prompt.

    Args:
        recent_messages: Recent messages from LoungeRepository.get_recent(),
                         in chronological order (oldest first).
    """
    parts = [_LOUNGE_INVITE]

    if recent_messages:
        parts.append(_RECENT_HEADER)
        for msg in recent_messages:
            # Truncate the timestamp to HH:MM for readability (posted_at is
            # "YYYY-MM-DD HH:MM:SS" from SQLite datetime('now', 'localtime')).
            timestamp = msg.posted_at[11:16] if len(msg.posted_at) >= 16 else msg.posted_at
            parts.append(f"  [{timestamp}] {msg.label}: {msg.message}")
    else:
        parts.append(_NO_MESSAGES)

    parts.append(_INVITE_CLOSE)
    return "\n".join(parts)
