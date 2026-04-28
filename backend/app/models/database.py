from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.app.config import settings


class Base(DeclarativeBase):
    pass


class TestTask(Base):
    __tablename__ = "test_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    api_protocol: Mapped[str] = mapped_column(String, nullable=False, default="openai", index=True)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    enable_stream: Mapped[bool] = mapped_column(Boolean, nullable=False)
    matrix_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class TestResult(Base):
    __tablename__ = "test_results"

    task_id: Mapped[str] = mapped_column(String, ForeignKey("test_tasks.id"), primary_key=True)
    summary_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    summary_path: Mapped[str | None] = mapped_column(String)
    details_jsonl_path: Mapped[str | None] = mapped_column(String)
    report_md_path: Mapped[str | None] = mapped_column(String)
    report_html_path: Mapped[str | None] = mapped_column(String)
    matrix_csv_path: Mapped[str | None] = mapped_column(String)


class TestEvent(Base):
    __tablename__ = "test_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("test_tasks.id"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        if db_path and not db_path.startswith(":memory:"):
            from pathlib import Path

            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_api_protocol_column()


def _ensure_api_protocol_column() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(test_tasks)")).fetchall()]
        if "api_protocol" not in columns:
            conn.execute(text("ALTER TABLE test_tasks ADD COLUMN api_protocol VARCHAR NOT NULL DEFAULT 'openai'"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_test_tasks_api_protocol ON test_tasks (api_protocol)"))

        rows = conn.execute(text("SELECT id, config_json, api_protocol FROM test_tasks")).fetchall()
        for task_id, config_json, current_protocol in rows:
            protocol = "openai"
            try:
                protocol = json.loads(config_json or "{}").get("api_protocol", "openai")
            except json.JSONDecodeError:
                protocol = "openai"
            if current_protocol == protocol:
                continue
            conn.execute(
                text("UPDATE test_tasks SET api_protocol = :protocol WHERE id = :task_id"),
                {"protocol": protocol, "task_id": task_id},
            )
