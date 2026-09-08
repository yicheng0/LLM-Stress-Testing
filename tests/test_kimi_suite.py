import unittest

from backend.app.core.kimi_suite import (
    CASE_CATALOG, KIMI_CASE_IDS, Scenario, assert_response, build_payload,
    build_progress_snapshot, build_protocol_request, classify_cache_usage,
    extract_input_tokens, validate_case_ids, assert_prompt_token_evidence,
)
from backend.app.models.schemas import KimiSuiteCreate


class KimiCatalogTest(unittest.TestCase):
    def test_catalog_has_stable_cases(self):
        self.assertEqual(tuple(case.id for case in CASE_CATALOG), KIMI_CASE_IDS)
        self.assertEqual(CASE_CATALOG[-1].id, "prompt_token_injection")

    def test_case_ids_deduplicate_and_reject_unknown(self):
        self.assertEqual(validate_case_ids(["json_output", "json_output"]), ["json_output"])
        with self.assertRaises(ValueError):
            validate_case_ids(["nope"])

    def test_schema_defaults_to_kimi_k3_and_all_cases(self):
        payload = KimiSuiteCreate(api_key="secret")
        self.assertEqual(payload.model, "kimi-k3")
        self.assertEqual(payload.endpoint, "/v1/chat/completions")
        self.assertEqual(len(payload.case_ids), 10)

    def test_schema_accepts_supported_protocols(self):
        self.assertEqual(KimiSuiteCreate(api_key="secret", api_protocol="anthropic").api_protocol, "anthropic")
        self.assertEqual(KimiSuiteCreate(api_key="secret", api_protocol="gemini").api_protocol, "gemini")


class KimiPayloadTest(unittest.TestCase):
    def test_payload_keeps_scenario_overrides_isolated(self):
        scenario = Scenario("json", "json", "reply", overrides={"response_format": {"type": "json_object"}})
        payload = build_payload("kimi-k3", scenario)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["model"], "kimi-k3")

    def test_protocol_request_uses_protocol_url_headers_and_payload(self):
        scenario = Scenario("basic", "basic", "reply")
        anthropic = build_protocol_request({
            "api_protocol": "anthropic", "base_url": "https://example.com",
            "endpoint": "/v1/messages", "model": "kimi-k3", "api_key": "secret",
        }, scenario)
        self.assertEqual(anthropic["url"], "https://example.com/v1/messages")
        self.assertEqual(anthropic["headers"]["x-api-key"], "secret")
        self.assertEqual(anthropic["payload"]["messages"][0]["role"], "user")
        self.assertNotIn("Authorization", anthropic["headers"])

        gemini = build_protocol_request({
            "api_protocol": "gemini", "base_url": "https://example.com",
            "endpoint": "/v1beta/models/{model-name}:generateContent", "model": "kimi-k3",
            "api_key": "secret", "enable_stream": False,
        }, scenario)
        self.assertEqual(gemini["url"], "https://example.com/v1beta/models/kimi-k3:generateContent")
        self.assertEqual(gemini["headers"]["x-goog-api-key"], "secret")
        self.assertIn("contents", gemini["payload"])

    def test_progress_snapshot_contains_live_case_rows(self):
        cases = [{"case_id": "cache_repeat", "case_name": "缓存命中-重复请求", "status": "passed", "elapsed_sec": 0.5, "scenarios": []}]
        snapshot = build_progress_snapshot(cases, current_case="思考控制-多场景", current_case_id="thinking", current_scenario="开启思考", total_cases=9)
        self.assertEqual(snapshot["completed_cases"], 1)
        self.assertEqual(snapshot["cases"], cases)
        self.assertEqual(snapshot["current_case_id"], "thinking")


class KimiAssertionTest(unittest.TestCase):
    def test_json_stop_tool_and_output_token_assertions(self):
        json_s = Scenario("j", "j", overrides={"response_format": {"type": "json_object"}})
        self.assertEqual(assert_response("json", {"content": '{"answer":"OK"}'}, json_s)["status"], "passed")
        self.assertEqual(assert_response("json", {"content": "nope"}, json_s)["status"], "assertion_failed")
        stop_s = Scenario("s", "s", overrides={"stop": ["5"]})
        self.assertEqual(assert_response("stop", {"content": "1,2,5"}, stop_s)["status"], "passed")
        self.assertEqual(assert_response("stop", {"content": "1,2,5,6"}, stop_s)["status"], "assertion_failed")
        out_s = Scenario("o", "o", overrides={"max_tokens": 5})
        self.assertEqual(assert_response("output_tokens", {"usage": {"completion_tokens": 5}}, out_s)["status"], "passed")
        self.assertEqual(assert_response("output_tokens", {"usage": {"completion_tokens": 6}}, out_s)["status"], "assertion_failed")

    def test_cache_classification_requires_usage_evidence(self):
        self.assertEqual(classify_cache_usage({"prompt_tokens_details": {"cached_tokens": 3}}), "cache_hit")
        self.assertEqual(classify_cache_usage({"prompt_tokens_details": {"cached_tokens": 0}}), "cache_miss")
        self.assertEqual(classify_cache_usage({"prompt_tokens": 10}), "unverifiable")

    def test_prompt_token_injection_verdicts(self):
        self.assertEqual(assert_prompt_token_evidence(100, 104)["status"], "passed")
        self.assertEqual(assert_prompt_token_evidence(100, 160)["status"], "suspected_injection")
        self.assertEqual(assert_prompt_token_evidence(100, None)["status"], "unverifiable")
        self.assertEqual(assert_prompt_token_evidence(100, 100, supported=False)["status"], "unsupported")
        self.assertEqual(assert_prompt_token_evidence(None, 100)["status"], "unverifiable")

    def test_extract_input_tokens_preserves_missing_usage(self):
        self.assertEqual(extract_input_tokens({"prompt_tokens": 12}), 12)
        self.assertEqual(extract_input_tokens({"input_tokens": 13}), 13)
        self.assertEqual(extract_input_tokens({"usageMetadata": {"promptTokenCount": 14}}), 14)
        self.assertIsNone(extract_input_tokens({"completion_tokens": 2}))


if __name__ == "__main__":
    unittest.main()
