"""
Ollama adapter — fully local, free models via a local Ollama server.

Talks to the Ollama REST API (default http://localhost:11434). Needs a running
`ollama serve` with the configured model pulled (`ollama pull llama3.1`). Note:
local models need meaningful RAM/CPU (or a GPU); a tiny cloud instance can't run
them — this adapter is aimed at a real local host.
"""
from __future__ import annotations

from ai.providers.base import BaseProvider, ProviderError


class OllamaProvider(BaseProvider):
    name = "ollama"

    def _generate(self, system: str, user: str, max_tokens: int | None) -> str:
        import requests
        url = f"{self.settings.ollama_url}/api/generate"
        payload = {
            "model": self.settings.ollama_model,
            "prompt": user,
            "system": system,
            "stream": False,
            "options": {"num_predict": max_tokens or self.settings.max_tokens},
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.settings.request_timeout_s)
        except Exception as e:
            raise ProviderError(self.name, f"cannot reach Ollama at {self.settings.ollama_url}: {e}", cause=e)
        if resp.status_code != 200:
            raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:200]}")
        text = (resp.json().get("response") or "").strip()
        if not text:
            raise ProviderError(self.name, "empty response")
        return text

    def health_check(self) -> bool:
        import requests
        try:
            return requests.get(f"{self.settings.ollama_url}/api/tags", timeout=5).status_code == 200
        except Exception:
            return False
