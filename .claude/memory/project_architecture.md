---
name: Project Architecture Decisions
description: Key architectural patterns and design decisions in the load testing framework
type: project
---

# Project Architecture Decisions

## Core Design Patterns

### 1. Pre-built Prompts for Performance

**Decision**: Build the prompt once during `LoadTester.__init__()` and reuse for all requests.

**Why**: Token counting is CPU-intensive, especially with tiktoken. Building prompts per-request would create significant overhead and skew latency measurements.

**How to apply**: When adding new test modes or prompt variations, always pre-build and cache prompts. Never generate prompts in the hot path (`send_one()` or `worker()`).

### 2. Streaming for TTFT Measurement

**Decision**: Use `resp.content.iter_any()` to capture first chunk arrival time.

**Why**: Non-streaming responses arrive as a complete payload, making it impossible to measure when the first token was generated. Streaming allows precise TTFT measurement by capturing the timestamp of the first non-empty chunk.

**How to apply**: Always recommend `--enable-stream` for performance analysis. Non-streaming mode is only for backward compatibility or when TTFT is not needed.

### 3. Separate TTFT and Decode Metrics

**Decision**: Track TTFT and calculate decode time as `latency - TTFT`.

**Why**: Prefill (context processing) and decode (token generation) have different performance characteristics and bottlenecks. Separating them enables targeted optimization.

**How to apply**: When analyzing performance issues, always check the TTFT vs decode ratio. High TTFT (>70% of latency) indicates prefill bottlenecks; high decode time indicates generation bottlenecks.

### 4. Percentile-Based Analysis

**Decision**: Calculate P50, P90, P95, P99 for all latency metrics.

**Why**: Average latency hides tail behavior. P95/P99 are critical for SLA compliance and user experience. A service with avg=1s but P99=30s will have poor user experience.

**How to apply**: Always prioritize P95/P99 over averages when evaluating performance. Use custom percentile calculation to avoid full sorting overhead.

### 5. Matrix Testing for Capacity Planning

**Decision**: Support testing multiple input sizes × concurrency levels in a single run.

**Why**: Capacity planning requires understanding how performance scales across different load patterns. Single-point tests don't reveal inflection points or optimal configurations.

**How to apply**: For capacity planning, always use matrix mode with at least 3 input sizes and 3 concurrency levels. Include cooldown periods between tests to avoid interference.

## Implementation Patterns

### Error Handling Strategy

**Pattern**: Categorize errors by type (timeout, HTTP status, connection error) and track retry counts.

**Why**: Different error types indicate different problems:
- 429: Rate limiting (adjust quotas)
- 5xx: Server capacity issues
- Timeouts: Queueing or slow processing
- Connection errors: Network or infrastructure issues

**How to apply**: When debugging failures, always check error distribution first. Don't just look at success rate.

### Async I/O with Semaphore

**Pattern**: Use `asyncio.Semaphore` to control concurrency, not thread pools.

**Why**: Async I/O is more efficient for I/O-bound workloads. Semaphore provides precise concurrency control without thread overhead.

**How to apply**: When adding new request types or endpoints, maintain the async pattern. Don't introduce blocking I/O in the hot path.

### Time Measurement Precision

**Pattern**: Use `time.perf_counter()` for latency measurement, not `time.time()`.

**Why**: `perf_counter()` is monotonic and higher resolution, avoiding clock adjustment issues.

**How to apply**: Always use `perf_counter()` for measuring durations. Use `time.time()` only for absolute timestamps (e.g., `started_at`, `ended_at`).

## Data Flow

```
LoadTester.__init__()
  ↓ (pre-build prompt)
LoadTester.run()
  ↓ (warmup phase)
  ↓ (spawn workers)
LoadTester.worker() [×N concurrent]
  ↓ (loop until duration expires)
LoadTester.send_one()
  ↓ (streaming: capture TTFT)
  ↓ (parse response)
  ↓ (retry on failure)
  ← (return RequestResult)
LoadTester.summarize()
  ↓ (calculate percentiles)
  ↓ (aggregate metrics)
render_markdown_report()
render_html_report()
  ↓ (write to files)
```

## Performance Considerations

1. **Prompt Building**: O(n) where n = target tokens, done once
2. **Token Counting**: O(n) with tiktoken, done once per prompt
3. **Request Sending**: O(1) per request, fully async
4. **Percentile Calculation**: O(n log n) where n = successful requests
5. **Report Generation**: O(n) where n = total requests

**Bottleneck**: For very high concurrency (>1000), the main bottleneck is typically network bandwidth or server capacity, not client-side processing.
