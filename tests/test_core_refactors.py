from __future__ import annotations

import asyncio
import json
import time
import unittest
from datetime import UTC, datetime

from backend.app.core.task_status import (
    TaskStatus,
    can_transition_task_status,
    is_active_status,
    is_terminal_status,
    stopped_final_status,
)
from backend.app.core.preflight import _body as preflight_body
from backend.app.core.repository import Repository
from backend.app.core.report_service import build_chart_data, load_chart_cache, load_details
from backend.app.models.database import TestResult as DbTestResult
from backend.app.models.database import TestTask as DbTestTask
from loadtest.chart_data import build_single_chart_data
from loadtest.config import LoadTestConfig
from loadtest.executor import RequestExecutor
from loadtest.metrics import percentile, percentile_metrics
from loadtest.runner import LoadTestRunner
from loadtest.models import RequestResult
from loadtest.protocols import build_payload
from loadtest.result_writer import ReportArtifactWriter, StreamingResultCollector
from loadtest.streaming import SseStreamParser
from loadtest.summary import MetricsAccumulator, MetricsSummaryBuilder
from test_glm_features import _chat_url


def result(**overrides):
    data = {
        "request_id": 1,
        "ok": True,
        "status": 200,
        "started_at": 1.0,
        "ended_at": 2.5,
        "latency_sec": 1.5,
        "ttft_sec": 0.4,
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "error_type": None,
        "error_message": None,
        "retry_count": 0,
    }
    data.update(overrides)
    return RequestResult(**data)


class TaskStatusTest(unittest.TestCase):
    def test_status_groups_and_transitions(self):
        self.assertTrue(is_active_status(TaskStatus.RUNNING))
        self.assertTrue(is_terminal_status("completed"))
        self.assertTrue(can_transition_task_status("queued", "running"))
        self.assertTrue(can_transition_task_status("running", "stopping"))
        self.assertFalse(can_transition_task_status("completed", "running"))

    def test_stop_request_wins_over_computed_status(self):
        self.assertEqual(stopped_final_status(True, "completed"), "cancelled")
        self.assertEqual(stopped_final_status(False, "completed"), "completed")


class MetricsAccumulatorTest(unittest.TestCase):
    def test_accumulator_matches_legacy_summary_builder(self):
        config = LoadTestConfig(duration_sec=10, warmup_requests=0)
        results = [
            result(request_id=1, latency_sec=1.0, ttft_sec=0.2, total_tokens=120),
            result(request_id=2, latency_sec=2.0, ttft_sec=0.5, total_tokens=130),
            result(
                request_id=3,
                ok=False,
                status=429,
                latency_sec=0.3,
                ttft_sec=None,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                error_type="HTTP_429",
                error_message="rate limited",
            ),
        ]

        accumulator = MetricsAccumulator()
        for item in results:
            accumulator.record(item)

        expected = MetricsSummaryBuilder(config).build(results, actual_input_tokens=100, started_at=0)
        actual = accumulator.build_summary(config, actual_input_tokens=100, started_at=0)

        self.assertEqual(actual["config"], expected["config"])
        self.assertEqual(actual["results"], expected["results"])

    def test_percentile_metrics_reuse_sorted_values(self):
        values = [4.0, 1.0, 3.0, 2.0]

        self.assertEqual(percentile(values, 0.5), 2.5)
        self.assertEqual(percentile(sorted(values), 0.5, presorted=True), 2.5)
        self.assertEqual(
            percentile_metrics(values, "latency_sec"),
            {
                "latency_sec_avg": 2.5,
                "latency_sec_p50": 2.5,
                "latency_sec_p90": 3.7,
                "latency_sec_p95": 3.85,
                "latency_sec_p99": 3.97,
            },
        )

    def test_report_writer_persists_chart_cache(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            writer = ReportArtifactWriter(tmp)
            summary = MetricsSummaryBuilder(LoadTestConfig(duration_sec=10)).build(
                [result()],
                actual_input_tokens=100,
                started_at=0,
            )
            files = writer.write_single(summary, [result()])
            charts = load_chart_cache(files["charts_path"])

            self.assertIsNotNone(charts)
            self.assertEqual(charts["detail_count"], 1)
            self.assertEqual(charts["success_count"], 1)
            self.assertIn("latency_histogram", charts)
            self.assertEqual(files["detail_count"], 1)

    def test_build_chart_data_prefers_cache_and_falls_back(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            details_path = f"{tmp}/details.jsonl"
            charts_path = f"{tmp}/charts.json"
            cached = {"detail_count": 99, "success_count": 98, "failed_count": 1}
            with open(charts_path, "w", encoding="utf-8") as f:
                json.dump(cached, f)
            with open(details_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(result().__dict__) + "\n")

            self.assertEqual(build_chart_data(None, details_path, charts_path=charts_path), cached)
            self.assertEqual(build_chart_data(None, details_path)["detail_count"], 1)

    def test_load_details_uses_cached_total_without_full_scan(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            details_path = f"{tmp}/details.jsonl"
            with open(details_path, "w", encoding="utf-8") as f:
                for i in range(10):
                    f.write(json.dumps(result(request_id=i).__dict__) + "\n")

            total, items = load_details(details_path, page=1, page_size=3, total_count=10)

            self.assertEqual(total, 10)
            self.assertEqual([item["request_id"] for item in items], [0, 1, 2])

    def test_single_chart_data_shape(self):
        charts = build_single_chart_data([result(), result(ok=False, error_type="HTTP_429", status=429)])

        self.assertEqual(charts["detail_count"], 2)
        self.assertEqual(charts["success_count"], 1)
        self.assertEqual(charts["failed_count"], 1)
        self.assertEqual(charts["error_counts"], {"HTTP_429": 1})

    def test_retry_metrics_are_reported_in_summary(self):
        config = LoadTestConfig(duration_sec=10, warmup_requests=0)
        results = [
            result(request_id=1, retry_count=2, total_tokens=120),
            result(request_id=2, retry_count=0, total_tokens=130),
        ]

        accumulator = MetricsAccumulator()
        for item in results:
            accumulator.record(item)

        summary = accumulator.build_summary(config, actual_input_tokens=100, started_at=0)
        results_summary = summary["results"]

        self.assertEqual(results_summary["total_requests"], 2)
        self.assertEqual(results_summary["successful_requests"], 2)
        self.assertEqual(results_summary["attempt_requests"], 4)
        self.assertEqual(results_summary["attempt_tokens"], 500)
        self.assertGreater(results_summary["attempt_rpm"], results_summary["rpm"])
        self.assertGreater(results_summary["attempt_tpm"], results_summary["total_tpm"])

    def test_retry_metrics_inclusive_for_failed_results(self):
        config = LoadTestConfig(duration_sec=10, warmup_requests=0)
        failed = result(
            request_id=1,
            ok=False,
            status=429,
            total_tokens=0,
            retry_count=2,
            error_type="HTTP_429",
            error_message="rate limited",
        )

        accumulator = MetricsAccumulator()
        accumulator.record(failed)
        summary = accumulator.build_summary(config, actual_input_tokens=100, started_at=0)
        results_summary = summary["results"]

        self.assertEqual(results_summary["attempt_requests"], 3)
        self.assertEqual(results_summary["attempt_tokens"], 300)

    def test_streaming_result_collector_writes_details_and_charts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            collector = StreamingResultCollector(tmp)
            collector.record(result(request_id=1))
            collector.record(result(request_id=2, ok=False, error_type="HTTP_429", status=429))
            collector.close()

            self.assertEqual(collector.detail_count, 2)
            total, items = load_details(str(collector.detail_path), page=1, page_size=10, total_count=collector.detail_count)
            charts = collector.build_charts()

            self.assertEqual(total, 2)
            self.assertEqual(len(items), 2)
            self.assertEqual(charts["detail_count"], 2)
            self.assertEqual(charts["failed_count"], 1)


class RequestPayloadTemperatureTest(unittest.TestCase):
    def test_payload_omits_temperature_when_none(self):
        cases = [
            ("openai", "/chat/completions", ("temperature",)),
            ("openai", "/responses", ("temperature",)),
            ("anthropic", "/messages", ("temperature",)),
            ("gemini", "/models/gemini-pro:generateContent", ("generationConfig", "temperature")),
        ]

        for protocol, endpoint, path in cases:
            with self.subTest(protocol=protocol, endpoint=endpoint):
                payload = build_payload(
                    protocol,
                    endpoint=endpoint,
                    model="new-model",
                    prompt="ping",
                    max_output_tokens=16,
                    temperature=None,
                    enable_stream=False,
                )
                current = payload
                for key in path[:-1]:
                    current = current[key]
                self.assertNotIn(path[-1], current)

    def test_payload_includes_temperature_when_zero_is_explicit(self):
        payload = build_payload(
            "openai",
            endpoint="/chat/completions",
            model="legacy-model",
            prompt="ping",
            max_output_tokens=16,
            temperature=0,
            enable_stream=False,
        )

        self.assertEqual(payload["temperature"], 0)

    def test_load_test_config_accepts_empty_temperature(self):
        self.assertIsNone(LoadTestConfig.from_mapping({"temperature": None}).temperature)
        self.assertIsNone(LoadTestConfig.from_mapping({"temperature": ""}).temperature)
        self.assertEqual(LoadTestConfig.from_mapping({"temperature": "0"}).temperature, 0.0)

    def test_preflight_body_omits_temperature(self):
        payload = preflight_body({
            "api_protocol": "openai",
            "endpoint": "/v1/chat/completions",
            "model": "new-model",
        })

        self.assertNotIn("temperature", payload)


class DashboardRepositoryTest(unittest.TestCase):
    def test_dashboard_snapshot_detaches_overlapping_active_and_recent_rows(self):
        repository = Repository()
        task = DbTestTask(
            id="task-1",
            name="Task",
            api_protocol="openai",
            base_url="https://example.com",
            endpoint="/v1/chat/completions",
            model="gpt-5.5",
            status="running",
            concurrency=1,
            duration_sec=1,
            input_tokens=1,
            max_output_tokens=1,
            enable_stream=True,
            matrix_mode=False,
            config_json=json.dumps({"api_protocol": "openai"}),
            created_at=datetime.now(UTC),
        )
        result_row = DbTestResult(task_id="task-1", error_message="HTTP_429: rate limited", detail_count=3)

        class FakeSession:
            def __init__(self):
                self._contains: set[int] = {id(task), id(result_row)}
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, stmt):
                self.calls += 1
                values = [
                    [(1,)],
                    [("running", 1)],
                    [("openai", 1)],
                    [("gpt-5.5", 1)],
                    [(task, result_row)],
                    [(task, result_row)],
                    [("HTTP_429: rate limited", 1)],
                ][self.calls - 1]

                class Result:
                    def __init__(self, rows):
                        self.rows = rows

                    def scalar_one(self):
                        return self.rows[0][0]

                    def all(self):
                        return self.rows

                return Result(values)

            def expunge(self, row):
                self._contains.discard(id(row))

            def __contains__(self, row):
                return id(row) in self._contains

        fake_session = FakeSession()
        repository.session = lambda: fake_session

        snapshot = repository.dashboard_snapshot()

        self.assertEqual(snapshot["total"], 1)
        self.assertEqual(snapshot["status_counts"], {"running": 1})
        self.assertEqual(snapshot["error_counts"], {"HTTP_429": 1})
        self.assertEqual(snapshot["recent_rows"][0][0].id, "task-1")
        self.assertEqual(snapshot["active_rows"][0][0].id, "task-1")


class LoadTestRunnerStopTest(unittest.IsolatedAsyncioTestCase):
    async def test_manual_stop_cancels_in_flight_request(self):
        runner = LoadTestRunner({
            "base_url": "https://example.com",
            "api_key": "test-key",
            "model": "gpt-5.5",
            "concurrency": 1,
            "duration_sec": 60,
            "input_tokens": 1,
            "warmup_requests": 0,
            "enable_stream": False,
            "timeout_sec": 60,
        })
        stop_event = asyncio.Event()
        runner.stop_event = stop_event
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_send_one(session, request_id):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        runner.send_one = fake_send_one
        runner.stop_at = time.time() + 60

        task = asyncio.create_task(runner._request_or_stop(object(), 1))
        await asyncio.wait_for(started.wait(), timeout=1)
        stop_event.set()

        result = await asyncio.wait_for(task, timeout=1)

        self.assertIsNone(result)
        self.assertTrue(cancelled.is_set())

    async def test_deadline_stops_worker_loop(self):
        runner = LoadTestRunner({
            "base_url": "https://example.com",
            "api_key": "test-key",
            "model": "gpt-5.5",
            "concurrency": 1,
            "duration_sec": 1,
            "input_tokens": 1,
            "warmup_requests": 0,
            "enable_stream": False,
            "timeout_sec": 60,
        })
        stop_event = asyncio.Event()
        runner.stop_event = stop_event
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_send_one(session, request_id):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        runner.send_one = fake_send_one
        runner.stop_at = time.time() + 0.05

        await asyncio.wait_for(runner.worker(0, object(), asyncio.Semaphore(1)), timeout=2)

        self.assertTrue(started.is_set())
        self.assertTrue(cancelled.is_set())
        self.assertTrue(stop_event.is_set())

    async def test_progress_includes_retry_metrics(self):
        runner = LoadTestRunner({
            "base_url": "https://example.com",
            "api_key": "test-key",
            "model": "gpt-5.5",
            "concurrency": 1,
            "duration_sec": 60,
            "input_tokens": 1,
            "warmup_requests": 0,
            "enable_stream": False,
            "timeout_sec": 60,
        }, retain_results=False)
        captured = {}

        async def progress(data):
            captured.update(data)

        runner.progress_callback = progress
        runner.test_start_wall_time = time.time() - 10
        runner._success_count = 1
        runner._success_token_count = 120
        runner._attempt_count = 3
        runner._attempt_token_count = 300
        runner.metrics_accumulator.total_requests = 1

        await runner.emit_progress(force=True)

        self.assertIn("attempt_rpm", captured)
        self.assertIn("attempt_tpm", captured)
        self.assertGreater(captured["attempt_rpm"], captured["current_rpm"])
        self.assertGreater(captured["attempt_tpm"], captured["current_tpm"])


class StreamParserTest(unittest.IsolatedAsyncioTestCase):
    async def test_parse_stream_handles_chunked_sse_lines(self):
        parser = SseStreamParser()

        class FakeContent:
            def __init__(self, chunks):
                self._chunks = chunks

            def iter_any(self):
                async def generator():
                    for chunk in self._chunks:
                        yield chunk
                return generator()

        chunks = [
            b"data: {\"usage\":{\"completion_tokens\":3",
            b",\"prompt_tokens\":2,\"total_tokens\":5}}\n",
            b"data: [DONE]\n",
        ]
        ttft, output_tokens, total_tokens, protocol_error = await parser.parse_stream(FakeContent(chunks), time.perf_counter())

        self.assertIsNotNone(ttft)
        self.assertEqual(output_tokens, 3)
        self.assertEqual(total_tokens, 5)
        self.assertIsNone(protocol_error)


class RequestExecutorCacheTest(unittest.TestCase):
    def test_executor_builds_static_request_parts_once(self):
        calls = {"url": 0, "headers": 0, "payload": 0}

        class CountingExecutor(RequestExecutor):
            def build_url(self):
                calls["url"] += 1
                return super().build_url()

            def build_headers(self):
                calls["headers"] += 1
                return super().build_headers()

            def build_payload(self):
                calls["payload"] += 1
                return super().build_payload()

        executor = CountingExecutor(
            LoadTestConfig(
                base_url="https://example.com",
                api_key="test-key",
                model="gpt-5.5",
                concurrency=1,
                duration_sec=1,
                input_tokens=1,
                warmup_requests=0,
                enable_stream=False,
            ),
            prompt="hello",
            actual_input_tokens=1,
            backoff=lambda attempt: 0,
        )

        self.assertEqual(calls, {"url": 1, "headers": 1, "payload": 1})
        self.assertEqual(executor._url, executor.build_url())
        self.assertEqual(executor._headers, executor.build_headers())
        self.assertEqual(executor._payload, executor.build_payload())


class RequestExecutorRetryTest(unittest.IsolatedAsyncioTestCase):
    def create_executor(self, *, retry_sleep=None, max_retries=1, backoff=lambda attempt: 5):
        return RequestExecutor(
            LoadTestConfig(
                base_url="https://example.com",
                api_key="test-key",
                model="gpt-5.5",
                concurrency=1,
                duration_sec=1,
                input_tokens=1,
                max_retries=max_retries,
                retry_backoff_max=8,
                warmup_requests=0,
                enable_stream=False,
            ),
            prompt="hello",
            actual_input_tokens=1,
            backoff=backoff,
            retry_sleep=retry_sleep,
        )

    async def test_retryable_http_uses_injected_sleep_and_retries(self):
        sleeps = []

        async def retry_sleep(seconds):
            sleeps.append(seconds)
            return True

        executor = self.create_executor(retry_sleep=retry_sleep, backoff=lambda attempt: 2)
        session = FakeSession([
            FakeResponse(429, "rate limited"),
            FakeResponse(200, '{"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}'),
        ])

        result_item = await executor.send_one(session, 1)

        self.assertTrue(result_item.ok)
        self.assertEqual(result_item.retry_count, 1)
        self.assertEqual(sleeps, [2])
        self.assertEqual(session.calls, 2)

    async def test_retry_after_header_is_capped_by_retry_backoff_max(self):
        sleeps = []

        async def retry_sleep(seconds):
            sleeps.append(seconds)
            return True

        executor = self.create_executor(retry_sleep=retry_sleep, backoff=lambda attempt: 2)
        session = FakeSession([
            FakeResponse(429, "rate limited", headers={"Retry-After": "30"}),
            FakeResponse(500, "failed"),
        ])

        result_item = await executor.send_one(session, 1)

        self.assertFalse(result_item.ok)
        self.assertEqual(result_item.status, 500)
        self.assertEqual(sleeps, [8])

    async def test_cancelled_retry_sleep_stops_before_next_attempt(self):
        async def retry_sleep(seconds):
            return False

        executor = self.create_executor(retry_sleep=retry_sleep)
        session = FakeSession([
            FakeResponse(429, "rate limited"),
            FakeResponse(200, '{"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}'),
        ])

        with self.assertRaises(asyncio.CancelledError):
            await executor.send_one(session, 1)

        self.assertEqual(session.calls, 1)


class FakeResponse:
    def __init__(self, status, text, headers=None):
        self.status = status
        self._text = text
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("No fake response queued")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FeatureScriptTest(unittest.TestCase):
    def test_chat_url_accepts_base_url_with_or_without_v1(self):
        self.assertEqual("https://api.example.com/v1/chat/completions", _chat_url("https://api.example.com"))
        self.assertEqual("https://api.example.com/v1/chat/completions", _chat_url("https://api.example.com/v1"))
        self.assertEqual(
            "https://api.example.com/v1/chat/completions",
            _chat_url("https://api.example.com/v1/chat/completions"),
        )


if __name__ == "__main__":
    unittest.main()
