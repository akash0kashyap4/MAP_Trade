from groww.auth import get_groww_client

def fetch_option_ltps(positions: list) -> dict:
    ltps = {}
    groww = get_groww_client()
    for pos in positions:
        key = f"{pos['instrument']}_{pos['strike']}_{pos['type']}"
        try:
            res = groww.get_ltp(trading_symbol=pos.get("instrument_key", "UNKNOWN"))
            ltps[key] = float(res.get("ltp", pos.get("entry", 0)))
        except:
            ltps[key] = pos.get("entry", 0)
    return ltps
