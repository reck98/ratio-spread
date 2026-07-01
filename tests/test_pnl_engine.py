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


