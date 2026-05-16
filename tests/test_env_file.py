"""Tests for the .env loader (SPEC Phase L)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from get_installer.env_file import load_env_file


def test_load_env_file_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOO_PHASE_L", raising=False)
    p = tmp_path / ".env"
    p.write_text("FOO_PHASE_L=bar\n", encoding="utf-8")
    applied = load_env_file(p)
    assert applied == {"FOO_PHASE_L": "bar"}
    assert os.environ["FOO_PHASE_L"] == "bar"


def test_load_env_file_does_not_override_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PREEXISTING_PHASE_L", "from-shell")
    p = tmp_path / ".env"
    p.write_text("PREEXISTING_PHASE_L=from-file\n", encoding="utf-8")
    applied = load_env_file(p)
    assert applied == {}
    assert os.environ["PREEXISTING_PHASE_L"] == "from-shell"


def test_load_env_file_strips_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A_PHASE_L", raising=False)
    monkeypatch.delenv("B_PHASE_L", raising=False)
    p = tmp_path / ".env"
    p.write_text('A_PHASE_L="hello"\nB_PHASE_L=\'world\'\n', encoding="utf-8")
    load_env_file(p)
    assert os.environ["A_PHASE_L"] == "hello"
    assert os.environ["B_PHASE_L"] == "world"


def test_load_env_file_skips_comments_and_blanks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OK_PHASE_L", raising=False)
    p = tmp_path / ".env"
    p.write_text(
        "# a comment\n\n   # indented comment\nOK_PHASE_L=yes\n",
        encoding="utf-8",
    )
    applied = load_env_file(p)
    assert applied == {"OK_PHASE_L": "yes"}


def test_load_env_file_raises_on_malformed(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("no equals here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected KEY=VALUE"):
        load_env_file(p)


def test_load_env_file_explicit_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_env_file(tmp_path / "does-not-exist.env")


def test_load_env_file_default_search_silent_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default search (no path) is silent when no .env is found."""
    monkeypatch.delenv("GET_INSTALLER_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    applied = load_env_file()
    assert applied == {}


def test_load_env_file_picks_up_cwd_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GET_INSTALLER_ENV_FILE", raising=False)
    monkeypatch.delenv("CWD_DISCOVERY_PHASE_L", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("CWD_DISCOVERY_PHASE_L=ok\n", encoding="utf-8")
    applied = load_env_file()
    assert applied == {"CWD_DISCOVERY_PHASE_L": "ok"}


def test_load_env_file_env_var_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ENVVAR_POINTER_PHASE_L", raising=False)
    target = tmp_path / "elsewhere.env"
    target.write_text("ENVVAR_POINTER_PHASE_L=via-env-var\n", encoding="utf-8")
    monkeypatch.setenv("GET_INSTALLER_ENV_FILE", str(target))
    monkeypatch.chdir(tmp_path)
    applied = load_env_file()
    assert applied == {"ENVVAR_POINTER_PHASE_L": "via-env-var"}
