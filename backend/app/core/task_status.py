from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


ACTIVE_TASK_STATUSES = {
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
    TaskStatus.STOPPING.value,
}

TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
    TaskStatus.INTERRUPTED.value,
}

TASK_STATUS_TRANSITIONS = {
    TaskStatus.QUEUED.value: {
        TaskStatus.RUNNING.value,
        TaskStatus.STOPPING.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.FAILED.value,
        TaskStatus.INTERRUPTED.value,
    },
    TaskStatus.RUNNING.value: {
        TaskStatus.STOPPING.value,
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.INTERRUPTED.value,
    },
    TaskStatus.STOPPING.value: {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.INTERRUPTED.value,
    },
    TaskStatus.COMPLETED.value: set(),
    TaskStatus.FAILED.value: set(),
    TaskStatus.CANCELLED.value: set(),
    TaskStatus.INTERRUPTED.value: set(),
}


def normalize_task_status(status: str | TaskStatus) -> str:
    value = status.value if isinstance(status, TaskStatus) else str(status)
    if value not in TASK_STATUS_TRANSITIONS:
        raise ValueError(f"Unknown task status: {value}")
    return value


def is_active_status(status: str | TaskStatus) -> bool:
    return normalize_task_status(status) in ACTIVE_TASK_STATUSES


def is_terminal_status(status: str | TaskStatus) -> bool:
    return normalize_task_status(status) in TERMINAL_TASK_STATUSES


def can_transition_task_status(current: str | TaskStatus, next_status: str | TaskStatus) -> bool:
    current_value = normalize_task_status(current)
    next_value = normalize_task_status(next_status)
    return current_value == next_value or next_value in TASK_STATUS_TRANSITIONS[current_value]


def stopped_final_status(stop_requested: bool, computed_status: str | TaskStatus) -> str:
    if stop_requested:
        return TaskStatus.CANCELLED.value
    return normalize_task_status(computed_status)
