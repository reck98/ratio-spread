from datetime import date

import pytest

from engine.pnl_engine import PnLEngine
from utils.models import OptionType, Position, Side


def test_buy_position_pnl() -> None:
    engine = PnLEngine()
    pos = Position(
        instrument_key="key1",
        trading_symbol="SYM",
        option_type=OptionType.CE,
        strike=25100,
        expiry=date.today(),
        side=Side.BUY,
        quantity=75,
        entry_price=182.5,
        current_price=191.4,
    )
    pnl = engine.calculate_position_pnl(pos)
    assert pnl == pytest.approx((191.4 - 182.5) * 75)


def test_sell_position_pnl() -> None:
    engine = PnLEngine()
    pos = Position(
        instrument_key="key1",
        trading_symbol="SYM",
        option_type=OptionType.CE,
        strike=25100,
        expiry=date.today(),
        side=Side.SELL,
        quantity=75,
        entry_price=182.5,
        current_price=170.0,
    )
    pnl = engine.calculate_position_pnl(pos)
    assert pnl == pytest.approx((182.5 - 170.0) * 75)


def test_total_mtm() -> None:
    engine = PnLEngine()
    positions = [
        Position(
            instrument_key="k1", trading_symbol="S1", option_type=OptionType.CE,
            strike=25100, expiry=date.today(), side=Side.BUY, quantity=75,
            entry_price=182.5, current_price=191.4,
        ),
        Position(
            instrument_key="k2", trading_symbol="S2", option_type=OptionType.PE,
            strike=25100, expiry=date.today(), side=Side.BUY, quantity=75,
            entry_price=185.0, current_price=170.0,
        ),
    ]
    total = engine.calculate_total_mtm(positions)
    buy_pnl = (191.4 - 182.5) * 75
    put_pnl = (170.0 - 185.0) * 75
    assert total == pytest.approx(buy_pnl + put_pnl)


def test_loss_percentage() -> None:
    engine = PnLEngine()
    loss_pct = engine.calculate_loss_percentage(-5000, 500000)
    assert loss_pct == pytest.approx(1.0)


def test_loss_percentage_zero_margin() -> None:
    engine = PnLEngine()
    loss_pct = engine.calculate_loss_percentage(-5000, 0)
    assert loss_pct == 0.0


def test_loss_percentage_positive_mtm_is_zero() -> None:
    # calculate_loss_percentage only quantifies loss — a profit returns 0.0.
    engine = PnLEngine()
    assert engine.calculate_loss_percentage(5000, 500000) == 0.0


def test_closed_position_uses_zero_exit_price() -> None:
    # A worthless-expiry SELL leg (exit_price == 0.0) must realize full premium,
    # NOT fall back to the last non-zero tick.
    engine = PnLEngine()
    pos = Position(
        instrument_key="k", trading_symbol="S", option_type=OptionType.CE,
        strike=25100, expiry=date.today(), side=Side.SELL, quantity=75,
        entry_price=60.0, current_price=0.4, exit_price=0.0, closed=True,
    )
    # Full premium captured: (entry - 0) * qty, not (entry - 0.4) * qty.
    assert engine.calculate_position_pnl(pos) == pytest.approx(60.0 * 75)


def test_closed_position_without_exit_price_uses_current() -> None:
    engine = PnLEngine()
    pos = Position(
        instrument_key="k", trading_symbol="S", option_type=OptionType.CE,
        strike=25100, expiry=date.today(), side=Side.BUY, quantity=75,
        entry_price=100.0, current_price=120.0, exit_price=None, closed=True,
    )
    assert engine.calculate_position_pnl(pos) == pytest.approx((120.0 - 100.0) * 75)


def test_update_position_prices() -> None:
    engine = PnLEngine()
    pos = Position(
        instrument_key="k1", trading_symbol="S", option_type=OptionType.CE,
        strike=25100, expiry=date.today(), side=Side.BUY, quantity=75,
        entry_price=100.0, current_price=100.0,
    )
    engine.update_position_prices([pos], {"k1": 130.0})
    assert pos.current_price == 130.0
    assert pos.unrealized_pnl == pytest.approx((130.0 - 100.0) * 75)


def test_calculate_metrics_splits_gross_profit_and_loss() -> None:
    engine = PnLEngine()
    positions = [
        Position(
            instrument_key="k1", trading_symbol="S1", option_type=OptionType.CE,
            strike=25100, expiry=date.today(), side=Side.BUY, quantity=75,
            entry_price=100.0, current_price=140.0,  # +3000
        ),
        Position(
            instrument_key="k2", trading_symbol="S2", option_type=OptionType.PE,
            strike=25100, expiry=date.today(), side=Side.BUY, quantity=75,
            entry_price=100.0, current_price=80.0,  # -1500
        ),
    ]
    metrics = engine.calculate_metrics(positions, current_mtm=1500.0)
    assert metrics["gross_profit"] == pytest.approx(3000.0)
    assert metrics["gross_loss"] == pytest.approx(1500.0)
    assert metrics["net_profit"] == pytest.approx(1500.0)
    assert metrics["current_mtm"] == pytest.approx(1500.0)


