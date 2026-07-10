from __future__ import annotations
import asyncio
import json

from fastapi import Request
from fastapi.responses import StreamingResponse

HEARTBEAT_INTERVAL = 30

# Each connected SSE client gets its own queue; push loop broadcasts to all.
_subscribers: set[asyncio.Queue] = set()


async def broadcast(payload: dict):
    """Push payload to every connected SSE client."""
    print(f"[sse.broadcast] Broadcasting to {len(_subscribers)} subscribers (set_id={id(_subscribers)})")
    dead: set[asyncio.Queue] = set()
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _subscribers.difference_update(dead)


async def sse_generator(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    _subscribers.add(q)
    print(f"[sse.generator] Subscriber added. Total subscribers: {len(_subscribers)} (set_id={id(_subscribers)})")
    last_heartbeat = asyncio.get_event_loop().time()

    try:
        # Yield the current store payload immediately so the browser is populated instantly
        from data.store import store
        initial_payload = store.sse_payload()
        yield f"data: {json.dumps(initial_payload)}\n\n"

        while True:
            if await request.is_disconnected():
                print("[sse.generator] Client disconnected")
                break
            try:
                payload = await asyncio.wait_for(q.get(), timeout=1.0)
                yield f"data: {json.dumps(payload)}\n\n"
            except asyncio.TimeoutError:
                now = asyncio.get_event_loop().time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
            except Exception as e:
                print(f"[sse.generator] Error in generator: {e}")
                break
    finally:
        _subscribers.discard(q)
        print(f"[sse.generator] Subscriber removed. Remaining: {len(_subscribers)} (set_id={id(_subscribers)})")


def sse_endpoint(request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
