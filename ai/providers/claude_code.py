"""
Claude Code CLI adapter — shells out to the local `claude` binary (`claude -p`).

Runs the AI brain through an authenticated Claude Code session instead of the
paid API, so it needs no ANTHROPIC_API_KEY. Requires the `claude` CLI to be
installed and logged in on the host (set CLAUDE_CLI_BIN to override the path).
"""
from __future__ import annotations

import os
import shutil
import subprocess

from ai.providers.base import BaseProvider, ProviderError


class ClaudeCodeCLIProvider(BaseProvider):
    name = "claude_code"

    def _build_prompt(self, system: str, user: str) -> str:
        return f"{system}\n\n{user}" if system else user

    def _subprocess_env(self) -> dict:
        # The bot's own process carries ANTHROPIC_API_KEY for the anthropic_api
        # adapter. If that leaks into this subprocess, the claude CLI sees an
        # API key and refuses to use the `claude login` session instead
        # ("connectors are disabled because ANTHROPIC_API_KEY ... takes
        # precedence"). Strip it so the CLI always uses its own login.
        return {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}

    def _generate(self, system: str, user: str, max_tokens: int | None) -> str:
        binary = self.settings.claude_cli_bin
        prompt = self._build_prompt(system, user)
        try:
            proc = subprocess.run(
                [binary, "-p", prompt],
                capture_output=True, text=True,
                timeout=self.settings.request_timeout_s,
                env=self._subprocess_env(),
            )
        except FileNotFoundError as e:
            raise ProviderError(self.name, f"'{binary}' not found — install the Claude Code CLI "
                                           "and/or set CLAUDE_CLI_BIN", cause=e)
        except subprocess.TimeoutExpired as e:
            # kill=True on TimeoutExpired already reaps the child — no zombies left
            raise ProviderError(self.name, f"CLI timed out after {self.settings.request_timeout_s}s", cause=e)
        if proc.returncode != 0:
            raise ProviderError(self.name, f"CLI exit {proc.returncode}: {(proc.stderr or '')[:200]}")
        out = (proc.stdout or "").strip()
        if not out:
            raise ProviderError(self.name, "CLI produced no output")
        return out

    def health_check(self) -> bool:
        return shutil.which(self.settings.claude_cli_bin) is not None
