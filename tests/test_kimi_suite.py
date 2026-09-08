import unittest

from backend.app.core.kimi_suite import (
    CASE_CATALOG, KIMI_CASE_IDS, Scenario, assert_response, build_payload,
    classify_cache_usage, validate_case_ids,
)
from backend.app.models.schemas import KimiSuiteCreate


class KimiCatalogTest(unittest.TestCase):
    def test_catalog_has_nine_stable_cases(self):
        self.assertEqual(tuple(case.id for case in CASE_CATALOG), KIMI_CASE_IDS)

    def test_case_ids_deduplicate_and_reject_unknown(self):
        self.assertEqual(validate_case_ids(["json_output", "json_output"]), ["json_output"])
        with self.assertRaises(ValueError):
            validate_case_ids(["nope"])

    def test_schema_defaults_to_kimi_k3_and_all_cases(self):
        payload = KimiSuiteCreate(api_key="secret")
        self.assertEqual(payload.model, "kimi-k3")
        self.assertEqual(payload.endpoint, "/v1/chat/completions")
        self.assertEqual(len(payload.case_ids), 9)


class KimiPayloadTest(unittest.TestCase):
    def test_payload_keeps_scenario_overrides_isolated(self):
        scenario = Scenario("json", "json", "reply", overrides={"response_format": {"type": "json_object"}})
        payload = build_payload("kimi-k3", scenario)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["model"], "kimi-k3")


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


if __name__ == "__main__":
    unittest.main()
