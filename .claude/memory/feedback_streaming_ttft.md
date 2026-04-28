---
name: Streaming Mode for TTFT Measurement
description: Critical requirement to use streaming mode for accurate TTFT measurement
type: feedback
---

# Streaming Mode for TTFT Measurement

Always enable streaming mode (`--enable-stream`) when TTFT (Time To First Token) measurement is needed.

**Why**: Non-streaming responses arrive as a complete payload after all tokens are generated. This makes it impossible to measure when the first token was produced. Streaming mode allows capturing the exact moment the first chunk arrives, which represents the end of the prefill phase.

**How to apply**: 
- When running performance tests that need to distinguish prefill vs decode performance, always use `--enable-stream`
- When documenting test procedures, emphasize that TTFT requires streaming mode
- When TTFT shows as "N/A" in reports, it means streaming was not enabled
- Default value is now `True` in the script to ensure TTFT is measured by default

**Context**: This was a key enhancement from earlier versions of the load testing script, which couldn't measure TTFT at all. The implementation plan document (`压测脚本增强实施计划.md`) specifically called out TTFT measurement as a P0 priority requirement.
