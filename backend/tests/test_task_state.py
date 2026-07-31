"""任务状态机测试：全转移矩阵 + 守卫（hermetic，无 DB）。"""
from __future__ import annotations

import pytest

from app.models import TaskStatus
from app.services.task_state import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    TaskStateError,
    assert_transition,
    can_transition,
)

LEGAL_TRANSITIONS = {
    (TaskStatus.QUEUED, TaskStatus.PROCESSING),
    (TaskStatus.QUEUED, TaskStatus.CANCELLED),
    (TaskStatus.PROCESSING, TaskStatus.SUCCEEDED),
    (TaskStatus.PROCESSING, TaskStatus.FAILED),
    (TaskStatus.PROCESSING, TaskStatus.CANCELLED),
}

ALL_STATUSES = list(TaskStatus)


@pytest.mark.parametrize("current", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
def test_transition_matrix(current: TaskStatus, target: TaskStatus):
    """每个状态对的合法性都与定义一致（含非法转移拒绝）。"""
    expected = (current, target) in LEGAL_TRANSITIONS
    assert can_transition(current, target, progress=100) is expected


def test_legal_transitions_do_not_raise():
    for current, target in LEGAL_TRANSITIONS:
        assert_transition(current, target, progress=100)


def test_succeeded_requires_progress_100():
    assert can_transition(TaskStatus.PROCESSING, TaskStatus.SUCCEEDED, progress=100) is True
    assert can_transition(TaskStatus.PROCESSING, TaskStatus.SUCCEEDED, progress=99) is False
    assert can_transition(TaskStatus.PROCESSING, TaskStatus.SUCCEEDED, progress=None) is False


def test_illegal_transition_raises_task_state_error():
    with pytest.raises(TaskStateError) as excinfo:
        assert_transition(TaskStatus.QUEUED, TaskStatus.SUCCEEDED)
    assert excinfo.value.code == "invalid_state_transition"
    assert excinfo.value.status_code == 409
    assert "queued" in excinfo.value.message and "succeeded" in excinfo.value.message


def test_terminal_states_have_no_outgoing_transitions():
    for terminal in TERMINAL_STATUSES:
        assert terminal not in ALLOWED_TRANSITIONS
        for target in ALL_STATUSES:
            assert can_transition(terminal, target, progress=100) is False