# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GLM API Load Testing Suite - A comprehensive performance testing framework for LLM APIs (OpenAI-compatible endpoints). Designed specifically for testing GLM models with focus on measuring TPM (Tokens Per Minute), TPS (Tokens Per Second), TTFT (Time To First Token), latency distribution, and throughput under various concurrency levels and input sizes.

**Primary Goal**: Accurately measure LLM API performance characteristics including prefill (TTFT) and decode phases, identify capacity bottlenecks, and support capacity planning decisions.

## Core Architecture

### Main Components

**glm_tpm_test.py** - Primary load testing engine (~1500 lines)
- `TokenEstimator` - Token counting using tiktoken (falls back to character-based estimation)
- `PromptFactory` - Generates prompts of target token length using repeated LOREM text blocks
- `LoadTester` - Main orchestrator handling concurrent workers, request lifecycle, and metrics aggregation
- `RequestResult` - Dataclass capturing per-request metrics (latency, TTFT, tokens, errors)

### Request Flow

1. **Initialization** (`LoadTester.__init__`)
   - Builds prompt to exact token count via `PromptFactory.build_prompt()`
   - Pre-counts actual tokens to avoid repeated computation
   - Initializes result storage and synchronization primitives

2. **Warmup Phase** (`LoadTester.run`)
   - Sends configurable warmup requests (default: 5)
   - Validates API connectivity before main test
   - Warmup results excluded from final metrics

3. **Load Generation** (`LoadTester.worker`)
   - Spawns N concurrent workers (N = `--concurrency`)
   - Each worker sends requests continuously until `--duration-sec` expires
   - Semaphore controls max concurrent requests
   - Real-time progress logging every 10 requests

4. **Request Execution** (`LoadTester.send_one`)
   - **Streaming mode** (`--enable-stream`):
     - Captures TTFT by measuring time to first chunk via `resp.content.iter_any()`
     - Parses SSE stream for token usage data
     - Critical for prefill/decode phase separation
   - **Non-streaming mode**:
     - TTFT remains None (cannot measure first token time)
     - Parses JSON response for token counts
   - Retry logic with exponential backoff for 408/429/5xx errors
   - Comprehensive error categorization (timeout, HTTP errors, connection errors)

5. **Metrics Aggregation** (`LoadTester.summarize`)
   - Calculates percentiles (P50, P90, P95, P99) for latency, TTFT, decode time
   - Computes TPM/TPS for input/output/total tokens
   - Generates error distribution and status code counts
   - Analyzes TTFT vs decode time ratios for bottleneck identification

6. **Report Generation**
   - Markdown report with tables and analysis (`render_markdown_report`)
   - Interactive HTML report with ECharts visualizations (`render_html_report`)
   - JSON summary and JSONL details for programmatic analysis
   - Matrix CSV export for multi-scenario comparisons

### Key Metrics Explained

**TTFT (Time To First Token)**
- Measures prefill phase performance (context processing)
- Only available in streaming mode
- High TTFT indicates KV cache pressure or long context bottlenecks
- Formula: `time_to_first_chunk - request_start_time`

**Decode Time**
- Measures generation phase performance
- Calculated as: `total_latency - TTFT`
- High decode time indicates generation speed bottlenecks

**TPM vs TPS**
- TPM (Tokens Per Minute): `total_tokens * 60 / wall_time`
- TPS (Tokens Per Second): `total_tokens / wall_time`
- Tracked separately for input/output/total tokens

**Percentiles**
- P50 (median): typical case performance
- P95: captures tail latency, critical for SLA
- P99: extreme tail, indicates worst-case user experience

## Running Tests

### Single-Point Test
```bash
python glm_tpm_test.py \
  --base-url https://api.example.com/v1 \
  --api-key $API_KEY \
  --model glm-5.1 \
  --concurrency 200 \
  --duration-sec 300 \
  --input-tokens 10000 \
  --enable-stream
```

### Matrix Testing (Multiple Scenarios)
Tests all combinations of input sizes × concurrency levels:
```bash
python glm_tpm_test.py \
  --matrix-mode \
  --input-tokens-list 1000,10000,100000 \
  --concurrency-list 50,100,200 \
  --matrix-duration-sec 60 \
  --enable-stream
```

Matrix mode includes:
- Cooldown period between tests (default: 10s)
- Separate reports per scenario
- Aggregated matrix report with comparison tables
- CSV export for analysis in Excel/Python

### Quick Test Wrappers
```bash
# Quick validation (10 concurrent, 30s, 1k tokens)
python quick_test.py

# Extreme load test (500 concurrent, 30s, 60k tokens)
python quick_extreme_test.py
```

### Feature Validation
```bash
python test_glm_features.py \
  --base-url https://api.example.com/v1 \
  --api-key $API_KEY \
  --model glm-5.1
```

Tests:
- `max_tokens` parameter enforcement
- `stop` sequences (numeric and Chinese characters)
- Model name case insensitivity

## Important Implementation Details

### Streaming Response Parsing

The `_parse_stream_usage()` method handles SSE format:
```
data: {"choices":[{"delta":{"content":"Hello"}}]}
data: {"choices":[{"delta":{}}],"usage":{"completion_tokens":10,"total_tokens":110}}
data: [DONE]
```

- Iterates through lines starting with `data: `
- Extracts `usage` object from final chunk before `[DONE]`
- Falls back to estimating output tokens if usage unavailable

### Token Counting Strategy

1. **Preferred**: tiktoken library for accurate counting
   - Tries model-specific encoder first
   - Falls back to `cl100k_base` encoding
2. **Fallback**: Character-based estimation (4 chars ≈ 1 token)
3. Prompt is pre-built once during initialization to avoid repeated counting overhead

### Error Handling

**Retryable Errors** (up to `--max-retries`, default: 2):
- 408 Request Timeout
- 409 Conflict
- 429 Rate Limit
- 500/502/503/504 Server Errors

**Non-Retryable Errors**:
- 4xx client errors (except above)
- Connection errors after max retries
- Timeout errors after max retries

**Exponential Backoff**:
- Base delay: `--retry-backoff-base` (default: 1.0s)
- Max delay: `--retry-backoff-max` (default: 8.0s)
- Formula: `min(base * 2^(attempt-1), max) + jitter`

### Performance Optimizations

1. **Prompt Pre-building**: Prompt constructed once, reused for all requests
2. **Connection Pooling**: Single `aiohttp.ClientSession` with unlimited connections
3. **Async I/O**: `asyncio` for efficient concurrent request handling
4. **Minimal Logging**: Only logs failures and every 10th request to reduce overhead
5. **Efficient Percentile Calculation**: Custom implementation avoiding full sorting

## Output Files

All results saved to `./results/` directory:

- `summary_YYYYMMDD_HHMMSS.json` - Aggregated metrics (config + results)
- `details_YYYYMMDD_HHMMSS.jsonl` - Per-request details (one JSON per line)
- `report_YYYYMMDD_HHMMSS.md` - Human-readable Markdown report
- `report_YYYYMMDD_HHMMSS.html` - Interactive HTML with ECharts visualizations
- `matrix_report_YYYYMMDD_HHMMSS.md` - Matrix test comparison tables (matrix mode only)
- `matrix_data_YYYYMMDD_HHMMSS.csv` - Matrix test CSV export (matrix mode only)

## Configuration Reference

### Essential Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--base-url` | `https://api.wenwen-ai.com/v1` | API base URL |
| `--api-key` | (hardcoded) | API authentication key |
| `--model` | `glm-5.1` | Model name |
| `--endpoint` | `/chat/completions` | API endpoint path |
| `--concurrency` | 500 | Number of concurrent workers |
| `--duration-sec` | 300 | Test duration in seconds |
| `--input-tokens` | 60000 | Target input token count |
| `--max-output-tokens` | 128 | Max tokens to generate |
| `--enable-stream` | True | Enable streaming for TTFT measurement |

### Advanced Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--timeout-sec` | 600 | Per-request timeout |
| `--connect-timeout-sec` | 30 | Connection timeout |
| `--warmup-requests` | 5 | Number of warmup requests |
| `--max-retries` | 2 | Max retry attempts for retryable errors |
| `--think-time-ms` | 0 | Delay between requests per worker |
| `--temperature` | 0.0 | Sampling temperature |

### Matrix Mode Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--matrix-mode` | False | Enable matrix testing |
| `--input-tokens-list` | `60000,80000,100000` | Comma-separated input sizes |
| `--concurrency-list` | `300,500,700` | Comma-separated concurrency levels |
| `--matrix-duration-sec` | 300 | Duration per test point |

## API Endpoint Compatibility

Supports two endpoint formats:

**Standard OpenAI Chat Format** (`/chat/completions`):
```json
{
  "model": "glm-5.1",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "max_tokens": 128,
  "temperature": 0.0,
  "stream": true
}
```

**Alternative Response Format** (`/responses`):
```json
{
  "model": "glm-5.1",
  "input": "...",
  "max_output_tokens": 128,
  "temperature": 0.0,
  "stream": true
}
```

Payload structure automatically adjusted based on endpoint path.

## Dependencies

**Required**:
- `aiohttp>=3.8.0` - Async HTTP client for concurrent requests

**Optional**:
- `tiktoken>=0.5.0` - Accurate token counting (highly recommended)

Install: `pip install aiohttp tiktoken`

## Common Issues and Solutions

### TTFT Shows N/A
- **Cause**: Streaming mode not enabled
- **Solution**: Add `--enable-stream` flag

### High Failure Rate
- **Possible Causes**:
  1. Input tokens exceed model context window
  2. Rate limiting (429 errors)
  3. Server capacity bottleneck (5xx errors)
  4. Network issues
- **Solution**: Check error distribution in report, reduce concurrency or input size

### TTFT > Total Latency
- **Cause**: Time measurement error or clock skew
- **Solution**: Check detailed logs, verify system clock stability

### Low TPM Despite High Concurrency
- **Possible Causes**:
  1. Server-side queueing
  2. Rate limiting
  3. Network bandwidth bottleneck
- **Solution**: Run matrix test to find optimal concurrency level

## Development Guidelines

### When Modifying Code

1. **Update CLAUDE.md** if:
   - Architecture changes (new classes, major refactoring)
   - New features added (parameters, metrics, output formats)
   - Request flow modified
   - Configuration defaults changed

2. **Update Memory** if:
   - Core optimization implemented
   - Bug fix with important context
   - Performance improvement technique discovered
   - User feedback incorporated

3. **Document in Code** if:
   - Non-obvious algorithm (e.g., percentile calculation)
   - Workaround for specific API behavior
   - Critical performance consideration

### Testing Checklist

Before committing changes:
- [ ] Test with streaming enabled and disabled
- [ ] Test with small (1k), medium (10k), and large (100k) input sizes
- [ ] Verify TTFT measurement accuracy
- [ ] Check error handling for common failure modes
- [ ] Validate report generation (MD, HTML, JSON)
- [ ] Test matrix mode if relevant

## Project Context

This project was created to address specific deficiencies in earlier load testing scripts:
1. **Missing TTFT measurement** - Earlier versions couldn't measure prefill performance
2. **No TPS metrics** - Only TPM was available
3. **Limited statistical analysis** - No percentile distributions
4. **Poor error visibility** - Errors not categorized or analyzed

The implementation plan document (`压测脚本增强实施计划.md`) contains detailed requirements and design decisions.
