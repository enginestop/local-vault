import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..app_context import AppContext
from .. import errors
from ..domain.models import now_utc

router = APIRouter()


@router.websocket("/api/v1/events")
async def events_ws(websocket: WebSocket):
    ctx: AppContext = websocket.app.state.ctx
    ticket = websocket.query_params.get("ticket")
    session = ctx.sessions.consume_ticket(ticket) if ticket else None
    if session is None:
        await websocket.accept()
        await websocket.send_json({"type": "error", "code": "INVALID_TICKET"})
        await websocket.close(code=4401)
        return

    user_id = session.user_id

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    try:
        ctx.sessions.set_ws_connected(session, queue)
    except errors.ProblemError as exc:
        await websocket.accept()
        await websocket.send_json({"type": "error", "code": exc.code})
        await websocket.close(code=4409)
        return

    await websocket.accept()
    current_revision = await ctx.vault.get_current_revision(user_id) if user_id and ctx.vault.is_unlocked(user_id) else 0
    last_seen = current_revision

    async def send_heartbeat():
        while True:
            await asyncio.sleep(20)
            ctx.sessions.touch(session)
            await websocket.send_json({"type": "heartbeat", "occurred_at": now_utc()})

    async def reader():
        nonlocal last_seen
        while True:
            raw = await websocket.receive_text()
            ctx.sessions.touch(session)
            try:
                message = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if message.get("type") == "sync_state":
                try:
                    last_seen = int(message.get("last_seen_vault_revision", last_seen))
                except (TypeError, ValueError):
                    continue
                current = await ctx.vault.get_current_revision(user_id) if user_id and ctx.vault.is_unlocked(user_id) else 0
                if current > last_seen:
                    await websocket.send_json({
                        "event_id": str(uuid.uuid4()),
                        "type": "vault.reload_required",
                        "entity_type": None,
                        "entity_id": None,
                        "entity_revision": None,
                        "vault_revision": current,
                        "occurred_at": now_utc(),
                    })

    heartbeat_task = asyncio.create_task(send_heartbeat())
    reader_task = asyncio.create_task(reader())
    try:
        while True:
            queue_task = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({queue_task, reader_task}, return_when=asyncio.FIRST_COMPLETED)
            if reader_task in done:
                queue_task.cancel()
                break
            event = queue_task.result()
            await websocket.send_json(event)
            if event.get("type") == "vault.locked":
                await websocket.close(code=1000)
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        heartbeat_task.cancel()
        reader_task.cancel()
        ctx.sessions.mark_disconnected(session, queue)
