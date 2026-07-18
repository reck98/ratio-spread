from engine.risk_manager import RiskManager
from utils.models import ExitReason, StrategyContext


def test_stop_loss_not_triggered() -> None:
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=500000, current_mtm=-4000)
    assert rm.check_stop_loss(ctx) is False


def test_stop_loss_triggered() -> None:
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=500000, current_mtm=-5000)
    assert rm.check_stop_loss(ctx) is True


def test_stop_loss_just_below_threshold() -> None:
    # Loss of 4999 on 500000 margin = 0.9998% < 1.0% limit → must NOT trigger.
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=500000, current_mtm=-4999)
    assert rm.check_stop_loss(ctx) is False


def test_stop_loss_at_exact_threshold() -> None:
    # Loss of exactly 1.0% must trigger (>= boundary).
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=500000, current_mtm=-5000)
    assert rm.check_stop_loss(ctx) is True


def test_scheduled_exit_takes_precedence() -> None:
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=500000, current_mtm=-3000)
    should_exit, reason = rm.should_exit(ctx, "15:27:00", "15:27:00")
    assert should_exit is True
    assert reason == ExitReason.SCHEDULED_EXIT


def test_stop_loss_overrides_scheduled() -> None:
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=500000, current_mtm=-5000)
    should_exit, reason = rm.should_exit(ctx, "15:27:00", "15:27:00")
    assert should_exit is True
    assert reason == ExitReason.STOP_LOSS


def test_zero_margin_with_loss_forces_exit() -> None:
    # Fail-safe: a losing position with no valid margin basis cannot be left
    # unprotected — check_stop_loss must force an exit.
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=0, current_mtm=-5000)
    assert rm.check_stop_loss(ctx) is True


def test_zero_margin_with_profit_does_not_exit() -> None:
    # A non-losing position is never force-exited even without margin.
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=0, current_mtm=2000)
    assert rm.check_stop_loss(ctx) is False
