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
    last_heartbeat = asyncio.get_event_loop().time()

    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(q.get(), timeout=1.0)
                yield f"data: {json.dumps(payload)}\n\n"
            except asyncio.TimeoutError:
                now = asyncio.get_event_loop().time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
            except Exception:
                break
    finally:
        _subscribers.discard(q)


def sse_endpoint(request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
