from utils.logging import LogManager
from utils.models import ExitReason, StrategyContext


class RiskManager:
    def __init__(self, stop_loss_percent: float = 1.0) -> None:
        self._stop_loss_percent = stop_loss_percent
        self._logger = LogManager.get_logger("strategy")

    def check_stop_loss(self, context: StrategyContext) -> bool:
        if context.current_mtm >= 0:
            return False
        if context.margin_used <= 0:
            # No valid margin basis for the stop-loss percentage. Rather than run a
            # losing position with NO downside protection, fail safe: force an exit.
            self._logger.warning(
                "Margin is %.2f (<= 0) with a losing MTM %.2f — cannot size stop-loss, "
                "forcing exit as a safety measure",
                context.margin_used, context.current_mtm,
            )
            return True
        loss_pct = abs(context.current_mtm) / context.margin_used * 100.0
        triggered = loss_pct >= self._stop_loss_percent
        if triggered:
            self._logger.warning(
                "Stop loss triggered: loss=%.2f%% (limit=%.1f%%) MTM=%.2f Margin=%.2f",
                loss_pct, self._stop_loss_percent, context.current_mtm, context.margin_used,
            )
        return triggered

    def should_exit(
        self, context: StrategyContext, current_time_str: str, exit_time_str: str,
    ) -> tuple[bool, ExitReason]:
        if self.check_stop_loss(context):
            return True, ExitReason.STOP_LOSS
        if current_time_str >= exit_time_str:
            self._logger.info("Scheduled exit at %s", current_time_str)
            return True, ExitReason.SCHEDULED_EXIT
        return False, ExitReason.NONE
