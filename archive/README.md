# Archive

This directory contains legacy versions of the load testing scripts that have been superseded by `glm_tpm_test.py`.

## Archived Files

### load_test_llm_api(1).py
- **Date**: 2026-04-28 14:15
- **Size**: 22KB (558 lines)
- **Status**: Legacy version without TTFT measurement
- **Superseded by**: glm_tpm_test.py

### load_test_llm_tpm.py
- **Date**: 2026-04-28 14:16
- **Size**: 23KB (580 lines)
- **Status**: Legacy version without streaming support
- **Superseded by**: glm_tpm_test.py

## Why Archived

These files were earlier iterations of the load testing framework that lacked:
- Streaming mode for TTFT measurement
- TPS (Tokens Per Second) metrics
- Percentile distributions (P50, P90, P95, P99)
- Matrix testing mode
- Interactive HTML reports
- Comprehensive error categorization

The current implementation (`glm_tpm_test.py`) includes all these features and should be used instead.

## Restoration

If you need to reference or restore these files:
```bash
cp archive/load_test_llm_api\(1\).py ./
cp archive/load_test_llm_tpm.py ./
```
