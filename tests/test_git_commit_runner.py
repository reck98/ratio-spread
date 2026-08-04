import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import TradingApp
from engine.git_commit_runner import GitCommitRunner
from utils.config import AppConfig
from utils.models import ExitReason, StrategyContext, StrategyState


def test_git_commit_runner_should_run_eligible() -> None:
    runner = GitCommitRunner()

    for reason in (
        ExitReason.SCHEDULED_EXIT,
        ExitReason.STOP_LOSS,
        ExitReason.MANUAL,
        ExitReason.MANUAL_EXIT,
    ):
        ctx = StrategyContext(
            strategy_state=StrategyState.COMPLETED,
            run_id=1,
            exit_reason=reason,
        )
        assert runner.should_run(ctx) is True


def test_git_commit_runner_should_run_ineligible() -> None:
    runner = GitCommitRunner()

    # Ineligible states or missing run_id or failed exit_reason
    ctx_not_completed = StrategyContext(
        strategy_state=StrategyState.MONITORING,
        run_id=1,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )
    ctx_no_run_id = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=None,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )
    ctx_failed = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=1,
        exit_reason=ExitReason.FAILED,
    )
    ctx_none = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=1,
        exit_reason=ExitReason.NONE,
    )

    assert runner.should_run(ctx_not_completed) is False
    assert runner.should_run(ctx_no_run_id) is False
    assert runner.should_run(ctx_failed) is False
    assert runner.should_run(ctx_none) is False


@patch("subprocess.run")
def test_scheduled_exit_executed_once(mock_subprocess: MagicMock) -> None:
    mock_subprocess.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
    runner = GitCommitRunner()
    ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=10,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )

    executed = runner.run(ctx)

    assert executed is True
    assert mock_subprocess.call_count == 1
    # Verify sys.executable and absolute path to scripts/git-commit.py
    cmd = mock_subprocess.call_args[0][0]
    assert cmd[0] == sys.executable
    assert Path(cmd[1]).is_absolute()
    assert Path(cmd[1]).name == "git-commit.py"


@patch("subprocess.run")
def test_manual_exit_executed_once(mock_subprocess: MagicMock) -> None:
    mock_subprocess.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
    runner = GitCommitRunner()

    # Test both MANUAL and MANUAL_EXIT with distinct run_ids
    for run_id, reason in enumerate([ExitReason.MANUAL, ExitReason.MANUAL_EXIT], start=20):
        mock_subprocess.reset_mock()
        ctx = StrategyContext(
            strategy_state=StrategyState.COMPLETED,
            run_id=run_id,
            exit_reason=reason,
        )
        executed = runner.run(ctx)
        assert executed is True
        assert mock_subprocess.call_count == 1


@patch("subprocess.run")
def test_stop_loss_exit_executed_once(mock_subprocess: MagicMock) -> None:
    mock_subprocess.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
    runner = GitCommitRunner()
    ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=30,
        exit_reason=ExitReason.STOP_LOSS,
    )

    executed = runner.run(ctx)

    assert executed is True
    assert mock_subprocess.call_count == 1


@patch("subprocess.run")
def test_idempotency_guard_prevents_duplicate_runs(mock_subprocess: MagicMock) -> None:
    mock_subprocess.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
    runner = GitCommitRunner()
    ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=40,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )

    first_run = runner.run(ctx)
    second_run = runner.run(ctx)

    assert first_run is True
    assert second_run is False
    assert mock_subprocess.call_count == 1


@patch("subprocess.run")
def test_timeout_handling_logs_error_and_succeeds(mock_subprocess: MagicMock) -> None:
    mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="git-commit.py", timeout=60.0)
    runner = GitCommitRunner(timeout=60.0)
    ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=50,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )

    executed = runner.run(ctx)

    assert executed is True
    assert mock_subprocess.call_count == 1


@pytest.mark.asyncio
async def test_crash_recovery_resumes_monitoring_executes_once() -> None:
    app = TradingApp()
    real_git_runner = GitCommitRunner()
    app._components = MagicMock()
    app._components.config = AppConfig()
    app._components.git_commit_runner = real_git_runner
    app._logger = MagicMock()

    recovered_ctx = StrategyContext(
        strategy_state=StrategyState.MONITORING,
        run_id=100,
        exit_reason=ExitReason.NONE,
    )
    final_ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=100,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )

    app._components.strategy.monitor = AsyncMock(return_value=final_ctx)

    with (
        patch("app.main.Startup.initialize", return_value=app._components),
        patch.object(app, "_try_recovery", new_callable=AsyncMock, return_value=recovered_ctx),
        patch.object(app, "_start_websocket", new_callable=AsyncMock),
        patch.object(app, "_generate_reports", new_callable=AsyncMock),
        patch("subprocess.run") as mock_subprocess,
    ):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="Success", stderr="")

        await app.run()

        assert mock_subprocess.call_count == 1

        # Attempt duplicate execution for the same recovered context
        dup_executed = real_git_runner.run(final_ctx)
        assert dup_executed is False
        assert mock_subprocess.call_count == 1


@pytest.mark.asyncio
async def test_no_expiry_day_script_not_executed() -> None:
    app = TradingApp()
    app._components = MagicMock()
    app._components.config = AppConfig()
    app._logger = MagicMock()
    app._scheduler = MagicMock()

    with (
        patch("app.main.Startup.initialize", return_value=app._components),
        patch.object(app, "_try_recovery", new_callable=AsyncMock, return_value=None),
        patch.object(app, "_resolve_expiry", new_callable=AsyncMock, return_value=False),
    ):

        await app.run()

    app._components.git_commit_runner.run.assert_not_called()


@pytest.mark.asyncio
async def test_missed_entry_day_script_not_executed() -> None:
    app = TradingApp()
    app._components = MagicMock()
    app._components.config = AppConfig()
    app._logger = MagicMock()
    app._scheduler = MagicMock()
    app._scheduler.wait_for_entry = AsyncMock(return_value=False)
    app._instrument = MagicMock()
    app._expiry_date = date.today()

    with (
        patch("app.main.Startup.initialize", return_value=app._components),
        patch("app.main.Scheduler", return_value=app._scheduler),
        patch.object(app, "_try_recovery", new_callable=AsyncMock, return_value=None),
        patch.object(app, "_resolve_expiry", new_callable=AsyncMock, return_value=True),
    ):

        await app.run()

    app._components.git_commit_runner.run.assert_not_called()


@patch("subprocess.run")
def test_script_raises_exception_session_completes(mock_subprocess: MagicMock) -> None:
    mock_subprocess.side_effect = OSError("Subprocess execution error")
    runner = GitCommitRunner()
    ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=60,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )

    # Should not raise exception
    executed = runner.run(ctx)
    assert executed is True


@patch("subprocess.run")
def test_non_zero_return_code_logged_session_succeeds(mock_subprocess: MagicMock) -> None:
    mock_subprocess.return_value = MagicMock(returncode=1, stdout="", stderr="Git push failed")
    runner = GitCommitRunner()
    ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED,
        run_id=70,
        exit_reason=ExitReason.SCHEDULED_EXIT,
    )

    # Should log error and return True without raising exception
    executed = runner.run(ctx)
    assert executed is True
