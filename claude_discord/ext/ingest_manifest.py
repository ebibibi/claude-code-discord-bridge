"""Reconcile what an ingest client *intended* to send against what arrived.

Why this exists
---------------
``POST /api/ingest`` used to be blind: it saved whatever bytes it was handed and
reported ``attachments_saved: N``. Nothing in the pipeline knew what ``N``
*should* have been, so a client that silently dropped an attachment (failed
download, size cap, a canvas capture that never loaded) produced a session that
answered confidently on incomplete evidence. For a Teams thread the missing file
is usually the one that matters most — the log or screenshot on the newest
message, the whole reason the thread was exported.

The fix is a manifest: the client declares every attachment it *found*, together
with how it fared (``embedded`` = bytes are in this request, ``linked`` /
``skipped`` / ``failed`` = they are not). ccdb matches that declaration against
the files that actually landed on disk and makes any shortfall impossible to
miss — in the session prompt, in a report file, in the HTTP response and in the
log. ccdb cannot recover bytes the client never sent; it can refuse to let their
absence pass silently, which is the part that was broken.

Everything here is pure and side-effect free apart from hashing files, so the
matching rules are directly testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# Statuses a client may report for one attachment it discovered upstream.
# Only ``embedded`` claims that bytes accompany this request.
STATUS_EMBEDDED = "embedded"
STATUS_LINKED = "linked"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
_KNOWN_STATUSES = frozenset({STATUS_EMBEDDED, STATUS_LINKED, STATUS_SKIPPED, STATUS_FAILED})

# A manifest describes attachments, not payload: keep it bounded so a malformed
# or hostile client cannot make ccdb build an enormous report.
MAX_MANIFEST_ENTRIES = 2000
_MAX_FIELD_CHARS = 400


def _clean(value: object, limit: int = _MAX_FIELD_CHARS) -> str | None:
    """Reduce a client-supplied field to a bounded single-line string."""
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return None
    return text[:limit]


@dataclass(frozen=True)
class ManifestEntry:
    """One attachment the client found upstream, and how it fared."""

    name: str
    status: str = STATUS_EMBEDDED
    kind: str | None = None
    size: int | None = None
    sha256: str | None = None
    # Which upstream message it hung off ("元投稿", "返信 12", …). Optional, but
    # it is what lets the prompt say "the newest message's attachment is gone".
    message: str | None = None
    url: str | None = None
    reason: str | None = None

    @property
    def claims_bytes(self) -> bool:
        """True when the client says this attachment's bytes are in the request."""
        return self.status == STATUS_EMBEDDED

    def describe(self) -> str:
        """Human-readable one-liner for reports and prompts."""
        bits = [self.name]
        if self.message:
            bits.append(f"（{self.message}）")
        detail = self.reason or ""
        if self.url and not detail:
            detail = self.url
        if detail:
            bits.append(f" — {detail}")
        return "".join(bits)


@dataclass(frozen=True)
class DeliveredFile:
    """A file that actually exists on disk after the request was unpacked."""

    path: Path
    size: int
    sha256: str

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Reconciliation:
    """The verdict: what was promised, what arrived, what is missing."""

    #: Every entry in the order the client declared it — i.e. upstream message
    #: order. Kept separately because the buckets below regroup by outcome, and
    #: "which message is newest" is a question only the original order answers.
    entries: list[ManifestEntry] = field(default_factory=list)
    matched: list[tuple[ManifestEntry, DeliveredFile]] = field(default_factory=list)
    #: status=embedded, but no file on disk answers to it — a real loss.
    missing: list[ManifestEntry] = field(default_factory=list)
    #: The client already knew these never made it (link-only, size cap, error).
    not_delivered: list[ManifestEntry] = field(default_factory=list)
    #: Files on disk nothing in the manifest claimed. Informational, not a fault.
    unlisted: list[DeliveredFile] = field(default_factory=list)
    #: False when the client sent no manifest at all — nothing can be verified.
    verified: bool = True

    @property
    def expected(self) -> int:
        """How many attachments the client claimed to be sending bytes for."""
        return len(self.matched) + len(self.missing)

    @property
    def delivered(self) -> int:
        return len(self.matched) + len(self.unlisted)

    @property
    def lost(self) -> list[ManifestEntry]:
        """Everything the session will NOT be able to read, in one list."""
        return [*self.missing, *self.not_delivered]

    @property
    def is_complete(self) -> bool:
        return not self.lost


def parse_manifest(raw: object) -> tuple[list[ManifestEntry], str | None]:
    """Parse the client's ``attachments_manifest`` field.

    Accepts a list of entry objects, or a wrapper object with an ``entries`` /
    ``attachments`` list (so the field can grow other metadata later without a
    breaking change). Returns ``(entries, error)``; ``error`` is a ready-to-send
    message and is only set for a manifest that is structurally wrong — a
    malformed *entry* is skipped rather than failing the whole ingest, because
    losing the whole export over one bad record is worse than the bug it reports.
    """
    if raw is None:
        return [], None
    if isinstance(raw, dict):
        raw = raw.get("entries", raw.get("attachments"))
        if raw is None:
            return [], None
    if not isinstance(raw, list):
        return [], "attachments_manifest must be a list"
    if len(raw) > MAX_MANIFEST_ENTRIES:
        return [], f"attachments_manifest too large (max {MAX_MANIFEST_ENTRIES} entries)"

    entries: list[ManifestEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name") or item.get("filename")) or "(名称不明)"
        status = _clean(item.get("status"), 32) or STATUS_EMBEDDED
        if status not in _KNOWN_STATUSES:
            # An unknown status must not be read as "delivered" — treat it as a
            # failure so it surfaces, rather than silently counting as fine.
            status = STATUS_FAILED
        size = item.get("size", item.get("bytes"))
        try:
            size_int = int(size) if size is not None else None
        except (TypeError, ValueError):
            size_int = None
        sha = _clean(item.get("sha256"), 64)
        entries.append(
            ManifestEntry(
                name=name,
                status=status,
                kind=_clean(item.get("kind"), 32),
                size=size_int,
                sha256=sha.lower() if sha else None,
                message=_clean(item.get("message") or item.get("source_message")),
                url=_clean(item.get("url")),
                reason=_clean(item.get("reason")),
            )
        )
    return entries, None


def hash_files(paths: list[Path]) -> list[DeliveredFile]:
    """Stat + SHA-256 every delivered file, skipping anything unreadable."""
    out: list[DeliveredFile] = []
    for path in paths:
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
            out.append(
                DeliveredFile(path=path, size=path.stat().st_size, sha256=digest.hexdigest())
            )
        except OSError:
            continue
    return out


def _suffix_match(entry_name: str, file_name: str) -> bool:
    """Match a name a bundler disambiguated with an index prefix.

    Clients that zip a whole thread rename colliding files (``image.png`` →
    ``4_image.png``), so the manifest name is a *suffix* of the delivered name.
    Requiring the prefix to be digits + ``_`` keeps this from matching unrelated
    files that merely end the same way.
    """
    if not file_name.endswith(entry_name) or file_name == entry_name:
        return False
    prefix = file_name[: -len(entry_name)]
    return prefix.endswith("_") and prefix[:-1].isdigit()


def reconcile(entries: list[ManifestEntry], files: list[DeliveredFile]) -> Reconciliation:
    """Match manifest entries to delivered files, strongest evidence first.

    Passes run in order — sha256, exact name, index-prefixed name, size — and a
    file is consumed by at most one entry, so two attachments with identical
    names cannot both match the single file that arrived (which is exactly how a
    silent loss used to hide).
    """
    if not entries:
        return Reconciliation(unlisted=list(files), verified=False)

    remaining = list(files)
    matched: list[tuple[ManifestEntry, DeliveredFile]] = []
    pending = [e for e in entries if e.claims_bytes]
    not_delivered = [e for e in entries if not e.claims_bytes]

    def take(entry: ManifestEntry, predicate) -> bool:
        for i, candidate in enumerate(remaining):
            if predicate(entry, candidate):
                matched.append((entry, remaining.pop(i)))
                return True
        return False

    passes = (
        lambda e, f: bool(e.sha256) and e.sha256 == f.sha256,
        lambda e, f: e.name == f.name,
        lambda e, f: _suffix_match(e.name, f.name),
        lambda e, f: e.size is not None and e.size == f.size,
    )

    unresolved = pending
    for predicate in passes:
        still: list[ManifestEntry] = []
        for entry in unresolved:
            if not take(entry, predicate):
                still.append(entry)
        unresolved = still
        if not unresolved:
            break

    return Reconciliation(
        entries=list(entries),
        matched=matched,
        missing=unresolved,
        not_delivered=not_delivered,
        unlisted=remaining,
    )


def _group_by_message(entries: list[ManifestEntry]) -> list[tuple[str, list[ManifestEntry]]]:
    """Group entries by their upstream message, preserving manifest order."""
    groups: list[tuple[str, list[ManifestEntry]]] = []
    index: dict[str, list[ManifestEntry]] = {}
    for entry in entries:
        key = entry.message or "（メッセージ未特定）"
        bucket = index.get(key)
        if bucket is None:
            bucket = []
            index[key] = bucket
            groups.append((key, bucket))
        bucket.append(entry)
    return groups


def render_attachment_section(result: Reconciliation, saved_paths: list[Path]) -> str:
    """The attachment part of the ingest prompt.

    Without a manifest this is the old flat path list. With one, files are
    grouped by the upstream message they came from and the **newest** group is
    called out, because that is the message being replied to and its evidence is
    the evidence that matters.
    """
    if not result.verified:
        listing = "\n".join(f"- {p}" for p in saved_paths)
        return (
            "添付ファイル（ローカルに保存済み）。下記はパス一覧です。"
            "全部を読み込む必要はありません。返信に必要なものだけ Read ツール等で"
            f"選択的に開いてください:\n{listing}"
        )

    by_message = _group_by_message([entry for entry, _ in result.matched])
    path_of = {id(entry): file.path for entry, file in result.matched}

    lines: list[str] = [
        "添付ファイル（ローカルに保存済み・元メッセージごと）。"
        "返信に必要なものを Read ツール等で開いてください:"
    ]
    for position, (message, group) in enumerate(by_message):
        newest = position == len(by_message) - 1 and len(by_message) > 1
        header = f"■ {message}" + ("　★最新メッセージ（最優先で確認）" if newest else "")
        lines.append(header)
        for entry in group:
            lines.append(f"  - {path_of[id(entry)]}")

    extra = [f.path for f in result.unlisted]
    if extra:
        lines.append("■ マニフェスト外（送信元が申告していないファイル）")
        lines.extend(f"  - {p}" for p in extra)

    lines.append(
        "返信対象は最新メッセージです。最新メッセージに添付がある場合は、"
        "推測で答えず必ずその中身を確認してから返信を書いてください。"
    )
    return "\n".join(lines)


def render_prompt_warning(result: Reconciliation) -> str | None:
    """A loud, unmissable block for the top of the prompt — or None if complete.

    The instruction matters as much as the list: a session that answers as if it
    had the missing file is worse than one that says "the log did not arrive,
    please resend", because the first looks finished.
    """
    if result.is_complete:
        return None

    lines = [
        "⚠️【添付ファイルが欠落しています — 内容を推測で補わないこと】",
        "送信元が申告した添付のうち、以下は**このセッションから読めません**。",
    ]
    if result.missing:
        lines.append("● 送信されるはずが届かなかったもの（送信元の不具合）:")
        lines.extend(f"  - {e.describe()}" for e in result.missing)
    if result.not_delivered:
        lines.append("● 送信元が実体を取得できなかったもの（リンクのみ／サイズ超過など）:")
        lines.extend(f"  - {e.describe()}" for e in result.not_delivered)

    newest = _newest_missing_message(result)
    if newest:
        lines.append(
            f"● 特に注意: **最新メッセージ「{newest}」の添付が欠けています**。"
            "返信の根拠そのものが不足している可能性が高いです。"
        )
    lines.append(
        "対応: 欠落した添付の内容を推測して回答を書かないでください。"
        "回答できる範囲は回答したうえで、**どの添付が届いていないかを明示**し、"
        "再送または内容の共有を依頼してください。"
    )
    return "\n".join(lines)


def _newest_missing_message(result: Reconciliation) -> str | None:
    """The last upstream message that lost an attachment, if it is the newest.

    Manifest order follows the upstream thread, so the final message named
    anywhere in the manifest is the newest one — and it is worth a separate
    warning when that is the message whose evidence went missing. Read from
    ``entries`` (declaration order), never from the outcome buckets: those are
    grouped by verdict, so their last element is not the newest message.
    """
    named = [e.message for e in result.entries if e.message]
    if not named:
        return None
    newest = named[-1]
    return newest if any(e.message == newest for e in result.lost) else None


def render_report(result: Reconciliation) -> str:
    """The full ledger, written next to the files as ``ATTACHMENTS-REPORT.md``.

    The prompt stays short on purpose; this is where the complete picture lives
    for a human (or the session) who wants to check the pipeline itself.
    """
    lines = ["# 添付ファイル受信レポート", ""]
    if not result.verified:
        lines += [
            "送信元が添付マニフェストを送っていないため、**欠落の有無を検証できません**。",
            "（送信元を新しいバージョンに更新すると検証が有効になります）",
            "",
            f"受信ファイル数: {result.delivered}",
            "",
        ]
        lines += [f"- {f.name}（{f.size:,} bytes）" for f in result.unlisted]
        return "\n".join(lines)

    verdict = "✅ 完全" if result.is_complete else "⚠️ 欠落あり"
    declared = len(result.matched) + len(result.missing) + len(result.not_delivered)
    lines += [
        f"判定: **{verdict}**",
        "",
        f"- 送信元が申告した添付: {declared} 件",
        f"- 受信して読める添付: {len(result.matched)} 件",
        f"- 届かなかった添付: {len(result.lost)} 件",
        f"- 申告外で届いたファイル: {len(result.unlisted)} 件",
        "",
    ]

    if result.matched:
        lines += [
            "## 受信できた添付",
            "",
            "| 元メッセージ | 名前 | サイズ | 保存先 |",
            "| --- | --- | --- | --- |",
        ]
        for entry, file in result.matched:
            lines.append(
                f"| {entry.message or '-'} | {entry.name} | {file.size:,} | `{file.path}` |"
            )
        lines.append("")

    if result.missing:
        lines += [
            "## 届かなかった添付（送信元は「送った」と申告）",
            "",
            "送信元の不具合です。実体が存在しないため、このセッションからは読めません。",
            "",
        ]
        lines += [f"- {e.describe()}" for e in result.missing]
        lines.append("")

    if result.not_delivered:
        lines += ["## 送信元が実体を取得できなかった添付", ""]
        for entry in result.not_delivered:
            lines.append(f"- [{entry.status}] {entry.describe()}")
        lines.append("")

    if result.unlisted:
        lines += ["## 申告外で届いたファイル", ""]
        lines += [f"- `{f.path}`（{f.size:,} bytes）" for f in result.unlisted]
        lines.append("")

    return "\n".join(lines)


def summarize_for_response(result: Reconciliation) -> dict[str, object]:
    """The machine-readable verdict returned by ``POST /api/ingest``.

    The sending client is the one that can actually fix a loss (retry, widen a
    cap, download the file properly), so it gets the verdict back rather than
    having to infer it from a count.
    """
    return {
        "verified": result.verified,
        "complete": result.is_complete if result.verified else None,
        "expected": result.expected if result.verified else None,
        "delivered": result.delivered,
        "missing": [
            {"name": e.name, "message": e.message, "status": e.status, "reason": e.reason}
            for e in result.missing
        ],
        "not_delivered": [
            {
                "name": e.name,
                "message": e.message,
                "status": e.status,
                "reason": e.reason,
                "url": e.url,
            }
            for e in result.not_delivered
        ],
        "unlisted": [f.name for f in result.unlisted],
    }
