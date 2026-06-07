from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/tests/{task_id}")
async def test_progress_ws(websocket: WebSocket, task_id: str) -> None:
    from backend.app.core.auth import can_access_task, parse_token
    from backend.app.main import progress_hub, repository

    token = websocket.query_params.get("token", "")
    user = parse_token(token)
    item = repository.get_task(task_id)
    if not user or not item or not can_access_task(user, item[0].owner_username):
        await websocket.close(code=1008)
        return

    await progress_hub.connect(task_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await progress_hub.disconnect(task_id, websocket)
    except Exception:
        await progress_hub.disconnect(task_id, websocket)
