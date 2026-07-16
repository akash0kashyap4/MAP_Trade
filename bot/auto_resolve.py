"""
Auto-resolve AI requests when the corresponding feature is already implemented.
Called once at startup. Checks for known feature files/flags and marks matching
open requests as resolved in the DB.
"""
from __future__ import annotations
import importlib
import os


# Map feature_key → check function that returns True if the feature exists
_FEATURE_CHECKS: dict[str, callable] = {}


def _register(key: str):
    def decorator(fn):
        _FEATURE_CHECKS[key] = fn
        return fn
    return decorator


@_register("health_monitor")
def _check_health_monitor() -> bool:
    return os.path.exists(os.path.join(os.path.dirname(__file__), "health_monitor.py"))


@_register("index_breadth")
def _check_breadth() -> bool:
    return os.path.exists(os.path.join(os.path.dirname(__file__), "breadth.py"))


@_register("fallback_bias")
def _check_fallback_bias() -> bool:
    return os.path.exists(os.path.join(os.path.dirname(__file__), "fallback_bias.py"))


async def auto_resolve_implemented_features(db) -> int:
    """
    Check every open AI request. If its feature_key matches a feature that is
    already implemented, mark it resolved. Returns count resolved.
    """
    try:
        requests = await db.get_ai_requests(include_resolved=False)
    except Exception as e:
        print(f"[auto_resolve] Could not load AI requests: {e}")
        return 0

    resolved = 0
    for req in requests:
        key = req.get("feature_key")
        if not key:
            continue
        check = _FEATURE_CHECKS.get(key)
        if check and check():
            try:
                await db.resolve_ai_request(req["id"])
                print(f"[auto_resolve] Resolved '{req['title']}' (key={key})")
                resolved += 1
            except Exception as e:
                print(f"[auto_resolve] Failed to resolve {req['id']}: {e}")

    return resolved
