import subprocess
import sys
import time
from logging import Logger
from pathlib import Path
from typing import Optional

from utils.logging import LogManager
from utils.models import ExitReason, StrategyContext, StrategyState

ALLOWED_EXIT_REASONS = {
    ExitReason.SCHEDULED_EXIT,
    ExitReason.STOP_LOSS,
    ExitReason.MANUAL,
    ExitReason.MANUAL_EXIT,
}


class GitCommitRunner:
    def __init__(
        self,
        script_path: str = "scripts/git-commit.py",
        timeout: float = 60.0,
        logger: Optional[Logger] = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[1]
        path_obj = Path(script_path)
        if path_obj.is_absolute():
            self._script_path = path_obj
        else:
            self._script_path = (project_root / path_obj).resolve()

        self._timeout = timeout
        self._logger = logger or LogManager.get_logger("git_commit")
        self._executed_run_ids: set[int] = set()

    def should_run(self, context: StrategyContext) -> bool:
        if context.strategy_state != StrategyState.COMPLETED:
            return False
        if context.run_id is None:
            return False
        if context.run_id in self._executed_run_ids:
            return False
        return context.exit_reason in ALLOWED_EXIT_REASONS

    def run(self, context: StrategyContext) -> bool:
        """Executes git-commit.py if eligible and not previously executed for this run_id.

        Returns True if executed during this call, or False if skipped.
        Never raises exceptions to caller.
        """
        if not self.should_run(context):
            self._logger.debug(
                "Skipping git-commit script (state=%s, exit_reason=%s, run_id=%s, already_executed=%s)",
                context.strategy_state.value,
                context.exit_reason.value,
                context.run_id,
                context.run_id in self._executed_run_ids if context.run_id is not None else False,
            )
            return False

        assert context.run_id is not None
        self._executed_run_ids.add(context.run_id)

        cmd = [sys.executable, str(self._script_path)]
        self._logger.info("Running post-session git commit: %s", " ".join(cmd))
        start_time = time.perf_counter()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout,
            )
            elapsed = time.perf_counter() - start_time

            if result.stdout:
                self._logger.info("git-commit stdout:\n%s", result.stdout.strip())
            if result.stderr:
                self._logger.warning("git-commit stderr:\n%s", result.stderr.strip())

            if result.returncode == 0:
                self._logger.info("Completed in %.2f seconds (exit code 0)", elapsed)
            else:
                self._logger.error("Completed in %.2f seconds (exit code %d)", elapsed, result.returncode)
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start_time
            self._logger.error(
                "git-commit script timed out after %.2f seconds (limit=%.0fs)",
                elapsed,
                self._timeout,
            )
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            self._logger.error(
                "Failed to execute git-commit script after %.2f seconds: %s",
                elapsed,
                e,
                exc_info=True,
            )

        return True
