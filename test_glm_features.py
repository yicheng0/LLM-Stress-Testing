"""
GLM API Feature Validation Test Script
Tests: max_tokens, stop sequences, model name case insensitivity
Usage: python test_glm_features.py
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

# ANSI colors
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def pass_line(msg):
    print(f"  {GREEN}PASS{RESET} {msg}")


def fail_line(msg):
    print(f"  {RED}FAIL{RESET} {msg}")


def info_line(msg):
    print(f"  {YELLOW}INFO{RESET} {msg}")


def chat(base_url, api_key, model, messages, **kwargs):
    url = base_url.rstrip("/") + "/v1/chat/completions"
    print(f"    → POST {url}")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {"model": model, "messages": messages, **kwargs}
    resp = requests.post(url, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Test 1: max_tokens
# ---------------------------------------------------------------------------
def test_max_tokens(base_url, api_key, model):
    print(f"\n{BOLD}[Test 1] max_tokens parameter{RESET}")
    results = []

    cases = [
        {"limit": 5,  "label": "max_tokens=5"},
        {"limit": 20, "label": "max_tokens=20"},
        {"limit": 80, "label": "max_tokens=80"},
    ]
    prompt = [{"role": "user", "content": "请详细介绍中国历史，越详细越好，至少写500字。"}]

    for case in cases:
        limit = case["limit"]
        try:
            data = chat(base_url, api_key, model, prompt, max_tokens=limit, temperature=0.0)
            tokens  = data.get("usage", {}).get("completion_tokens", -1)
            content = data["choices"][0]["message"].get("content", "") or ""
            passed  = tokens != -1 and tokens <= limit
            detail  = f"limit={limit}, completion_tokens={tokens}, text_len={len(content)}"
            (pass_line if passed else fail_line)(f"{case['label']}: {detail}")
            results.append({"case": case["label"], "passed": passed, "limit": limit,
                             "completion_tokens": tokens, "text_length": len(content),
                             "response_text": content[:200]})
        except Exception as e:
            fail_line(f"{case['label']}: error — {e}")
            results.append({"case": case["label"], "passed": False, "error": str(e)})

    overall = all(r["passed"] for r in results)
    return {"name": "max_tokens", "passed": overall, "cases": results}


# ---------------------------------------------------------------------------
# Test 2: stop sequences
# ---------------------------------------------------------------------------
def test_stop(base_url, api_key, model):
    print(f"\n{BOLD}[Test 2] stop parameter{RESET}")
    results = []

    cases = [
        {
            "label": 'stop=["5"]',
            "prompt": "请用逗号分隔，列出数字1到10，只输出数字和逗号，不要其他内容。",
            "stop": ["5"],
            "forbidden": ["6", "7", "8", "9", "10"],
        },
        {
            "label": 'stop=["三"]',
            "prompt": "请依次输出：一、二、三、四、五，每个汉字之间用顿号隔开。",
            "stop": ["三"],
            "forbidden": ["四", "五"],
        },
    ]

    for case in cases:
        prompt = [{"role": "user", "content": case["prompt"]}]
        try:
            data = chat(base_url, api_key, model, prompt, stop=case["stop"], temperature=0.0)
            content       = data["choices"][0]["message"].get("content", "") or ""
            finish_reason = data["choices"][0].get("finish_reason", "")
            forbidden_found = [w for w in case["forbidden"] if w in content]
            passed = len(forbidden_found) == 0
            detail = (f"finish_reason={finish_reason}, "
                      f"forbidden_found={forbidden_found}, "
                      f"text={repr(content)}")
            (pass_line if passed else fail_line)(f"{case['label']}: {detail}")
            results.append({"case": case["label"], "passed": passed, "finish_reason": finish_reason,
                             "forbidden_found": forbidden_found, "response_text": content})
        except Exception as e:
            fail_line(f"{case['label']}: error — {e}")
            results.append({"case": case["label"], "passed": False, "error": str(e)})

    overall = all(r["passed"] for r in results)
    return {"name": "stop", "passed": overall, "cases": results}


# ---------------------------------------------------------------------------
# Test 3: model name case insensitivity
# ---------------------------------------------------------------------------
def test_model_case(base_url, api_key, model):
    print(f"\n{BOLD}[Test 3] model name case insensitivity{RESET}")
    results = []

    variants = list(dict.fromkeys([model.lower(), model.upper(), model.title()]))
    prompt   = [{"role": "user", "content": "Say 'ok' only."}]

    for variant in variants:
        try:
            data    = chat(base_url, api_key, variant, prompt, max_tokens=10, temperature=0.0)
            content = data["choices"][0]["message"].get("content", "") or ""
            info_line(f"model={repr(variant)}: HTTP 200, response={repr(content)}")
            results.append({"variant": variant, "passed": True, "response_text": content})
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            fail_line(f"model={repr(variant)}: HTTP {status} — {e}")
            results.append({"variant": variant, "passed": False, "error": str(e), "status_code": status})
        except Exception as e:
            fail_line(f"model={repr(variant)}: error — {e}")
            results.append({"variant": variant, "passed": False, "error": str(e)})

    overall = all(r["passed"] for r in results)
    if overall:
        pass_line("All model name variants accepted — model name is case-insensitive")
    else:
        failed = [r["variant"] for r in results if not r["passed"]]
        fail_line(f"Some variants rejected: {failed}")

    return {"name": "model_case", "passed": overall, "cases": results}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    BASE_URL = ""
    API_KEY  = ""
    MODEL    = "glm-5.1"

    parser = argparse.ArgumentParser(description="GLM API feature validation tests")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--api-key",  default=API_KEY)
    parser.add_argument("--model",    default=MODEL)
    parser.add_argument("--skip", nargs="*", choices=["max_tokens", "stop", "model_case"],
                        default=[], help="Tests to skip")
    args = parser.parse_args()

    print(f"{BOLD}GLM API Feature Validation{RESET}")
    print(f"base_url : {args.base_url}")
    print(f"model    : {args.model}")
    print(f"time     : {datetime.now().isoformat(timespec='seconds')}")

    all_results = []

    if "max_tokens" not in args.skip:
        all_results.append(test_max_tokens(args.base_url, args.api_key, args.model))
    if "stop" not in args.skip:
        all_results.append(test_stop(args.base_url, args.api_key, args.model))
    if "model_case" not in args.skip:
        all_results.append(test_model_case(args.base_url, args.api_key, args.model))

    print(f"\n{BOLD}{'='*50}{RESET}")
    print(f"{BOLD}Summary{RESET}")
    any_failed = False
    for r in all_results:
        status = f"{GREEN}PASS{RESET}" if r["passed"] else f"{RED}FAIL{RESET}"
        print(f"  {status}  {r['name']}")
        if not r["passed"]:
            any_failed = True

    out_dir  = Path("results")
    out_dir.mkdir(exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"feature_test_{ts}.json"
    payload  = {
        "timestamp": datetime.now().isoformat(),
        "base_url":  args.base_url,
        "model":     args.model,
        "results":   all_results,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull results saved to: {out_path}")

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
