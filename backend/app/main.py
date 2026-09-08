from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.auth import router as auth_router
from backend.app.api.cache_diagnostics import router as cache_diagnostics_router
from backend.app.api.docs import router as docs_router
from backend.app.api.tests import router as tests_router
from backend.app.api.websocket import router as websocket_router
from backend.app.api.vendor_billing import router as vendor_billing_router
from backend.app.api.kimi_suite import router as kimi_suite_router
from backend.app.api.vendor_templates import router as vendor_templates_router
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
    yield


app = FastAPI(title="LLM API 性能测试平台", version="unversioned", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(cache_diagnostics_router)
app.include_router(vendor_billing_router)
app.include_router(kimi_suite_router)
app.include_router(vendor_templates_router)
app.include_router(tests_router)
app.include_router(docs_router)
app.include_router(websocket_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
