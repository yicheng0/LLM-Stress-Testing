# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python-based GLM/OpenAI-compatible API load testing suite. The reusable implementation lives in `loadtest/`, and `llm_load_test.py` is the CLI entrypoint. The core package handles prompt generation, async load workers, retry logic, protocol payloads, metrics aggregation, and report generation. Quick entry points live in `quick_test.py` and `quick_extreme_test.py`. API behavior checks are in `test_glm_features.py`. Generated outputs are written to `results/` as JSON, JSONL, Markdown, HTML, and CSV files. Older replaced scripts have been removed; use git history when historical behavior must be inspected. Project documentation is in `CLAUDE.md`, `PROJECT_STRUCTURE.md`, `CHANGELOG.md`, and `压测脚本增强实施计划.md`.

## Build, Test, and Development Commands

Install runtime dependencies before running tests:

```bash
pip install aiohttp tiktoken
```

Run a targeted load test:

```bash
python llm_load_test.py --base-url https://api.example.com/v1 --api-key $API_KEY --model glm-5.1 --concurrency 200 --duration-sec 300 --input-tokens 10000 --enable-stream
```

Run matrix testing across multiple input sizes and concurrency levels:

```bash
python llm_load_test.py --matrix-mode --input-tokens-list 1000,10000,100000 --concurrency-list 50,100,200 --matrix-duration-sec 60 --enable-stream
```

Use `python quick_test.py` for a short validation run and `python quick_extreme_test.py` for high-concurrency stress testing. Use `python test_glm_features.py --base-url ... --api-key ... --model ...` to validate API parameter support.

## Coding Style & Naming Conventions

Use Python 3 syntax with 4-space indentation, type hints where they clarify data flow, and dataclasses for structured result objects. Keep CLI flags lowercase and hyphenated, matching existing patterns such as `--duration-sec` and `--input-tokens`. Prefer explicit names for metrics (`ttft_sec`, `output_tokens`, `retry_count`) and keep report filenames timestamped under `results/`.

## Testing Guidelines

Before changing load behavior, verify both streaming and non-streaming modes. For metric or report changes, run at least one small scenario and inspect `summary_*.json`, `details_*.jsonl`, and generated reports. For API compatibility work, update or run `test_glm_features.py`. Matrix mode should be tested when modifying concurrency, token sizing, cooldown, or aggregate CSV/report logic.

## Commit & Pull Request Guidelines

This checkout has no `.git` metadata, so no local commit convention can be inferred. Use concise imperative commit subjects, for example `Add TTFT percentile reporting` or `Fix matrix CSV output`. Pull requests should include the purpose, commands run, representative result files or screenshots for report changes, linked issues if available, and notes about any changed defaults or API assumptions.

## Security & Configuration Tips

Do not commit API keys, endpoint secrets, or large generated result sets unless explicitly needed. Pass credentials through environment variables such as `$API_KEY` or local shell configuration. Keep `results/` outputs reviewable and remove sensitive request or response payloads before sharing reports.

