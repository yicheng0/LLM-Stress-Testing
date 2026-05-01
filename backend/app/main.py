from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.api.docs import router as docs_router
from backend.app.api.tests import router as tests_router
from backend.app.api.websocket import router as websocket_router
from backend.app.core.progress import ProgressHub
from backend.app.core.repository import Repository
from backend.app.core.task_manager import TaskManager
from backend.app.models.database import init_db

repository = Repository()
progress_hub = ProgressHub()
task_manager = TaskManager(repository, progress_hub)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    repository.mark_unfinished_interrupted()
    if settings.cleanup_on_startup:
        repository.cleanup_expired_results()
    yield


app = FastAPI(title="LLM API 性能测试平台", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tests_router)
app.include_router(docs_router)
app.include_router(websocket_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
