"""checkpoint 建表这一步的受控执行行为。

它是部署步骤，失败必须让部署停下来，而不是让应用带病启动。
"""

from unittest.mock import MagicMock, patch

import pytest
from tenacity import RetryError, stop_after_attempt, wait_fixed

from app import checkpoint_pre_start
from app.agent.checkpointer import CheckpointNotConfiguredError
from app.checkpoint_pre_start import init, main


def test_init_builds_the_checkpoint_tables() -> None:
    with patch.object(checkpoint_pre_start, "run_setup") as run_setup:
        init()

    run_setup.assert_called_once_with()


def test_main_reports_before_and_after() -> None:
    with patch.object(checkpoint_pre_start, "run_setup") as run_setup:
        main()

    run_setup.assert_called_once_with()


def test_a_missing_key_stops_the_deployment() -> None:
    """没有加密密钥就不该建表，更不该悄悄跳过——部署必须停在这里。"""
    broken = MagicMock(
        side_effect=CheckpointNotConfiguredError("CHECKPOINT_ENCRYPTION_KEY 未配置")
    )
    once = init.retry_with(stop=stop_after_attempt(1))

    with patch.object(checkpoint_pre_start, "run_setup", broken):
        # 重试耗尽后 tenacity 抛 RetryError，部署照样停下来。
        with pytest.raises(RetryError) as raised:
            once()

    assert isinstance(
        raised.value.last_attempt.exception(), CheckpointNotConfiguredError
    )


def test_a_transient_failure_is_retried() -> None:
    """数据库还没起来时允许重试。"""
    flaky = MagicMock(side_effect=[RuntimeError("db not ready"), None])
    twice = init.retry_with(stop=stop_after_attempt(2), wait=wait_fixed(0))

    with patch.object(checkpoint_pre_start, "run_setup", flaky):
        twice()

    assert flaky.call_count == 2
