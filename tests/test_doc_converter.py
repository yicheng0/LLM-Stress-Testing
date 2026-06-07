from __future__ import annotations

import unittest

from fastapi import HTTPException

from backend.app.api.docs import convert_curl
from backend.app.core.auth import AuthUser
from backend.app.core.doc_converter import CurlConvertError, convert_curl_to_openapi, infer_json_schema
from backend.app.models.schemas import CurlConvertRequest


class CurlDocConverterTest(unittest.TestCase):
    def test_openai_curl_generates_schema_and_sanitizes_auth(self):
        converted = convert_curl_to_openapi(
            curl="""curl https://api.openai.com/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer sk-real-key' \
  -H 'X-Request-Source: official-docs' \
  -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"Hello"}],"temperature":0.7,"stream":true}'""",
            base_url="https://api.wenwen-ai.com",
            title="LLM API 接口文档",
        )

        self.assertEqual(converted.protocol, "openai")
        self.assertEqual(converted.endpoint, "/v1/chat/completions")
        self.assertIn("Authorization: Bearer ${API_KEY}", converted.sanitized_curl)
        self.assertNotIn("sk-real-key", converted.sanitized_curl)
        self.assertIn("X-Request-Source: official-docs", converted.sanitized_curl)
        self.assertIn("properties:", converted.openapi_yaml)
        self.assertIn("messages:", converted.openapi_yaml)
        self.assertIn('type: "array"', converted.openapi_yaml)
        self.assertIn("temperature:", converted.openapi_yaml)
        self.assertIn('type: "number"', converted.openapi_yaml)
        self.assertIn("stream:", converted.openapi_yaml)
        self.assertIn('type: "boolean"', converted.openapi_yaml)
        self.assertIn("X-Request-Source", converted.openapi_yaml)

    def test_anthropic_keeps_version_and_redacts_api_key(self):
        converted = convert_curl_to_openapi(
            curl="""curl https://api.anthropic.com/v1/messages \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: sk-ant-real' \
  -H 'anthropic-version: 2023-06-01' \
  -d '{"model":"claude-test","max_tokens":1024,"messages":[{"role":"user","content":"Hello"}]}'""",
            base_url="https://api.apipro.ai",
            title="Anthropic 文档",
        )

        self.assertEqual(converted.protocol, "anthropic")
        self.assertIn("x-api-key: ${API_KEY}", converted.sanitized_curl)
        self.assertNotIn("sk-ant-real", converted.sanitized_curl)
        self.assertIn("anthropic-version: 2023-06-01", converted.sanitized_curl)
        self.assertIn('name: "anthropic-version"', converted.openapi_yaml)
        self.assertIn("required: true", converted.openapi_yaml)

    def test_gemini_extracts_model_from_url_and_redacts_key(self):
        converted = convert_curl_to_openapi(
            curl="""curl https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key=real-key \
  -H 'Content-Type: application/json' \
  -H 'x-goog-api-key: real-key' \
  -d '{"contents":[{"parts":[{"text":"Hello"}]}],"generationConfig":{"temperature":0.5,"maxOutputTokens":128}}'""",
            base_url="https://api.wenwen-ai.com",
            title="Gemini 文档",
        )

        self.assertEqual(converted.protocol, "gemini")
        self.assertEqual(converted.model, "gemini-3.1-pro-preview")
        self.assertIn("key=${API_KEY}", converted.endpoint)
        self.assertIn("x-goog-api-key: ${API_KEY}", converted.sanitized_curl)
        self.assertNotIn("real-key", converted.sanitized_curl)
        self.assertNotIn("real-key", converted.openapi_yaml)

    def test_secret_headers_are_not_preserved_but_safe_headers_are(self):
        converted = convert_curl_to_openapi(
            curl="""curl https://api.example.com/v1/responses \
  -H 'Authorization: Bearer sk-real' \
  -H 'Cookie: session=secret' \
  -H 'X-Custom-Token: custom-secret' \
  -H 'X-Tenant-Id: tenant-a' \
  -d '{"model":"gpt-5.5","input":"hello"}'""",
            base_url="https://api.wenwen-ai.com",
            title="Headers",
        )

        headers = {item["name"]: item["value"] for item in converted.headers}
        self.assertEqual(headers["Authorization"], "Bearer ${API_KEY}")
        self.assertEqual(headers["X-Tenant-Id"], "tenant-a")
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("X-Custom-Token", headers)
        self.assertNotIn("session=secret", converted.openapi_yaml)
        self.assertNotIn("custom-secret", converted.openapi_yaml)

    def test_infer_schema_handles_nested_empty_and_mixed_arrays(self):
        schema = infer_json_schema({
            "items": [1, "two"],
            "empty": [],
            "nested": {"enabled": True, "count": 2, "ratio": 1.5, "note": None},
        })

        self.assertEqual(schema["properties"]["items"]["items"]["oneOf"], [{"type": "integer"}, {"type": "string"}])
        self.assertEqual(schema["properties"]["empty"], {"type": "array", "items": {}})
        self.assertEqual(schema["properties"]["nested"]["properties"]["enabled"], {"type": "boolean"})
        self.assertEqual(schema["properties"]["nested"]["properties"]["count"], {"type": "integer"})
        self.assertEqual(schema["properties"]["nested"]["properties"]["ratio"], {"type": "number"})
        self.assertEqual(schema["properties"]["nested"]["properties"]["note"], {"type": "null"})

    def test_invalid_curl_errors_are_clear(self):
        with self.assertRaisesRegex(CurlConvertError, "未找到请求 URL"):
            convert_curl_to_openapi("curl -d '{}'", "https://api.wenwen-ai.com", "Doc")
        with self.assertRaisesRegex(CurlConvertError, "请求体不是合法 JSON"):
            convert_curl_to_openapi(
                "curl https://api.example.com/v1/chat/completions -d '{bad'",
                "https://api.wenwen-ai.com",
                "Doc",
            )

    def test_post_without_body_is_supported_for_control_endpoints(self):
        converted = convert_curl_to_openapi(
            curl="""curl -X POST https://api.openai.com/v1/responses/resp_123/cancel \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $OPENAI_API_KEY" """,
            base_url="https://api.wenwen-ai.com",
            title="Cancel",
        )

        self.assertEqual(converted.method, "POST")
        self.assertEqual(converted.endpoint, "/v1/responses/resp_123/cancel")
        self.assertEqual(converted.recognized_params, [])
        self.assertEqual(converted.unknown_params, [])
        self.assertIn("curl -X POST 'https://api.wenwen-ai.com/v1/responses/resp_123/cancel'", converted.sanitized_curl)
        self.assertIn("Authorization: Bearer ${API_KEY}", converted.sanitized_curl)
        self.assertNotIn("$OPENAI_API_KEY", converted.sanitized_curl)
        self.assertNotIn("  -d ", converted.sanitized_curl)
        self.assertNotIn("requestBody:", converted.openapi_yaml)


class CurlDocApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_convert_curl_api_rejects_guest_builtin_base_url(self):
        with self.assertRaises(HTTPException) as ctx:
            await convert_curl(
                CurlConvertRequest(
                    curl="curl https://api.openai.com/v1/chat/completions -d '{}'",
                    base_url="https://API.WENWEN-AI.com/",
                    title="Guest Docs",
                ),
                _user=AuthUser(username="guest_test", role="guest"),
            )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_convert_curl_api_allows_guest_third_party_base_url(self):
        response = await convert_curl(
            CurlConvertRequest(
                curl="""curl https://api.openai.com/v1/chat/completions \
  -H 'Authorization: Bearer sk-real-key' \
  -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"Hello"}]}'""",
                base_url="https://third-party.example.com",
                title="Guest Docs",
            ),
            _user=AuthUser(username="guest_test", role="guest"),
        )

        self.assertEqual(response.endpoint, "/v1/chat/completions")
        self.assertIn("https://third-party.example.com/v1/chat/completions", response.sanitized_curl)

    async def test_convert_curl_api_accepts_post_without_body(self):
        response = await convert_curl(
            CurlConvertRequest(
                curl="""curl -X POST https://api.openai.com/v1/responses/resp_123/cancel \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $OPENAI_API_KEY" """,
                base_url="https://api.wenwen-ai.com",
                title="Cancel",
            ),
            _user=AuthUser(username="root", role="root"),
        )

        self.assertEqual(response.method, "POST")
        self.assertEqual(response.endpoint, "/v1/responses/resp_123/cancel")
        self.assertEqual(response.recognized_params, [])
        self.assertEqual(response.unknown_params, [])
        self.assertIn("Authorization: Bearer ${API_KEY}", response.sanitized_curl)
        self.assertNotIn("$OPENAI_API_KEY", response.sanitized_curl)
        self.assertNotIn("  -d ", response.sanitized_curl)


if __name__ == "__main__":
    unittest.main()
