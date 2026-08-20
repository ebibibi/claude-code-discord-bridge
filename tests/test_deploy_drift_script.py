"""Regression tests for scripts/check-deploy-drift.sh.

The script exists because a forgotten `make dev-on` kept a side branch in
production while every merged PR appeared to deploy. These exercise the real
shell script against throwaway git repos so the exit codes stay meaningful —
a detector that cannot fail is worth nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check-deploy-drift.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_origin(base: Path) -> Path:
    """A bare 'origin' plus a clone with one commit on main."""
    origin = base / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)

    repo = base / "ccdb"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "claude_discord").mkdir()
    (repo / "claude_discord" / "__init__.py").write_text("")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "push", "-q", "origin", "main")
    return repo


def _run(script_home: Path, repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            "HOME": str(script_home),
            "CCDB_HOME": str(repo),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
        capture_output=True,
        text=True,
    )


def test_no_marker_is_main_tree_mode(tmp_path: Path) -> None:
    repo = _init_origin(tmp_path)
    result = _run(tmp_path, repo)

    assert result.returncode == 0
    assert "main-tree mode" in result.stdout


def test_marker_pointing_nowhere_is_reported_not_silently_ignored(tmp_path: Path) -> None:
    """The import hook falls back to the main tree here — say so, don't pass."""
    repo = _init_origin(tmp_path)
    (tmp_path / ".ccdb-dev-worktree").write_text(str(tmp_path / "gone"))

    result = _run(tmp_path, repo)

    assert result.returncode == 2
    assert "BROKEN" in result.stdout


def test_dev_mode_on_unmerged_branch_is_drift(tmp_path: Path) -> None:
    repo = _init_origin(tmp_path)
    worktree = tmp_path / "wt-dev"
    _git(repo, "worktree", "add", "-q", str(worktree), "-b", "feat/side")
    (worktree / "claude_discord" / "extra.py").write_text("x = 1\n")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", "side work")
    (tmp_path / ".ccdb-dev-worktree").write_text(str(worktree))

    result = _run(tmp_path, repo)

    assert result.returncode == 1
    assert "DRIFT" in result.stdout
    assert "feat/side" in result.stdout


def test_dev_mode_on_merged_branch_is_not_drift(tmp_path: Path) -> None:
    """Dev mode is only a problem when the code isn't on origin/main."""
    repo = _init_origin(tmp_path)
    worktree = tmp_path / "wt-dev"
    _git(repo, "worktree", "add", "-q", str(worktree), "-b", "feat/merged")
    (tmp_path / ".ccdb-dev-worktree").write_text(str(worktree))

    result = _run(tmp_path, repo)

    assert result.returncode == 0
    assert "already merged" in result.stdout


def test_drift_report_counts_commits_left_behind(tmp_path: Path) -> None:
    """The count is the point: it says how many merges never actually shipped."""
    repo = _init_origin(tmp_path)
    worktree = tmp_path / "wt-dev"
    _git(repo, "worktree", "add", "-q", str(worktree), "-b", "feat/side")
    (worktree / "claude_discord" / "extra.py").write_text("x = 1\n")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", "side work")
    (tmp_path / ".ccdb-dev-worktree").write_text(str(worktree))

    for n in range(2):
        (repo / f"merged{n}.py").write_text("y = 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"merged pr {n}")
    _git(repo, "push", "-q", "origin", "main")

    result = _run(tmp_path, repo)

    assert result.returncode == 1
    assert "behind   : 2 commit(s)" in result.stdout


def test_script_is_executable() -> None:
    assert SCRIPT.stat().st_mode & 0o111
