from __future__ import annotations

import os
import stat
from pathlib import Path

from get_installer import Journal, JournalEntry


def test_record_and_len() -> None:
    j = Journal()
    j.record(JournalEntry(description="x", undo=lambda: None))
    j.record(JournalEntry(description="y", undo=lambda: None))
    assert len(j) == 2


def test_rollback_runs_in_reverse() -> None:
    order: list[str] = []
    j = Journal()
    j.record(JournalEntry(description="a", undo=lambda: order.append("a")))
    j.record(JournalEntry(description="b", undo=lambda: order.append("b")))
    j.record(JournalEntry(description="c", undo=lambda: order.append("c")))
    assert j.rollback() == 3
    assert order == ["c", "b", "a"]
    assert len(j) == 0


def test_rollback_continues_on_undo_error() -> None:
    seen: list[str] = []

    def boom() -> None:
        raise RuntimeError("boom")

    j = Journal()
    j.record(JournalEntry(description="a", undo=boom))
    j.record(JournalEntry(description="b", undo=lambda: seen.append("b")))
    errors: list[tuple[str, Exception]] = []
    j.rollback(on_error=lambda d, e: errors.append((d, e)))
    # b's undo still ran despite a's failure
    assert seen == ["b"]
    assert errors and errors[0][0] == "a"


def test_commit_clears_journal() -> None:
    ran: list[str] = []
    j = Journal()
    j.record(JournalEntry(description="x", undo=lambda: ran.append("x")))
    j.commit()
    assert j.rollback() == 0
    assert ran == []


def test_make_dir_undo_removes_only_what_we_created(tmp_path: Path) -> None:
    pre_existing = tmp_path / "kept"
    pre_existing.mkdir()
    j = Journal()
    j.make_dir(pre_existing)            # no-op: directory existed
    j.make_dir(tmp_path / "fresh")      # created: undo deletes
    j.rollback()
    assert pre_existing.exists()
    assert not (tmp_path / "fresh").exists()


def test_write_file_undo_restores_previous(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("old")
    j = Journal()
    j.write_file(p, b"new")
    assert p.read_text() == "new"
    j.rollback()
    assert p.read_text() == "old"


def test_write_file_undo_deletes_when_new(tmp_path: Path) -> None:
    p = tmp_path / "fresh.txt"
    j = Journal()
    j.write_file(p, b"hi")
    j.rollback()
    assert not p.exists()


def test_write_log_uses_strict_mode(tmp_path: Path) -> None:
    j = Journal()
    j.record(JournalEntry(description="x", undo=lambda: None))
    log = tmp_path / "log.txt"
    j.write_log(log, mode=0o600)
    mode = stat.S_IMODE(os.stat(log).st_mode)
    # Some filesystems mask group/other bits, but at minimum the owner must read
    assert mode & stat.S_IRUSR
    # And group/other must NOT have read
    assert not (mode & stat.S_IRGRP)
    assert not (mode & stat.S_IROTH)
