---
name: GLM Load Testing Project Overview
description: Purpose, evolution, and key requirements of the GLM API load testing suite
type: project
---

# GLM Load Testing Project Overview

## Purpose

This is a comprehensive load testing framework for LLM APIs (OpenAI-compatible endpoints), specifically designed for testing GLM models. The primary goal is to accurately measure performance characteristics under various load conditions to support capacity planning and performance optimization decisions.

## Key Requirements

The project was created to address specific deficiencies in earlier load testing scripts:

1. **TTFT Measurement** - Earlier versions couldn't measure Time To First Token, making it impossible to distinguish prefill (context processing) performance from decode (generation) performance
2. **TPS Metrics** - Only TPM (Tokens Per Minute) was available; TPS (Tokens Per Second) needed for real-time throughput analysis
3. **Statistical Analysis** - Needed percentile distributions (P50, P90, P95, P99) for latency, TTFT, and decode time
4. **Error Visibility** - Errors needed categorization and detailed analysis
5. **Matrix Testing** - Support for testing multiple input sizes × concurrency levels in a single run

## Evolution

**Phase 1**: Basic load testing scripts (`load_test_llm_api(1).py`, `load_test_llm_tpm.py`)
- Simple concurrent request generation
- Basic TPM calculation
- Limited error handling

**Phase 2**: Enhanced script (`glm_tpm_test.py`)
- Streaming support for TTFT measurement
- Comprehensive metrics (TPM, TPS, TTFT, decode time)
- Percentile distributions
- Matrix testing mode
- Interactive HTML reports with visualizations
- Detailed error categorization

**Phase 3**: Wrapper scripts and validation
- `quick_test.py` - Fast validation test
- `quick_extreme_test.py` - Extreme load test
- `test_glm_features.py` - API feature validation

## Critical Success Factors

**Why**: The client needs accurate performance data to make capacity planning decisions. Inaccurate TTFT or missing decode time analysis leads to wrong conclusions about bottlenecks.

**How to apply**: Always prioritize measurement accuracy over convenience. When adding features, ensure they don't compromise timing precision or introduce measurement artifacts.

## Current Status (2026-04-28)

- Core functionality complete and tested
- Streaming TTFT measurement working correctly
- Matrix testing mode operational
- HTML visualization reports generated successfully
- Documentation being established (CLAUDE.md + memory system)
