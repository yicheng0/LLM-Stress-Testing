from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/tests/{task_id}")
async def test_progress_ws(websocket: WebSocket, task_id: str) -> None:
    from backend.app.main import progress_hub

    await progress_hub.connect(task_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await progress_hub.disconnect(task_id, websocket)
    except Exception:
        await progress_hub.disconnect(task_id, websocket)
