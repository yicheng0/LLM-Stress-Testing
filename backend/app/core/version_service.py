from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.config import settings


REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
SAFE_WORKTREE_DIR_PREFIXES = (
    ".claude/",
    ".idea/",
    "__pycache__/",
    "backend/__pycache__/",
    "backend/app/__pycache__/",
    "frontend/dist/",
    "frontend/node_modules/",
    "frontend/node_modules/.vite/",
    "results/",
    "data/",
)
SAFE_WORKTREE_FILE_SUFFIXES = (".log", ".err.log", ".out.log", ".pyc", ".pyo")


@dataclass
class VersionSnapshot:
    available: bool
    update_enabled: bool
    current_version: str
    current_ref: str | None
    latest_ref: str | None
    branch: str | None
    remote_url: str | None
    ahead_count: int | None
    behind_count: int | None
    dirty: bool | None
    update_available: bool
    message: str | None
    dirty_paths: list[str] | None
    checked_at: datetime

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_at"] = self.checked_at
        return data


def _run_command(args: list[str], *, cwd: Path = REPO_ROOT, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )


def _run_git(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return _run_command(["git", *args], timeout=timeout)


def _git_available() -> bool:
    try:
        _run_git(["--version"], timeout=10)
        return True
    except Exception:
        return False


def _read_frontend_version() -> str:
    try:
        data = json.loads(FRONTEND_PACKAGE_JSON.read_text(encoding="utf-8"))
        version = str(data.get("version") or "").strip()
        if version:
            return version
    except Exception:
        pass
    return "unknown"


def _short_ref(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value[:12] if len(value) > 12 else value


def _status_entries() -> list[tuple[str, str]]:
    raw = _run_git(["status", "--porcelain=v1", "-z"], timeout=30).stdout
    if not raw:
        return []
    entries: list[tuple[str, str]] = []
    items = raw.split("\0")
    index = 0
    while index < len(items):
        item = items[index]
        if not item:
            index += 1
            continue
        status = item[:2]
        path = item[3:]
        if status[:1] in {"R", "C"}:
            index += 1
            if index < len(items) and items[index]:
                path = items[index]
        entries.append((status, path))
        index += 1
    return entries


def _normalize_status_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def _is_safe_worktree_path(path: str) -> bool:
    normalized = _normalize_status_path(path)
    if not normalized:
        return False
    if normalized.startswith(SAFE_WORKTREE_DIR_PREFIXES):
        return True
    if normalized.endswith(SAFE_WORKTREE_FILE_SUFFIXES):
        return True
    return False


def _classify_worktree_changes() -> tuple[list[str], list[str]]:
    protected: list[str] = []
    ignored: list[str] = []
    for _status, path in _status_entries():
        normalized = _normalize_status_path(path)
        if _is_safe_worktree_path(normalized):
            ignored.append(normalized)
        else:
            protected.append(normalized)
    return protected, ignored


def _format_paths(paths: list[str], *, limit: int = 5) -> str:
    if not paths:
        return ""
    visible = paths[:limit]
    suffix = f" 等 {len(paths)} 个文件" if len(paths) > limit else ""
    return "，".join(visible) + suffix


def _resolve_branch() -> str | None:
    try:
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        return branch if branch and branch != "HEAD" else None
    except Exception:
        return None


def _resolve_remote_upstream(branch: str | None) -> str | None:
    try:
        upstream = _run_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]).stdout.strip()
        if upstream:
            return upstream
    except Exception:
        pass
    if branch:
        return f"origin/{branch}"
    return None


def get_version_snapshot(*, fetch: bool = False) -> VersionSnapshot:
    current_version = _read_frontend_version()
    checked_at = datetime.utcnow()

    if not (REPO_ROOT / ".git").exists() or not _git_available():
        return VersionSnapshot(
            available=False,
            update_enabled=settings.self_update_enabled,
            current_version=current_version,
            current_ref=None,
            latest_ref=None,
            branch=None,
            remote_url=None,
            ahead_count=None,
            behind_count=None,
            dirty=None,
            update_available=False,
            message="当前环境未检测到 Git 仓库，无法在线检查更新。",
            dirty_paths=None,
            checked_at=checked_at,
        )

    if fetch:
        _run_git(["fetch", "--tags", "origin"], timeout=60)

    branch = _resolve_branch()
    remote_url = None
    try:
        remote_url = _run_git(["remote", "get-url", "origin"]).stdout.strip() or None
    except Exception:
        remote_url = None

    latest_ref = None
    ahead_count = None
    behind_count = None
    dirty = None
    dirty_paths: list[str] | None = None
    message = None
    update_available = False

    upstream = _resolve_remote_upstream(branch)
    if upstream:
        try:
            latest_ref = _run_git(["describe", "--tags", "--always", upstream], timeout=30).stdout.strip() or None
        except Exception:
            try:
                latest_ref = _short_ref(_run_git(["rev-parse", upstream], timeout=30).stdout.strip())
            except Exception:
                latest_ref = None

        try:
            count_output = _run_git(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"], timeout=30).stdout.strip()
            ahead_text, behind_text = count_output.split()
            ahead_count = int(ahead_text)
            behind_count = int(behind_text)
            update_available = behind_count > 0
        except Exception:
            message = "已获取远端信息，但无法计算差异。"
    else:
        message = "未找到可用的上游分支。"

    protected_paths: list[str] = []
    ignored_paths: list[str] = []
    try:
        protected_paths, ignored_paths = _classify_worktree_changes()
        dirty = bool(protected_paths)
        dirty_paths = protected_paths or None
    except Exception:
        dirty = None
        dirty_paths = None
        protected_paths = []
        ignored_paths = []

    current_ref = None
    try:
        if dirty:
            current_ref = _run_git(["describe", "--tags", "--always", "--dirty"], timeout=30).stdout.strip() or None
        else:
            current_ref = _run_git(["describe", "--tags", "--always"], timeout=30).stdout.strip() or None
    except Exception:
        try:
            current_ref = _short_ref(_run_git(["rev-parse", "HEAD"], timeout=30).stdout.strip())
        except Exception:
            current_ref = None

    if protected_paths:
        message = f"工作区存在未提交的源码或配置修改，无法自动更新：{_format_paths(protected_paths)}"
    elif update_available:
        if ignored_paths:
            message = f"检测到远端有新版本。当前存在 {len(ignored_paths)} 个运行产物变更，已忽略，不影响在线更新。"
        else:
            message = "检测到远端有新版本。"
    elif message is None:
        if ignored_paths:
            message = f"当前已是最新版本。当前存在 {len(ignored_paths)} 个运行产物变更，已忽略。"
        else:
            message = "当前已是最新版本。"

    if not settings.self_update_enabled:
        if update_available:
            message = "检测到远端有新版本，但在线更新未启用。"
        elif message == "当前已是最新版本。":
            message = "当前已是最新版本。在线更新未启用。"

    return VersionSnapshot(
        available=True,
        update_enabled=settings.self_update_enabled,
        current_version=current_version,
        current_ref=current_ref,
        latest_ref=latest_ref,
        branch=branch,
        remote_url=remote_url,
        ahead_count=ahead_count,
        behind_count=behind_count,
        dirty=dirty,
        update_available=update_available,
        message=message,
        dirty_paths=dirty_paths,
        checked_at=checked_at,
    )


def _default_update_steps(branch: str | None) -> list[tuple[list[str], Path]]:
    pull_command = ["git", "pull", "--ff-only", "--autostash"]
    if branch:
        pull_command.extend(["origin", branch])
    steps: list[tuple[list[str], Path]] = [(pull_command, REPO_ROOT)]
    steps.append(([sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"], REPO_ROOT))
    frontend_dir = REPO_ROOT / "frontend"
    if (frontend_dir / "package.json").exists():
        steps.append((["npm", "install"], frontend_dir))
        steps.append((["npm", "run", "build"], frontend_dir))
    return steps


def run_self_update(branch: str | None = None) -> tuple[str, str]:
    if settings.self_update_command:
        command = ["cmd", "/c", settings.self_update_command] if os.name == "nt" else ["/bin/sh", "-lc", settings.self_update_command]
        result = _run_command(command, timeout=settings.self_update_timeout_sec)
        return result.stdout.strip(), result.stderr.strip()

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    for step, cwd in _default_update_steps(branch):
        result = _run_command(step, cwd=cwd, timeout=settings.self_update_timeout_sec)
        if result.stdout.strip():
            stdout_parts.append(result.stdout.strip())
        if result.stderr.strip():
            stderr_parts.append(result.stderr.strip())
    return "\n".join(stdout_parts).strip(), "\n".join(stderr_parts).strip()
