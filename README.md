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

- `DATABASE_URL`: default `sqlite:///./data/llm_test.db`
- `RESULTS_DIR`: default `./results`
- `MAX_RUNNING_TESTS`: default `2`
- `MAX_CONCURRENCY_PER_TEST`: default `500`

The frontend can use:

- `VITE_API_BASE_URL`: optional API base URL for non-proxy deployments
- `VITE_WS_BASE_URL`: optional websocket base URL for non-proxy deployments

API keys are submitted per test run. The backend removes `api_key` before persisting task configuration to SQLite and reports; do not put real keys in `.env.example`, docs, logs, or committed result files.

## State And Retention

The web console uses SQLite as a lightweight local state store at `data/llm_test.db` by default. It stores task metadata, status, events, summaries, and file paths. Report artifacts are written under `results/`, with web-console runs grouped by task id.

Results are intended for short-term local review by default. Use the UI delete action to remove a task and its task-specific result directory, or clean old local artifacts after exporting what you need. Before sharing reports, remove sensitive request/response payloads and endpoint details.

## Smoke Check

With backend and frontend running:

```powershell
.\scripts\smoke_check.ps1
```

The smoke check verifies expected files/directories, backend health, test listing, and frontend reachability without creating a load-test task.

## Versioned Commit Workflow

After finishing a feature, stage only the source files that should be committed, then use the versioned commit script:

```powershell
git add frontend\src\components\ConfigForm.vue backend\app\models\schemas.py README.md
.\scripts\commit_with_version.ps1 -Message "Add beginner load estimator"
```

The script bumps the patch version, syncs the frontend package files and backend API version, then creates the commit. Do not stage logs, `results/`, `frontend/dist/`, or `__pycache__/` files.
## CLI Example

```powershell
python glm_tpm_test.py --base-url https://api.example.com/v1 --api-key $env:API_KEY --model glm-5.1 --concurrency 10 --duration-sec 60 --input-tokens 1000 --enable-stream
```
