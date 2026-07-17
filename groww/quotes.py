from groww.auth import get_groww_client

def fetch_option_ltps(positions: list) -> dict:
    ltps = {}
    groww = get_groww_client()
    for pos in positions:
        key = f"{pos['instrument']}_{pos['strike']}_{pos['type']}"
        inst_key = pos.get("instrument_key", "UNKNOWN")
        if inst_key.startswith("MOCK-NSE-"):
            ltps[key] = pos.get("entry", 0)
            try:
                from data.store import store
                store.using_mock_options = True
            except ImportError:
                pass
            continue

        try:
            res = groww.get_ltp(trading_symbol=inst_key)
            ltps[key] = float(res.get("ltp", pos.get("entry", 0)))
        except Exception:
            ltps[key] = pos.get("entry", 0)
            try:
                from data.store import store
                store.using_mock_options = True
            except ImportError:
                pass
    return ltps
