# LLM Stress Testing

LLM Stress Testing is a performance benchmarking and stress testing toolkit for OpenAI-compatible and GLM-style model APIs. It can run from the command line or through the lightweight web console.

## Key Metrics

- **TPM**: Tokens Per Minute
- **RPM**: Requests Per Minute
- **TPS**: Tokens Per Second
- **TTFT**: Time To First Token
- **Average Latency**: Average request completion time
- **P50 Latency**: Median response latency
- **P99 Latency**: Tail latency under high load

Retry-inclusive metrics such as `attempt_tokens` and `attempt_tpm` estimate observable retry pressure: every attempt counts its input tokens, failed retry attempts do not infer hidden output tokens, and a successful response contributes output tokens once.

## Web Console Quick Start

Backend:

```powershell
cd D:\model_rpm_test
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```powershell
cd D:\model_rpm_test\frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. In development, Vite proxies `/api` and `/ws` to `http://127.0.0.1:8000`.

## Environment

Copy `.env.example` to `.env` for local overrides. The current backend reads:

- `DATABASE_URL`: default `postgresql+psycopg://llm_test:llm_test@postgres:5432/llm_test`
- `RESULTS_DIR`: default `./results`
- `MAX_RUNNING_TESTS`: default `2`
- `MAX_CONCURRENCY_PER_TEST`: default `500`
- `RESULT_RETENTION_HOURS`: default `24`

The frontend can use:

- `VITE_API_BASE_URL`: optional API base URL for non-proxy deployments
- `VITE_WS_BASE_URL`: optional websocket base URL for non-proxy deployments

API keys are submitted per test run. The backend removes `api_key` before persisting task configuration to the database and reports; do not put real keys in `.env.example`, docs, logs, or committed result files.

## State And Retention

The web console uses PostgreSQL as the default state store in deployment. It stores task metadata, status, events, summaries, and file paths. Report artifacts are written under `results/`, with web-console runs grouped by task id.

Results are intended for short-term local review by default. Use the UI delete action to remove a task and its task-specific result directory. The backend does not run automatic startup or interval cleanup jobs. Before sharing reports, remove sensitive request/response payloads and endpoint details.

## Smoke Check

With backend and frontend running:

```powershell
.\scripts\smoke_check.ps1
```

The smoke check verifies expected files/directories, backend health, test listing, and frontend reachability without creating a load-test task.

## Deployment Guide

See [docs/部署教程.md](docs/部署教程.md) for a step-by-step deployment guide, including first-time setup, Nginx reverse proxy, persistence, upgrades, and troubleshooting.

Docker Compose defaults to these host ports:

- Web console: `8080`
- Backend API: `8081`

## Operations Runbooks

- [MySQL 30 分钟 Dump 高 CPU 排障 Runbook](docs/mysql_dump_high_cpu_runbook.md): locate recurring `SQL_NO_CACHE` dump/log cleanup jobs, collect read-only evidence, and lower schedule impact without deleting the task first.
- Supporting assets: `scripts/mysql_dump_triage.sql`, `scripts/mysql_dump_scheduler_audit.sh`, and `scripts/mysql_dump_mitigation_templates.sql`.

## CLI Example

```powershell
python llm_load_test.py --base-url https://api.example.com/v1 --api-key $env:API_KEY --model glm-5.1 --concurrency 10 --duration-sec 60 --input-tokens 1000 --enable-stream
```
