"""Terminal UI primitives: colour, headers, steps, prompts.

Single ``UI`` class wraps stdout/stderr. Detects TTY + NO_COLOR. Honours
``--yes`` (assume default) and ``--quiet`` flags. All prompts call into
``UI.confirm()`` / ``UI.ask()`` / ``UI.choose()`` so tests can swap the
class with a recording stub.
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Any


class UI:
    # ANSI colour codes. Empty strings when colour is disabled.
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    def __init__(
        self,
        *,
        assume_yes: bool = False,
        quiet: bool = False,
        no_color: bool | None = None,
        stream: Any = None,
        input_fn: Any = None,
    ) -> None:
        self.assume_yes = assume_yes
        self.quiet = quiet
        self._stream = stream if stream is not None else sys.stdout
        self._input = input_fn if input_fn is not None else input
        if no_color is None:
            no_color = bool(os.environ.get("NO_COLOR")) or not self._stream.isatty()
        self.no_color = no_color
        if no_color:
            for attr in ("BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "CYAN", "RESET"):
                # Per-instance override so class default isn't mutated.
                object.__setattr__(self, attr, "")

    # ---- output ------------------------------------------------------

    def print(self, msg: str = "", end: str = "\n") -> None:
        if self.quiet:
            return
        self._stream.write(msg + end)
        self._stream.flush()

    def header(self, title: str, subtitle: str = "") -> None:
        bar = "─" * max(len(title), len(subtitle))
        self.print()
        self.print(f"{self.BOLD}{title}{self.RESET}")
        if subtitle:
            self.print(f"{self.DIM}{subtitle}{self.RESET}")
        self.print(f"{self.DIM}{bar}{self.RESET}")

    def step(self, n: int, total: int, label: str) -> None:
        self.print(f"\n{self.BOLD}[{n}/{total}]{self.RESET} {label}")

    def ok(self, msg: str) -> None:
        self.print(f"  {self.GREEN}ok{self.RESET}    {msg}")

    def skip(self, msg: str) -> None:
        self.print(f"  {self.DIM}skip{self.RESET}  {msg}")

    def warn(self, msg: str) -> None:
        # Warnings go to stderr so they survive `--quiet`-style stdout filtering.
        sys.stderr.write(f"  {self.YELLOW}warn{self.RESET}  {msg}\n")
        sys.stderr.flush()

    def fail(self, msg: str) -> None:
        sys.stderr.write(f"  {self.RED}fail{self.RESET}  {msg}\n")
        sys.stderr.flush()

    def info(self, msg: str) -> None:
        self.print(f"  {self.CYAN}info{self.RESET}  {msg}")

    def detail(self, msg: str) -> None:
        self.print(f"        {self.DIM}{msg}{self.RESET}")

    # ---- prompts -----------------------------------------------------

    def confirm(self, question: str, default: bool = True) -> bool:
        if self.assume_yes:
            return default
        if not sys.stdin.isatty():
            return default
        hint = "[Y/n]" if default else "[y/N]"
        try:
            ans = self._input(f"  {self.BOLD}?{self.RESET} {question} {hint} ").strip().lower()
        except EOFError:
            return default
        if not ans:
            return default
        return ans in ("y", "yes")

    def ask(self, question: str, default: str = "", secret: bool = False) -> str:
        if self.assume_yes:
            return default
        if not sys.stdin.isatty():
            return default
        hint = f" [{default}]" if default else ""
        try:
            if secret:
                ans = getpass.getpass(f"  ? {question}{hint}: ")
            else:
                ans = self._input(f"  {self.BOLD}?{self.RESET} {question}{hint}: ").strip()
        except EOFError:
            return default
        return ans or default

    def choose(self, question: str, choices: list[str], default: str = "") -> str:
        if self.assume_yes:
            return default or choices[0]
        if not sys.stdin.isatty():
            return default or choices[0]
        self.print(f"  {self.BOLD}?{self.RESET} {question}")
        for i, c in enumerate(choices, 1):
            mark = " (default)" if c == default else ""
            self.print(f"      {i}) {c}{mark}")
        while True:
            try:
                ans = self._input("    choice: ").strip()
            except EOFError:
                return default or choices[0]
            if not ans:
                return default or choices[0]
            if ans.isdigit():
                idx = int(ans)
                if 1 <= idx <= len(choices):
                    return choices[idx - 1]
            if ans in choices:
                return ans
            self.warn(f"invalid choice: {ans!r}")

    # ---- summary box -------------------------------------------------

    def summary_box(self, lines: list[str], title: str = "") -> None:
        if not lines:
            return
        width = max(len(line) for line in lines + ([title] if title else []))
        bar = "─" * (width + 2)
        self.print()
        self.print(f"┌{bar}┐")
        if title:
            self.print(f"│ {self.BOLD}{title.ljust(width)}{self.RESET} │")
            self.print(f"├{bar}┤")
        for line in lines:
            self.print(f"│ {line.ljust(width)} │")
        self.print(f"└{bar}┘")
