"""The main install flow.

Composes config + ui + journal + verify into a single ``Installer`` class.

Phases:
  1. Validate environment (Python version, refuse-root, PATH guard, required commands)
  2. Plan + confirm (or skip with --yes)
  3. Install package (pipx / uv tool / pip --user, picked by install_method)
  4. Clone content_repo (optional)
  5. Run prompts
  6. Execute post_install commands
  7. Print next steps + summary

On any failure between phases 3-6, the journal rolls back. Signals
(SIGINT/SIGTERM) are caught and trigger rollback.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType

from .config import AccessControl, InstallConfig, PostInstallStep, Prompt, RateLimits
from .journal import Journal
from .ui import UI
from .verify import (
    SecurityError,
    check_path_injection,
    python_version_at_least,
    refuse_root,
)


@dataclass(frozen=True)
class InstallReport:
    success: bool
    package_installed: bool = False
    content_cloned: bool = False
    post_install_ran: int = 0
    rolled_back: int = 0
    prompts_answered: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    log_path: Path | None = None

    def summary(self) -> str:
        if self.success:
            return "install OK"
        return f"install FAILED: {self.error} (rolled back {self.rolled_back} actions)"


class Installer:
    """Drive an installation end-to-end."""

    PHASES = 7

    def __init__(
        self,
        config: InstallConfig,
        *,
        ui: UI | None = None,
        allow_root: bool = False,
        dry_run: bool = False,
        with_python: bool = False,
        rate_limits: RateLimits | None = None,
        access_control: AccessControl | None = None,
    ) -> None:
        self.config = config
        self.ui = ui or UI()
        self.allow_root = allow_root
        self.dry_run = dry_run
        self.with_python = with_python
        self.rate_limits = rate_limits or RateLimits()
        self.access_control = access_control or AccessControl()
        self.journal = Journal()
        self._prompt_answers: dict[str, str] = {}

    # ---- entry point ------------------------------------------------

    def run(self) -> InstallReport:
        log_path = Path(tempfile.gettempdir()) / f"simtabi-installer-{self.config.product}.log"
        self._install_signal_handlers()
        try:
            self._banner()
            self._phase_validate()
            self._phase_plan()
            if self.dry_run:
                self.ui.summary_box(
                    ["dry-run complete — no changes made"],
                    title=self.config.product,
                )
                return InstallReport(success=True)
            self._phase_install_package()
            self._phase_clone_content()
            self._phase_prompts()
            ran = self._phase_post_install()
            self._phase_next_steps()
            self.journal.write_log(log_path, mode=self.access_control.log_mode)
            self.journal.commit()
            return InstallReport(
                success=True,
                package_installed=True,
                content_cloned=self.config.content_repo is not None,
                post_install_ran=ran,
                prompts_answered=dict(self._prompt_answers),
                log_path=log_path,
            )
        except KeyboardInterrupt:
            return self._abort("interrupted", log_path)
        except SecurityError as e:
            return self._abort(f"security: {e}", log_path)
        except Exception as e:
            return self._abort(str(e), log_path)

    def _abort(self, reason: str, log_path: Path) -> InstallReport:
        self.ui.fail(reason)
        rolled_back = self.journal.rollback(
            on_error=lambda desc, exc: self.ui.warn(f"rollback {desc}: {exc}")
        )
        import contextlib as _ctx
        with _ctx.suppress(Exception):
            self.journal.write_log(log_path, mode=self.access_control.log_mode)
        return InstallReport(
            success=False,
            rolled_back=rolled_back,
            prompts_answered=dict(self._prompt_answers),
            error=reason,
            log_path=log_path,
        )

    # ---- signal handlers --------------------------------------------

    def _install_signal_handlers(self) -> None:
        def handler(signum: int, _frame: FrameType | None) -> None:
            raise KeyboardInterrupt
        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except (ValueError, OSError):
            # Not in main thread; skip. The default handlers will fire.
            pass

    # ---- phases -----------------------------------------------------

    def _banner(self) -> None:
        self.ui.header(
            f"{self.config.product} installer",
            f"v{self.config.version}  ({self.config.package}=={self.config.package_version} via {self.config.install_method})",
        )

    def _phase_validate(self) -> None:
        self.ui.step(1, self.PHASES, "Validating environment")

        refuse_root(allow=self.allow_root)

        if not python_version_at_least(*self.config.min_python):
            min_str = ".".join(str(n) for n in self.config.min_python)
            running = ".".join(str(n) for n in sys.version_info[:2])
            if self.with_python:
                self.ui.info(f"Python {running} below required {min_str}; --with-python set")
                from . import python_setup as ps
                if not ps.can_bootstrap():
                    raise SecurityError(
                        "uv is not installed; cannot bootstrap Python. "
                        "Install uv (https://docs.astral.sh/uv/) or install Python manually."
                    )
                path = ps.install_via_uv(min_str)
                self.ui.ok(f"installed Python {min_str} via uv at {path}")
                self.ui.info("re-run this installer using that Python:")
                self.ui.detail(f"{path} {' '.join(sys.argv)}")
                raise SystemExit(0)
            raise SecurityError(
                f"Python {min_str}+ required; running {running}. "
                f"Install Python first, or pass --with-python to bootstrap via uv."
            )
        self.ui.ok(f"Python {'.'.join(str(n) for n in sys.version_info[:3])}")

        for warn in check_path_injection():
            self.ui.warn(warn)

        for cmd in self.config.required_commands:
            if not shutil.which(cmd):
                raise SecurityError(f"required command not on PATH: {cmd}")
            self.ui.ok(f"{cmd} on PATH ({shutil.which(cmd)})")

        for cmd in self.config.optional_commands:
            if shutil.which(cmd):
                self.ui.ok(f"{cmd} on PATH ({shutil.which(cmd)})")
            else:
                self.ui.skip(f"{cmd} not on PATH (optional)")

    def _phase_plan(self) -> None:
        self.ui.step(2, self.PHASES, "Plan")
        self.ui.info(f"package:        {self.config.package}=={self.config.version}")
        self.ui.info(f"install_method: {self.config.install_method}")
        if self.config.content_repo is not None:
            self.ui.info(f"content repo:   {self.config.content_repo.url}")
        if self.config.post_install:
            self.ui.info("post_install:")
            for step in self.config.post_install:
                gate = f"  [if {step.if_expr}]" if step.if_expr else ""
                self.ui.detail(" ".join(step.argv) + gate)
        if not self.dry_run and not self.ui.confirm("proceed?", default=True):
            raise SecurityError("user declined plan")

    def _phase_install_package(self) -> None:
        pkg = self.config.package
        pkg_pin = f"{pkg}=={self.config.package_version}"
        self.ui.step(3, self.PHASES, f"Installing {pkg_pin}")
        method = self._resolve_method()
        self.ui.info(f"using {method}")
        if method == "pipx":
            self._run_install_cmd(["pipx", "install", pkg_pin])
            self.journal.pipx_install(pkg)
        elif method == "uv-tool":
            self._run_install_cmd(["uv", "tool", "install", pkg_pin])
            self.journal.uv_tool_install(pkg)
        elif method == "pip-user":
            self._run_install_cmd(
                [sys.executable, "-m", "pip", "install", "--user", pkg_pin]
            )
            self.journal.pip_user_install(pkg)
        else:
            raise SecurityError(f"unknown install_method: {method}")
        self.ui.ok(f"{pkg_pin} installed")

    def _resolve_method(self) -> str:
        if self.config.install_method == "auto":
            if shutil.which("pipx"):
                return "pipx"
            if shutil.which("uv"):
                return "uv-tool"
            return "pip-user"
        return self.config.install_method

    def _phase_clone_content(self) -> None:
        repo = self.config.content_repo
        if repo is None:
            return
        self.ui.step(4, self.PHASES, "Cloning content repo")
        target = Path(repo.target).expanduser()
        if target.exists():
            self.ui.skip(f"{target} already exists; not re-cloning")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["git", "clone", "--branch", repo.ref, repo.url, str(target)],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            if repo.optional:
                self.ui.warn(f"clone failed (optional): {r.stderr.strip()}")
                return
            raise SecurityError(f"clone failed: {r.stderr.strip()}")
        self.journal.git_clone(target)
        self.ui.ok(f"cloned to {target}")

    def _phase_prompts(self) -> None:
        if not self.config.prompts:
            return
        self.ui.step(5, self.PHASES, "Configuration")
        for prompt in self.config.prompts:
            self._prompt_answers[prompt.key] = self._ask_prompt(prompt)

    def _ask_prompt(self, prompt: Prompt) -> str:
        if prompt.type == "yes_no":
            default_bool = bool(prompt.default) if prompt.default is not None else True
            return "yes" if self.ui.confirm(prompt.question, default=default_bool) else "no"
        default_str = prompt.default if isinstance(prompt.default, str) else ""
        if prompt.type == "choice":
            return self.ui.choose(prompt.question, list(prompt.choices), default=default_str)
        return self.ui.ask(prompt.question, default=default_str, secret=prompt.secret)

    def _phase_post_install(self) -> int:
        if not self.config.post_install:
            return 0
        self.ui.step(6, self.PHASES, "Post-install")
        ran = 0
        for step in self.config.post_install:
            cmd_str = " ".join(step.argv)
            if not self._gate_passes(step):
                self.ui.skip(f"{cmd_str} (gate {step.if_expr!r} not met)")
                continue
            self.ui.detail(cmd_str)
            r = subprocess.run(list(step.argv), check=False)
            if r.returncode != 0:
                raise SecurityError(
                    f"post_install command failed (exit {r.returncode}): {cmd_str}"
                )
            ran += 1
            self.ui.ok(cmd_str)
        return ran

    def _gate_passes(self, step: PostInstallStep) -> bool:
        """``step.if_expr`` is ``key=value`` — passes when answer matches."""
        if step.if_expr is None:
            return True
        key, _, expected = step.if_expr.partition("=")
        actual = self._prompt_answers.get(key.strip(), "")
        return actual == expected.strip()

    def _phase_next_steps(self) -> None:
        self.ui.step(7, self.PHASES, "Done")
        if self.config.next_steps:
            self.ui.summary_box(list(self.config.next_steps), title="next steps")
        else:
            self.ui.ok(f"{self.config.product} {self.config.version} installed")

    # ---- helpers ----------------------------------------------------

    def _run_install_cmd(self, cmd: list[str]) -> None:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            raise SecurityError(
                f"command failed: {' '.join(cmd)}\n  {r.stderr.strip() or r.stdout.strip()}"
            )
