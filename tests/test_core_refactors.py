from __future__ import annotations

import unittest

from backend.app.core.task_status import (
    TaskStatus,
    can_transition_task_status,
    is_active_status,
    is_terminal_status,
    stopped_final_status,
)
from loadtest.config import LoadTestConfig
from loadtest.models import RequestResult
from loadtest.summary import MetricsAccumulator, MetricsSummaryBuilder


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


if __name__ == "__main__":
    unittest.main()
