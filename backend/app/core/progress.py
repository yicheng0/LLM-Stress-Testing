from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

from fastapi import WebSocket


class ProgressHub:
    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._events: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=50))
        self._clients: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    def snapshot(self, task_id: str) -> dict[str, Any] | None:
        return self._snapshots.get(task_id)

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return list(self._events.get(task_id, []))

    async def connect(self, task_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients[task_id].add(websocket)

        snapshot = self.snapshot(task_id)
        if snapshot:
            await websocket.send_json({"type": "progress", "test_id": task_id, "data": snapshot})
        for event in self.events(task_id):
            await websocket.send_json({"type": "log", "test_id": task_id, "data": event})

    async def disconnect(self, task_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            clients = self._clients.get(task_id)
            if clients:
                clients.discard(websocket)

    async def publish_progress(self, task_id: str, data: dict[str, Any]) -> None:
        self._snapshots[task_id] = data
        await self._broadcast(task_id, {"type": "progress", "test_id": task_id, "data": data})

    async def publish_log(self, task_id: str, level: str, message: str) -> None:
        event = {"level": level, "message": message}
        self._events[task_id].append(event)
        await self._broadcast(task_id, {"type": "log", "test_id": task_id, "data": event})

    async def publish_status(self, task_id: str, status: str) -> None:
        await self._broadcast(task_id, {"type": "status", "test_id": task_id, "data": {"status": status}})

    async def _broadcast(self, task_id: str, message: dict[str, Any]) -> None:
        clients = list(self._clients.get(task_id, set()))
        if not clients:
            return
        stale: list[WebSocket] = []
        for websocket in clients:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)

        if stale:
            async with self._lock:
                active = self._clients.get(task_id)
                if active:
                    for websocket in stale:
                        active.discard(websocket)
