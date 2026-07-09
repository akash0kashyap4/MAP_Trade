import asyncio
from groww.auth import get_groww_client
from data.store import store

async def start_feed():
    store.feed_status = "live"
    print("[groww.feed] Starting REST polling feed...")
    while True:
        await asyncio.sleep(5)
        pass

def request_option_subscribe(instrument_key: str):
    pass
