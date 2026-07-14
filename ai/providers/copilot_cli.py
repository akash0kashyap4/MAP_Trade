"""
GitHub Copilot CLI adapter (adapter-ready).

Shells out to the Copilot CLI. The exact invocation depends on which Copilot CLI
is installed (`copilot -p "…"`, or the older `gh copilot suggest`), so the
command is configurable via COPILOT_CLI_BIN / COPILOT_CLI_ARGS. health_check
reports whether the binary is present; wire the precise prompt flags for your
installed version before switching the default provider to this.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from ai.providers.base import BaseProvider, ProviderError


class CopilotCLIProvider(BaseProvider):
    name = "copilot_cli"

    def _generate(self, system: str, user: str, max_tokens: int | None) -> str:
        binary = self.settings.copilot_cli_bin
        prompt = f"{system}\n\n{user}" if system else user
        # COPILOT_CLI_ARGS lets you adapt to your installed CLI without code changes,
        # e.g. "-p" (new Copilot CLI) or "suggest -t shell" (gh copilot).
        extra = os.getenv("COPILOT_CLI_ARGS", "-p").split()
        try:
            proc = subprocess.run(
                [binary, *extra, prompt],
                capture_output=True, text=True,
                timeout=self.settings.request_timeout_s,
            )
        except FileNotFoundError as e:
            raise ProviderError(self.name, f"'{binary}' not found — install the GitHub Copilot CLI "
                                           "and/or set COPILOT_CLI_BIN", cause=e)
        except subprocess.TimeoutExpired as e:
            raise ProviderError(self.name, f"CLI timed out after {self.settings.request_timeout_s}s", cause=e)
        if proc.returncode != 0:
            raise ProviderError(self.name, f"CLI exit {proc.returncode}: {(proc.stderr or '')[:200]}")
        out = (proc.stdout or "").strip()
        if not out:
            raise ProviderError(self.name, "CLI produced no output")
        return out

    def health_check(self) -> bool:
        return shutil.which(self.settings.copilot_cli_bin) is not None
