from __future__ import annotations
from growwapi import GrowwAPI
from config import GROWW_API_KEY, GROWW_SECRET_KEY

_groww_client = None

def get_groww_client() -> GrowwAPI:
    global _groww_client
    if _groww_client is None:
        if not GROWW_API_KEY or not GROWW_SECRET_KEY:
            raise ValueError("Groww API keys not found in config")
        try:
            access_token = GrowwAPI.get_access_token(api_key=GROWW_API_KEY, secret=GROWW_SECRET_KEY)
            _groww_client = GrowwAPI(access_token)
            print("[groww.auth] ✅ Ready to Groww")
        except Exception as e:
            print(f"[groww.auth] ❌ Failed to authenticate with Groww: {e}")
            raise
    return _groww_client
