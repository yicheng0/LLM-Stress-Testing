from __future__ import annotations

import os
from pathlib import Path


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://llm_test:llm_test@postgres:5432/llm_test")
    results_dir: Path = Path(os.getenv("RESULTS_DIR", "./results"))
    max_running_tests: int = int(os.getenv("MAX_RUNNING_TESTS", "2"))
    max_concurrency_per_test: int = int(os.getenv("MAX_CONCURRENCY_PER_TEST", "500"))
    result_retention_hours: int = int(os.getenv("RESULT_RETENTION_HOURS", "24"))


settings = Settings()
