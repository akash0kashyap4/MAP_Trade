"""Google Gemini adapter (free tier) via the Generative Language REST API."""
from __future__ import annotations

from ai.providers.base import BaseProvider, ProviderError


class GeminiProvider(BaseProvider):
    name = "gemini"

    def _generate(self, system: str, user: str, max_tokens: int | None) -> str:
        import requests
        import config

        if not config.GEMINI_API_KEY:
            raise ProviderError(self.name, "GEMINI_API_KEY not set in .env")

        model = config.GEMINI_MODEL
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent")
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": max_tokens or self.settings.max_tokens},
        }
        resp = requests.post(
            url, params={"key": config.GEMINI_API_KEY}, json=payload,
            timeout=self.settings.request_timeout_s,
        )
        if resp.status_code != 200:
            # 400 bad key/model, 429 rate limit, 403 perms — all surfaced structured
            raise ProviderError(self.name, f"HTTP {resp.status_code} model={model}: {resp.text[:200]}")
        cand = (resp.json().get("candidates") or [{}])[0]
        if cand.get("finishReason") == "MAX_TOKENS":
            from config.runtime import get_logger
            get_logger().warning("provider=%s hit maxOutputTokens — output may be truncated", self.name)
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise ProviderError(self.name, f"empty response (finishReason={cand.get('finishReason')})")
        return text

    def health_check(self) -> bool:
        import config
        return bool(config.GEMINI_API_KEY)
