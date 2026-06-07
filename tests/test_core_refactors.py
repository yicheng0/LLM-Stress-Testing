from __future__ import annotations

import asyncio
import hashlib
import json
import time
import unittest
from datetime import UTC, datetime

from fastapi import HTTPException

from backend.app.api import tests as tests_api
from backend.app.core.auth import AuthUser
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
from backend.app.core.doc_converter import CurlConvertError, convert_curl_to_openapi, infer_json_schema
from backend.app.models.database import TestResult as DbTestResult
from backend.app.models.database import TestTask as DbTestTask
from backend.app.models.schemas import CustomCaseBatchCase, CustomCaseBatchChannel, CustomCaseBatchRequest, TestCreate
from loadtest.chart_data import build_single_chart_data
from loadtest.config import LoadTestConfig
from loadtest.executor import RequestExecutor
from loadtest.metrics import percentile, percentile_metrics
from loadtest.runner import LoadTestRunner, matrix_result_key, should_reuse_matrix_result
from loadtest.models import RequestResult
from loadtest.protocols import build_payload, extract_token_usage
from loadtest.reports import generate_matrix_csv, render_html_report, render_markdown_report, render_matrix_report
from loadtest.result_writer import ReportArtifactWriter, StreamingResultCollector
from loadtest.streaming import SseStreamParser
from loadtest.summary import MetricsAccumulator, MetricsSummaryBuilder, retry_attempt_tokens
from test_glm_features import _chat_url

ROOT_USER = AuthUser(username="root", role="root")


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
        self.assertEqual(retry_attempt_tokens(results[0]), 320)
        self.assertEqual(retry_attempt_tokens(results[1]), 120)
        self.assertEqual(results_summary["attempt_tokens"], 440)
        legacy_summary = MetricsSummaryBuilder(config).build(results, actual_input_tokens=100, started_at=0)
        self.assertEqual(legacy_summary["results"]["attempt_tokens"], results_summary["attempt_tokens"])
        self.assertGreater(results_summary["attempt_rpm"], results_summary["rpm"])
        self.assertGreater(results_summary["attempt_tpm"], results_summary["total_tpm"])

    def test_cache_metrics_are_reported_in_summary(self):
        config = LoadTestConfig(duration_sec=10, warmup_requests=0)
        results = [
            result(
                request_id=1,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                cached_input_tokens=40,
                cache_creation_input_tokens=10,
                cache_inclusive_total_tokens=170,
            ),
            result(
                request_id=2,
                input_tokens=80,
                output_tokens=20,
                total_tokens=100,
                cached_input_tokens=20,
                cache_creation_input_tokens=0,
                cache_inclusive_total_tokens=100,
            ),
        ]

        accumulator = MetricsAccumulator()
        for item in results:
            accumulator.record(item)

        summary = accumulator.build_summary(config, actual_input_tokens=100, started_at=0)
        results_summary = summary["results"]

        self.assertEqual(results_summary["total_cached_input_tokens"], 60)
        self.assertEqual(results_summary["total_cache_creation_input_tokens"], 10)
        self.assertEqual(results_summary["total_cache_inclusive_tokens"], 270)
        self.assertEqual(results_summary["cache_hit_tpm"], 360.0)
        self.assertEqual(results_summary["cache_inclusive_tpm"], 1620.0)
        self.assertEqual(results_summary["cache_hit_rate"], 0.3333)

        markdown = render_markdown_report(summary)
        html = render_html_report(summary, results)

        self.assertIn("含缓存总计", markdown)
        self.assertIn("1,620", markdown)
        self.assertIn("含缓存 TPM", html)
        self.assertIn("1,620", html)

    def test_matrix_exports_include_cache_inclusive_tpm(self):
        point = {
            "config": {
                "base_url": "https://api.example.com",
                "model": "gpt-5.5",
                "duration_sec": 10,
                "enable_stream": True,
            },
            "matrix_config": {
                "input_tokens": 1000,
                "concurrency": 10,
            },
            "results": {
                "rpm": 60,
                "qps": 1,
                "input_tpm": 6000,
                "output_tpm": 1200,
                "total_tpm": 7200,
                "cache_inclusive_tpm": 9600,
                "cache_hit_tpm": 2400,
                "input_tps": 100,
                "output_tps": 20,
                "total_tps": 120,
                "success_rate": 1.0,
                "latency_sec_avg": 1.0,
                "latency_sec_p50": 1.0,
                "latency_sec_p95": 1.2,
                "latency_sec_p99": 1.3,
                "ttft_sec_avg": 0.2,
                "ttft_sec_p50": 0.2,
                "ttft_sec_p95": 0.3,
                "ttft_sec_p99": 0.4,
                "decode_sec_avg": 0.8,
                "decode_sec_p95": 1.0,
            },
        }

        markdown = render_matrix_report([point])
        csv = generate_matrix_csv([point])

        self.assertIn("含缓存 TPM 矩阵", markdown)
        self.assertIn("9,600", markdown)
        self.assertIn("cache_inclusive_tpm,cache_hit_tpm", csv)
        self.assertIn(",7200,9600.0,2400,", csv)

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


class CustomPromptConfigTest(unittest.TestCase):
    def test_runner_uses_custom_prompt_and_counts_actual_tokens(self):
        prompt = "请分析这条真实业务输入的首 token 延迟。"
        runner = LoadTestRunner({
            "base_url": "https://example.com",
            "api_key": "test-key",
            "model": "gpt-5.5",
            "concurrency": 1,
            "duration_sec": 1,
            "input_tokens": 9999,
            "warmup_requests": 0,
            "enable_stream": False,
            "prompt_source": "custom",
            "custom_prompt": prompt,
        })

        self.assertEqual(runner.prompt, prompt)
        self.assertEqual(runner.actual_input_tokens, runner.estimator.count(prompt))
        self.assertNotEqual(runner.actual_input_tokens, 9999)

    def test_runner_keeps_synthetic_prompt_default(self):
        runner = LoadTestRunner({
            "base_url": "https://example.com",
            "api_key": "test-key",
            "model": "gpt-5.5",
            "concurrency": 1,
            "duration_sec": 1,
            "input_tokens": 3,
            "warmup_requests": 0,
            "enable_stream": False,
        })

        self.assertEqual(runner.actual_input_tokens, 3)
        self.assertNotEqual(runner.prompt, "")

    def test_custom_prompt_metadata_is_saved_with_summary_config(self):
        prompt = "custom ttft prompt"
        config = LoadTestConfig(
            duration_sec=10,
            warmup_requests=0,
            prompt_source="custom",
            custom_prompt=prompt,
        )
        summary = MetricsAccumulator().build_summary(config, actual_input_tokens=4, started_at=0)

        self.assertEqual(summary["config"]["prompt_source"], "custom")
        self.assertEqual(summary["config"]["custom_prompt"], prompt)
        self.assertEqual(summary["config"]["custom_prompt_chars"], len(prompt))
        self.assertEqual(
            summary["config"]["custom_prompt_sha256"],
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )

    def test_custom_prompt_schema_rejects_empty_and_matrix_mode(self):
        base = {
            "api_key": "test-key",
            "prompt_source": "custom",
            "custom_prompt": "hello",
        }

        self.assertEqual(TestCreate(**base).custom_prompt, "hello")
        with self.assertRaises(ValueError):
            TestCreate(**{**base, "custom_prompt": "   "})
        with self.assertRaises(ValueError):
            TestCreate(**{**base, "matrix_mode": True})

    def test_repository_persists_custom_prompt_metadata_and_redacts_api_key(self):
        prompt = "保存完整自定义输入"
        payload = TestCreate(
            api_key="test-key",
            prompt_source="custom",
            custom_prompt=prompt,
            concurrency=1,
            duration_sec=10,
            input_tokens=1,
        )

        class FakeSession:
            def __init__(self):
                self.task = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def add(self, item):
                if isinstance(item, DbTestTask):
                    self.task = item

            def commit(self):
                return None

            def refresh(self, item):
                return None

        fake_session = FakeSession()
        repository = Repository()
        repository.session = lambda: fake_session

        task = repository.create_task("task-custom", payload, ROOT_USER)
        saved = json.loads(task.config_json)

        self.assertNotIn("api_key", saved)
        self.assertEqual(saved["custom_prompt"], prompt)
        self.assertEqual(saved["custom_prompt_chars"], len(prompt))
        self.assertEqual(saved["custom_prompt_sha256"], hashlib.sha256(prompt.encode("utf-8")).hexdigest())

    def test_export_reports_show_custom_prompt_metadata(self):
        prompt = "custom report prompt"
        config = LoadTestConfig(
            duration_sec=10,
            warmup_requests=0,
            prompt_source="custom",
            custom_prompt=prompt,
        )
        summary = MetricsSummaryBuilder(config).build([result()], actual_input_tokens=4, started_at=0)

        markdown = render_markdown_report(summary)
        html = render_html_report(summary, [result()])

        self.assertIn("输入来源: **自定义输入 Case**", markdown)
        self.assertIn("自定义输入字符数", markdown)
        self.assertIn(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), markdown)
        self.assertIn("输入来源: 自定义输入 Case", html)
        self.assertIn("自定义输入", html)


class MatrixResumeTest(unittest.IsolatedAsyncioTestCase):
    def _task(self, task_id: str, *, matrix_mode: bool, status: str = "completed") -> DbTestTask:
        return DbTestTask(
            id=task_id,
            name="matrix",
            api_protocol="openai",
            base_url="https://api.wenwen-ai.com",
            endpoint="/v1/chat/completions",
            model="gpt-5.5",
            status=status,
            concurrency=50,
            duration_sec=60,
            input_tokens=1000,
            max_output_tokens=128,
            enable_stream=True,
            matrix_mode=matrix_mode,
            config_json=json.dumps({
                "name": "matrix",
                "api_protocol": "openai",
                "base_url": "https://api.wenwen-ai.com",
                "endpoint": "/v1/chat/completions",
                "model": "gpt-5.5",
                "concurrency": 50,
                "duration_sec": 60,
                "input_tokens": 1000,
                "max_output_tokens": 128,
                "enable_stream": True,
                "matrix_mode": matrix_mode,
                "input_tokens_list": "1000,2000",
                "concurrency_list": "50",
            }, ensure_ascii=False),
            created_at=datetime.now(UTC),
        )

    def test_reuse_policy_keeps_successful_points_only(self):
        successful = {
            "matrix_config": {"input_tokens": 1000, "concurrency": 50},
            "results": {"total_requests": 3, "successful_requests": 1, "success_rate": 33.3},
        }
        failed = {
            "matrix_config": {"input_tokens": 2000, "concurrency": 50},
            "results": {"total_requests": 3, "successful_requests": 0, "success_rate": 0},
        }
        empty = {
            "matrix_config": {"input_tokens": 3000, "concurrency": 50},
            "results": {"total_requests": 0, "successful_requests": 0, "success_rate": 0},
        }

        self.assertTrue(should_reuse_matrix_result(successful))
        self.assertFalse(should_reuse_matrix_result(failed))
        self.assertFalse(should_reuse_matrix_result(empty))
        self.assertEqual(matrix_result_key(successful), "1000:50")

    async def test_run_matrix_skips_successful_points_and_reruns_failed_or_missing_points(self):
        runner = LoadTestRunner({
            "base_url": "https://example.com",
            "api_key": "test-key",
            "model": "gpt-5.5",
            "input_tokens": 1000,
            "concurrency": 50,
            "matrix_mode": True,
            "input_tokens_list": "1000,2000,3000",
            "concurrency_list": "50",
            "matrix_duration_sec": 1,
            "warmup_requests": 0,
            "enable_stream": False,
        })
        existing_success = {
            "matrix_config": {"input_tokens": 1000, "concurrency": 50},
            "results": {"total_requests": 2, "successful_requests": 2, "success_rate": 100.0},
        }
        existing_failed = {
            "matrix_config": {"input_tokens": 2000, "concurrency": 50},
            "results": {"total_requests": 2, "successful_requests": 0, "success_rate": 0.0},
        }
        calls = []

        async def fake_run():
            calls.append((runner.config.input_tokens, runner.config.concurrency))
            return {
                "results": {"total_requests": 1, "successful_requests": 1, "success_rate": 100.0},
            }

        runner.run = fake_run
        runner._prompt_for_tokens = lambda tokens: (f"prompt {tokens}", tokens)
        runner._sleep_or_stop = lambda seconds: asyncio.sleep(0, result=True)

        results = await runner.run_matrix(existing_matrix_results=[existing_success, existing_failed])

        self.assertEqual(calls, [(2000, 50), (3000, 50)])
        self.assertEqual([matrix_result_key(item) for item in results], ["1000:50", "2000:50", "3000:50"])
        self.assertEqual([item["matrix_resume_source"] for item in results], ["existing", "rerun", "rerun"])
        self.assertEqual([item["matrix_config"]["test_index"] for item in results], [1, 2, 3])
        self.assertEqual([item["matrix_config"]["total_tests"] for item in results], [3, 3, 3])
        self.assertEqual(runner.config.input_tokens, 1000)
        self.assertEqual(runner.config.concurrency, 50)

    async def test_resume_api_rejects_non_matrix_tasks(self):
        class FakeRepository:
            def get_task(self, task_id):
                return self_task, None

        self_task = self._task("single-task", matrix_mode=False)

        with self.assertRaises(HTTPException) as ctx:
            await tests_api.resume_matrix_test(
                "single-task",
                tests_api.MatrixResumeRequest(api_key="test-key"),
                user=ROOT_USER,
                repository=FakeRepository(),
                manager=object(),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "非矩阵任务不能续跑")

    async def test_resume_api_starts_new_task_from_existing_matrix_summary(self):
        existing_point = {
            "matrix_config": {"input_tokens": 1000, "concurrency": 50},
            "results": {"total_requests": 1, "successful_requests": 1, "success_rate": 100.0},
        }
        source_task = self._task("source-task", matrix_mode=True)
        source_result = DbTestResult(
            task_id="source-task",
            summary_json=json.dumps({"matrix": True, "results_matrix": [existing_point]}, ensure_ascii=False),
        )
        new_task = self._task("new-task", matrix_mode=True, status="queued")

        class FakeRepository:
            def __init__(self):
                self.events = []

            def get_task(self, task_id):
                if task_id == "source-task":
                    return source_task, source_result
                if task_id == "new-task":
                    return new_task, None
                return None

            def add_event(self, task_id, level, message):
                self.events.append((task_id, level, message))

        class FakeManager:
            def __init__(self):
                self.call = None

            async def resume_matrix_test(self, *args, **kwargs):
                self.call = (args, kwargs)
                return "new-task"

        repository = FakeRepository()
        manager = FakeManager()

        response = await tests_api.resume_matrix_test(
            "source-task",
            tests_api.MatrixResumeRequest(api_key="test-key"),
            user=ROOT_USER,
            repository=repository,
            manager=manager,
        )

        self.assertEqual(response.test_id, "new-task")
        self.assertEqual(response.status, "queued")
        self.assertEqual(manager.call[0][0], "source-task")
        self.assertEqual(manager.call[0][2], "test-key")
        self.assertEqual(manager.call[0][3], [existing_point])
        self.assertEqual(manager.call[1]["resume_policy"], "missing_or_failed")
        self.assertEqual(repository.events[0][0], "new-task")
        self.assertIn("source-task", repository.events[0][2])

    def test_repository_redacts_api_key_from_resume_config(self):
        payload = TestCreate(
            api_key="resume-secret-key",
            matrix_mode=True,
            resume_from_task_id="source-task",
            resume_policy="missing_or_failed",
            input_tokens_list="1000",
            concurrency_list="50",
        )

        class FakeSession:
            def __init__(self):
                self.task = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def add(self, item):
                if isinstance(item, DbTestTask):
                    self.task = item

            def commit(self):
                return None

            def refresh(self, item):
                return None

        fake_session = FakeSession()
        repository = Repository()
        repository.session = lambda: fake_session

        repository.create_task("resume-task", payload, ROOT_USER)
        saved = json.loads(fake_session.task.config_json)

        self.assertNotIn("api_key", saved)
        self.assertEqual(saved["resume_from_task_id"], "source-task")
        self.assertEqual(saved["resume_policy"], "missing_or_failed")

    async def test_start_test_rejects_guest_builtin_base_url(self):
        class FakeRepository:
            def get_task(self, task_id):
                return None

        class FakeManager:
            async def start_test(self, payload, user):
                return "unused"

        payload = TestCreate(api_key="test-key", base_url="https://API.WENWEN-AI.com/")

        with self.assertRaises(HTTPException) as ctx:
            await tests_api.start_test(
                payload,
                user=AuthUser(username="guest_test", role="guest"),
                repository=FakeRepository(),
                manager=FakeManager(),
            )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_start_test_rejects_root_third_party_base_url(self):
        class FakeRepository:
            def get_task(self, task_id):
                return None

        class FakeManager:
            async def start_test(self, payload, user):
                return "unused"

        payload = TestCreate(api_key="test-key", base_url="https://third-party.example.com")

        with self.assertRaises(HTTPException) as ctx:
            await tests_api.start_test(
                payload,
                user=AuthUser(username="root", role="root"),
                repository=FakeRepository(),
                manager=FakeManager(),
            )

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_resume_matrix_rejects_guest_builtin_source_task(self):
        source_task = self._task("source-task", matrix_mode=True)
        source_task.base_url = "https://api.apipro.ai/"
        source_task.owner_username = "guest_test"

        class FakeRepository:
            def get_task(self, task_id):
                return source_task, None

        with self.assertRaises(HTTPException) as ctx:
            await tests_api.resume_matrix_test(
                "source-task",
                tests_api.MatrixResumeRequest(api_key="test-key"),
                user=AuthUser(username="guest_test", role="guest"),
                repository=FakeRepository(),
                manager=object(),
            )

        self.assertEqual(ctx.exception.status_code, 403)


class CustomCaseBatchTest(unittest.IsolatedAsyncioTestCase):
    def test_batch_request_rejects_more_than_twelve_combinations(self):
        cases = [
            CustomCaseBatchCase(name=f"case-{index}", prompt="hello")
            for index in range(4)
        ]
        channels = [
            CustomCaseBatchChannel(
                name=f"channel-{index}",
                base_url="https://example.com",
                endpoint="/v1/chat/completions",
                model="gpt-5.5",
                api_key="test-key",
            )
            for index in range(4)
        ]

        with self.assertRaises(ValueError):
            CustomCaseBatchRequest(cases=cases, channels=channels)

    async def test_custom_case_batch_expands_cases_and_channels(self):
        class FakeManager:
            def __init__(self):
                self.payloads = []

            async def start_test(self, payload, user):
                self.payloads.append(payload)
                return f"task-{len(self.payloads)}"

        manager = FakeManager()
        payload = CustomCaseBatchRequest(
            batch_name="渠道诊断",
            cases=[
                CustomCaseBatchCase(name="短问答", prompt="hello"),
                CustomCaseBatchCase(name="长上下文", prompt="请分析这段输入"),
            ],
            channels=[
                CustomCaseBatchChannel(
                    name="国内",
                    base_url="https://api.wenwen-ai.com",
                    endpoint="/v1/chat/completions",
                    model="gpt-5.5",
                    api_key="domestic-key",
                ),
                CustomCaseBatchChannel(
                    name="海外",
                    base_url="https://api.apipro.ai",
                    endpoint="/v1/chat/completions",
                    model="gpt-5.5",
                    api_key="oversea-key",
                ),
            ],
            concurrency=2,
            duration_sec=5,
        )

        response = await tests_api.start_custom_case_batch(payload, user=ROOT_USER, manager=manager)

        self.assertEqual(response.total, 4)
        self.assertEqual(response.started, 4)
        self.assertEqual(response.failures, [])
        self.assertEqual(response.test_ids, ["task-1", "task-2", "task-3", "task-4"])
        first = manager.payloads[0]
        self.assertEqual(first.prompt_source, "custom")
        self.assertEqual(first.custom_prompt, "hello")
        self.assertFalse(first.matrix_mode)
        self.assertEqual(first.batch_name, "渠道诊断")
        self.assertEqual(first.batch_case_name, "短问答")
        self.assertEqual(first.batch_case_index, 1)
        self.assertEqual(first.batch_channel_name, "国内")
        self.assertEqual(first.batch_channel_index, 1)
        self.assertEqual(first.batch_total_tests, 4)
        self.assertEqual(first.concurrency, 2)
        self.assertEqual(first.duration_sec, 5)

    async def test_custom_case_batch_keeps_successes_when_one_item_fails(self):
        class FakeManager:
            def __init__(self):
                self.calls = 0

            async def start_test(self, payload, user):
                self.calls += 1
                if payload.batch_channel_name == "失败渠道":
                    raise ValueError("preflight failed")
                return "task-ok"

        payload = CustomCaseBatchRequest(
            batch_name="渠道诊断",
            cases=[CustomCaseBatchCase(name="case", prompt="hello")],
            channels=[
                CustomCaseBatchChannel(
                    name="成功渠道",
                    base_url="https://api.wenwen-ai.com",
                    endpoint="/v1/chat/completions",
                    model="gpt-5.5",
                    api_key="ok-key",
                ),
                CustomCaseBatchChannel(
                    name="失败渠道",
                    base_url="https://api.apipro.ai",
                    endpoint="/v1/chat/completions",
                    model="gpt-5.5",
                    api_key="bad-key",
                ),
            ],
        )

        response = await tests_api.start_custom_case_batch(payload, user=ROOT_USER, manager=FakeManager())

        self.assertEqual(response.started, 1)
        self.assertEqual(response.test_ids, ["task-ok"])
        self.assertEqual(len(response.failures), 1)
        self.assertEqual(response.failures[0].channel_name, "失败渠道")
        self.assertIn("preflight failed", response.failures[0].message)

    def test_repository_redacts_api_key_from_batch_config(self):
        payload = TestCreate(
            api_key="batch-secret-key",
            prompt_source="custom",
            custom_prompt="hello",
            batch_id="batch-1",
            batch_name="渠道诊断",
            batch_case_name="case",
            batch_case_index=1,
            batch_channel_name="domestic",
            batch_channel_index=1,
            batch_total_tests=2,
        )

        class FakeSession:
            def __init__(self):
                self.task = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def add(self, item):
                if isinstance(item, DbTestTask):
                    self.task = item

            def commit(self):
                return None

            def refresh(self, item):
                return None

        fake_session = FakeSession()
        repository = Repository()
        repository.session = lambda: fake_session

        repository.create_task("batch-task", payload, ROOT_USER)
        saved = json.loads(fake_session.task.config_json)

        self.assertNotIn("api_key", saved)
        self.assertEqual(saved["batch_id"], "batch-1")
        self.assertEqual(saved["batch_case_name"], "case")
        self.assertEqual(saved["batch_channel_name"], "domestic")
        self.assertEqual(saved["batch_total_tests"], 2)


class TokenUsageParsingTest(unittest.TestCase):
    def test_openai_cached_tokens_do_not_double_count_total(self):
        usage = extract_token_usage({
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 40},
        })

        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(usage.cached_input_tokens, 40)
        self.assertEqual(usage.cache_inclusive_total_tokens, 120)

    def test_anthropic_cache_read_and_creation_are_cache_inclusive(self):
        usage = extract_token_usage({
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 10,
        })

        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(usage.cached_input_tokens, 40)
        self.assertEqual(usage.cache_creation_input_tokens, 10)
        self.assertEqual(usage.cache_inclusive_total_tokens, 170)

    def test_gemini_cached_content_does_not_double_count_total(self):
        usage = extract_token_usage({
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "totalTokenCount": 120,
            "cachedContentTokenCount": 40,
        })

        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(usage.cached_input_tokens, 40)
        self.assertEqual(usage.cache_inclusive_total_tokens, 120)

    def test_gateway_prompt_cache_hit_tokens_are_supported(self):
        usage = extract_token_usage({
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
            "completion_tokens": 20,
        })

        self.assertEqual(usage.cached_input_tokens, 40)
        self.assertEqual(usage.total_tokens, 20)
        self.assertEqual(usage.cache_inclusive_total_tokens, 120)


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

        snapshot = repository.dashboard_snapshot(ROOT_USER)

        self.assertEqual(snapshot["total"], 1)
        self.assertEqual(snapshot["status_counts"], {"running": 1})
        self.assertEqual(snapshot["error_counts"], {"HTTP_429": 1})
        self.assertEqual(snapshot["recent_rows"][0][0].id, "task-1")
        self.assertEqual(snapshot["active_rows"][0][0].id, "task-1")

    def test_dashboard_task_item_includes_cache_metrics_from_progress_and_summary(self):
        task = DbTestTask(
            id="task-cache",
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
        result_row = DbTestResult(
            task_id="task-cache",
            summary_json=json.dumps({
                "results": {
                    "rpm": 1,
                    "total_tpm": 100,
                    "cache_hit_tpm": 20,
                    "cache_inclusive_tpm": 120,
                    "total_cached_input_tokens": 40,
                    "cache_hit_rate": 0.25,
                },
            }),
        )

        class FakeProgressHub:
            def snapshot(self, task_id):
                return {
                    "current_rpm": 2,
                    "current_tpm": 200,
                    "current_cache_hit_tpm": 60,
                    "current_cache_inclusive_tpm": 260,
                    "current_cached_input_tokens": 80,
                    "current_cache_hit_rate": 0.4,
                }

        task_item, metric_item, _targets, _is_active = tests_api._dashboard_task_item(
            task,
            result_row,
            FakeProgressHub(),
            {"running"},
        )

        self.assertEqual(task_item["cache_hit_tpm"], 60)
        self.assertEqual(task_item["cache_inclusive_tpm"], 260)
        self.assertEqual(task_item["cached_input_tokens"], 80)
        self.assertEqual(task_item["cache_hit_rate"], 0.4)
        self.assertEqual(metric_item["cache_hit_tpm"], 60)

        task.status = "completed"
        task_item, metric_item, _targets, _is_active = tests_api._dashboard_task_item(
            task,
            result_row,
            FakeProgressHub(),
            {"running"},
        )

        self.assertEqual(task_item["cache_hit_tpm"], 20)
        self.assertEqual(task_item["cache_inclusive_tpm"], 120)
        self.assertEqual(task_item["cached_input_tokens"], 40)
        self.assertEqual(task_item["cache_hit_rate"], 0.25)
        self.assertEqual(metric_item["cache_inclusive_tpm"], 120)


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
        runner._success_cached_input_count = 40
        runner._success_cache_inclusive_token_count = 120
        runner.metrics_accumulator.total_input_tokens = 100
        runner.metrics_accumulator.total_cached_input_tokens = 40
        runner._attempt_count = 3
        runner._attempt_token_count = 300
        runner.metrics_accumulator.total_requests = 1

        await runner.emit_progress(force=True)

        self.assertIn("current_cache_hit_tpm", captured)
        self.assertIn("current_cache_inclusive_tpm", captured)
        self.assertIn("current_cached_input_tokens", captured)
        self.assertIn("current_cache_hit_rate", captured)
        self.assertGreater(captured["current_cache_hit_tpm"], 0)
        self.assertGreater(captured["current_cache_inclusive_tpm"], 0)
        self.assertEqual(captured["current_cached_input_tokens"], 40)
        self.assertIn("attempt_rpm", captured)
        self.assertIn("attempt_tpm", captured)
        self.assertGreater(captured["attempt_rpm"], captured["current_rpm"])
        self.assertGreater(captured["attempt_tpm"], captured["current_tpm"])

    async def test_cache_warmup_is_excluded_from_formal_summary(self):
        runner = LoadTestRunner({
            "base_url": "https://example.com",
            "api_key": "test-key",
            "model": "gpt-5.5",
            "concurrency": 1,
            "duration_sec": 1,
            "input_tokens": 1,
            "warmup_requests": 0,
            "cache_test_enabled": True,
            "cache_warmup_requests": 2,
            "enable_stream": False,
            "timeout_sec": 60,
        }, retain_results=True)
        sent_prompts = []
        progress_events = []

        async def progress(data):
            progress_events.append(dict(data))

        async def fake_send_one(session, request_id):
            sent_prompts.append(runner.prompt)
            if runner.phase == "cache_warmup":
                return result(
                    request_id=request_id,
                    input_tokens=100,
                    output_tokens=1,
                    total_tokens=101,
                    cached_input_tokens=0,
                    cache_creation_input_tokens=100,
                    cache_inclusive_total_tokens=101,
                )
            if request_id <= 2:
                if request_id == 2:
                    runner.stop_event.set()
                return result(
                    request_id=request_id,
                    input_tokens=100,
                    output_tokens=1,
                    total_tokens=101,
                    cached_input_tokens=80,
                    cache_creation_input_tokens=0,
                    cache_inclusive_total_tokens=181,
                )
            return None

        runner.send_one = fake_send_one
        runner.progress_callback = progress
        runner.stop_event = asyncio.Event()

        summary = await runner.run()

        self.assertEqual(summary["results"]["total_requests"], 2)
        self.assertEqual(summary["results"]["total_cached_input_tokens"], 160)
        self.assertEqual(summary["results"]["total_cache_creation_input_tokens"], 0)
        self.assertEqual(summary["config"]["cache_test_enabled"], True)
        self.assertEqual(summary["config"]["cache_warmup_requests"], 2)
        self.assertEqual([item.request_id for item in runner.results], [1, 2])
        self.assertEqual(len(set(sent_prompts)), 1)
        cache_events = [event for event in progress_events if event.get("phase") == "cache_warmup"]
        self.assertTrue(cache_events)
        self.assertEqual(cache_events[-1]["cache_warmup_completed"], 2)


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

    async def test_parse_stream_usage_includes_cache_tokens(self):
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
            b"data: {\"usage\":{\"completion_tokens\":3,\"prompt_tokens\":2,",
            b"\"total_tokens\":5,\"prompt_tokens_details\":{\"cached_tokens\":2}}}\n",
            b"data: [DONE]\n",
        ]
        ttft, usage, protocol_error = await parser.parse_stream_usage(FakeContent(chunks), time.perf_counter())

        self.assertIsNotNone(ttft)
        self.assertEqual(usage.output_tokens, 3)
        self.assertEqual(usage.total_tokens, 5)
        self.assertEqual(usage.cached_input_tokens, 2)
        self.assertEqual(usage.cache_inclusive_total_tokens, 5)
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
        self.assertEqual(converted.recognized_params, ["messages", "model", "stream", "temperature"])
        self.assertEqual(converted.unknown_params, [])

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
        self.assertIn("name: \"anthropic-version\"", converted.openapi_yaml)
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

    def test_curl_parser_supports_attached_and_equals_flag_values(self):
        converted = convert_curl_to_openapi(
            curl="""curl --location --compressed --url=https://api.example.com/v1/chat/completions \
  --header='Authorization: Bearer sk-real' \
  --header='Content-Type: application/json' \
  --data-raw='{"model":"gpt-5.5","messages":[{"role":"user","content":"Hello"}]}'""",
            base_url="https://api.wenwen-ai.com",
            title="Curl",
        )

        self.assertEqual(converted.endpoint, "/v1/chat/completions")
        self.assertIn("Authorization: Bearer ${API_KEY}", converted.sanitized_curl)
        self.assertIn('"model": "gpt-5.5"', converted.sanitized_curl)
        self.assertNotIn("sk-real", converted.sanitized_curl)

    def test_curl_parser_supports_short_attached_flag_values(self):
        converted = convert_curl_to_openapi(
            curl="""curl -XPOST https://api.example.com/v1/chat/completions \
  -H'Authorization: Bearer sk-real' \
  -H'X-Request-Source: official-docs' \
  -d'{"model":"gpt-5.5","input":"hello"}'""",
            base_url="https://api.wenwen-ai.com",
            title="Curl",
        )

        self.assertEqual(converted.method, "POST")
        self.assertIn("X-Request-Source: official-docs", converted.sanitized_curl)
        self.assertIn('"input": "hello"', converted.sanitized_curl)
        self.assertNotIn("sk-real", converted.sanitized_curl)

    def test_body_fields_are_all_preserved_without_unknown_classification(self):
        converted = convert_curl_to_openapi(
            curl="""curl https://api.example.com/v1/chat/completions \
  -H 'Authorization: Bearer sk-real' \
  -d '{"model":"gpt-5.5","unsupportedVendorField":true,"Imopat":"enabled"}'""",
            base_url="https://api.wenwen-ai.com",
            title="Curl",
        )

        self.assertEqual(converted.recognized_params, ["Imopat", "model", "unsupportedVendorField"])
        self.assertEqual(converted.unknown_params, [])
        self.assertIn('"unsupportedVendorField": true', converted.sanitized_curl)
        self.assertIn('"Imopat": "enabled"', converted.sanitized_curl)


if __name__ == "__main__":
    unittest.main()
