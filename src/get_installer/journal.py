"""Action journal + rollback (the garbage collector).

Every state-changing step records a ``JournalEntry`` with an ``undo``
callback. On signal (SIGINT/SIGTERM) or unhandled exception, the
installer walks the journal in reverse and invokes each ``undo``.

Failures inside ``undo`` are logged but do not abort the rollback —
we want to get as much cleanup done as possible.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class JournalEntry:
    description: str
    undo: Callable[[], None]
    detail: str = ""


class Journal:
    """Append-only ledger of reversible actions."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    def record(self, entry: JournalEntry) -> None:
        self._entries.append(entry)

    def rollback(self, *, on_error: Callable[[str, Exception], None] | None = None) -> int:
        """Run every undo in reverse. Returns count of undos performed."""
        count = 0
        for entry in reversed(self._entries):
            try:
                entry.undo()
                count += 1
            except Exception as e:
                if on_error is not None:
                    on_error(entry.description, e)
                else:
                    sys.stderr.write(f"rollback error in {entry.description!r}: {e}\n")
        self._entries.clear()
        return count

    def commit(self) -> None:
        """Mark every recorded action as final — clears the journal so rollback is a no-op."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    # ---- common reversible actions ----------------------------------

    def make_dir(self, path: Path) -> None:
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        if not existed:
            self.record(JournalEntry(
                description=f"created dir {path}",
                undo=lambda: shutil.rmtree(path, ignore_errors=True),
            ))

    def write_file(self, path: Path, content: bytes, *, mode: int = 0o600) -> None:
        """Atomically write ``content`` to ``path`` with explicit ``mode``.

        Default ``mode`` is ``0o600`` — owner-only — because installer-
        written content tends to be private (logs, intermediate state).
        Callers that need a wider mode (e.g., a generated `install.sh`
        an end user must execute) pass ``mode=0o644``.

        Records an undo that restores the previous bytes (or removes
        the file when it didn't previously exist).
        """
        existed = path.exists()
        previous: bytes | None = path.read_bytes() if existed else None
        previous_mode: int | None = path.stat().st_mode & 0o777 if existed else None
        path.write_bytes(content)
        # Mode is best-effort on filesystems that don't honour it (Windows
        # NTFS without ACL helpers, FAT, network mounts).
        with contextlib.suppress(OSError):
            os.chmod(path, mode)

        def undo() -> None:
            if previous is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_bytes(previous)
                if previous_mode is not None:
                    with contextlib.suppress(OSError):
                        os.chmod(path, previous_mode)

        self.record(JournalEntry(
            description=f"wrote {path}",
            undo=undo,
        ))

    def pipx_install(self, package: str) -> None:
        def undo() -> None:
            # Best effort — uninstall if pipx is around.
            if shutil.which("pipx"):
                subprocess.run(
                    ["pipx", "uninstall", package],
                    capture_output=True, text=True, check=False,
                )

        self.record(JournalEntry(
            description=f"pipx install {package}",
            undo=undo,
        ))

    def uv_tool_install(self, package: str) -> None:
        def undo() -> None:
            if shutil.which("uv"):
                subprocess.run(
                    ["uv", "tool", "uninstall", package],
                    capture_output=True, text=True, check=False,
                )

        self.record(JournalEntry(
            description=f"uv tool install {package}",
            undo=undo,
        ))

    def pip_user_install(self, package: str) -> None:
        def undo() -> None:
            subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", package],
                capture_output=True, text=True, check=False,
            )

        self.record(JournalEntry(
            description=f"pip install --user {package}",
            undo=undo,
        ))

    def git_clone(self, target: Path) -> None:
        def undo() -> None:
            if target.exists() and target.is_dir():
                shutil.rmtree(target, ignore_errors=True)

        self.record(JournalEntry(
            description=f"git clone -> {target}",
            undo=undo,
        ))

    def custom(self, description: str, undo: Callable[[], None], detail: str = "") -> None:
        self.record(JournalEntry(description=description, undo=undo, detail=detail))

    # ---- diagnostics ------------------------------------------------

    def write_log(self, path: Path, mode: int = 0o600) -> None:
        """Write a human-readable transcript of the journal to ``path``.

        Uses ``O_CREAT|O_EXCL`` + the given mode so other users on the
        machine can't read it (a tmp-dir hijack would otherwise win the
        race). Default ``mode`` is 0600 — owner only.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# Installer journal\n\n")
            for i, entry in enumerate(self._entries, 1):
                f.write(f"{i}. {entry.description}\n")
                if entry.detail:
                    f.write(f"   {entry.detail}\n")
