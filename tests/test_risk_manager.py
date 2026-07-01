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


def test_stop_loss_at_exact_threshold() -> None:
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


def test_zero_margin() -> None:
    rm = RiskManager(stop_loss_percent=1.0)
    ctx = StrategyContext(margin_used=0, current_mtm=-5000)
    assert rm.check_stop_loss(ctx) is False
