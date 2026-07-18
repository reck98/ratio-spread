"""End-to-end paper-session integration test (TODO.md:29).

Drives a whole session — entry -> monitor -> scheduled exit -> finalize — through the
real StrategyRunner, ExitManager, PnLEngine, RiskManager and InstrumentResolver against a
temp SQLite DB. Only the broker's network boundary is stubbed (FakeChainBroker returns a
canned option chain and a fixed margin); order fills, P&L, state transitions and
persistence are all exercised for real. Complements tests/test_exit_flow.py, which covers
only the exit slice.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from broker.instrument_resolver import InstrumentResolver
from broker.paper_broker import PaperBroker
from broker.upstox_broker import UpstoxBroker
from database.repository import (
    ConfigSnapshotRepository,
    DailySummaryRepository,
    OrderRepository,
    PnLHistoryRepository,
    PositionRepository,
    StrategyRunRepository,
)
from database.sqlite_manager import SQLiteManager
from engine.exit_manager import ExitManager
from engine.market_data_cache import MarketDataCache
from engine.pnl_engine import PnLEngine
from engine.risk_manager import RiskManager
from engine.strategy_runner import StrategyRunner
from state.state_manager import StateManager
from utils.config import AppConfig
from utils.models import ExitReason, InstrumentType, Side, StrategyState, Tick

EXPIRY = date(2026, 7, 2)
ENTRY_LTP = 24500.0

# Leg instrument keys, matched between the canned chain and the tick feed below.
CE_ATM = "NSE_FO|CE24500"
PE_ATM = "NSE_FO|PE24500"
CE_SELL = "NSE_FO|CE24700"
PE_SELL = "NSE_FO|PE24300"


def _chain_entry(strike: int, premium: float, opt: str) -> dict[str, Any]:
    return {
        "strike": strike,
        "premium": premium,
        "instrument_key": f"NSE_FO|{opt}{strike}",
        "trading_symbol": f"NIFTY{strike}{opt}",
    }


class FakeChainBroker(PaperBroker):
    """PaperBroker with the two network calls run_strategy makes stubbed offline."""

    async def load_option_chain(self, instrument: str, expiry: date) -> dict[str, list[dict[str, Any]]]:
        return {
            "calls": [
                _chain_entry(24400, 140.0, "CE"),
                _chain_entry(24500, 100.0, "CE"),  # ATM CE
                _chain_entry(24600, 60.0, "CE"),
                _chain_entry(24700, 30.0, "CE"),   # sell CE (premium <= 100/3)
            ],
            "puts": [
                _chain_entry(24300, 30.0, "PE"),   # sell PE (premium <= 100/3)
                _chain_entry(24400, 60.0, "PE"),
                _chain_entry(24500, 100.0, "PE"),  # ATM PE
                _chain_entry(24600, 140.0, "PE"),
            ],
        }

    async def get_margin(self, orders: list[Any]) -> float:
        # A fixed, positive requirement — avoids the estimate_margin() fallback and gives
        # a deterministic stop-loss base. (The un-stubbed live call is what A2b fixed.)
        return 500000.0


def _runner(db: SQLiteManager, cache: MarketDataCache, sm: StateManager) -> StrategyRunner:
    config = AppConfig()
    broker = FakeChainBroker(UpstoxBroker(config))
    pnl = PnLEngine()
    return StrategyRunner(
        config=config, broker=broker, instrument_resolver=InstrumentResolver(broker),
        market_cache=cache, pnl_engine=pnl,
        risk_manager=RiskManager(config.trading.stop_loss_percent),
        exit_manager=ExitManager(broker, pnl, cache, sm, OrderRepository(db), PositionRepository(db)),
        state_manager=sm,
        strategy_run_repo=StrategyRunRepository(db), order_repo=OrderRepository(db),
        position_repo=PositionRepository(db), pnl_history_repo=PnLHistoryRepository(db),
        daily_summary_repo=DailySummaryRepository(db), config_snapshot_repo=ConfigSnapshotRepository(db),
    )


async def _feed(runner: StrategyRunner, cache: MarketDataCache, prices: dict[str, float]) -> None:
    """Simulate a monitoring tick arriving: prime every leg's price, then handle one tick."""
    now = datetime.now(timezone.utc)
    for key, price in prices.items():
        cache.update(Tick(instrument_key=key, ltp=price, timestamp=now))
    await runner.handle_tick(Tick(instrument_key=CE_ATM, ltp=prices[CE_ATM], timestamp=now))


@pytest.mark.asyncio
async def test_full_session_entry_monitor_exit(temp_db: SQLiteManager, tmp_path: Path) -> None:
    cache = MarketDataCache()
    sm = StateManager()
    sm.initialize(str(tmp_path / "state.json"))
    runner = _runner(temp_db, cache, sm)

    # --- 1. Entry -----------------------------------------------------------------
    ctx = await runner.run_strategy(InstrumentType.NIFTY, EXPIRY, EXPIRY, ENTRY_LTP)

    assert ctx.strategy_state == StrategyState.MONITORING
    assert ctx.run_id is not None
    assert ctx.margin_used == 500000.0
    assert ctx.atm_strike == 24500
    assert ctx.sell_call_strike == 24700
    assert ctx.sell_put_strike == 24300

    run_id = ctx.run_id
    buy_ce, buy_pe, sell_ce, sell_pe = ctx.positions
    assert [p.instrument_key for p in ctx.positions] == [CE_ATM, PE_ATM, CE_SELL, PE_SELL]
    assert (buy_ce.side, buy_ce.quantity, buy_ce.entry_price) == (Side.BUY, 65, 100.0)
    assert (buy_pe.side, buy_pe.quantity, buy_pe.entry_price) == (Side.BUY, 65, 100.0)
    assert (sell_ce.side, sell_ce.quantity, sell_ce.entry_price) == (Side.SELL, 195, 30.0)
    assert (sell_pe.side, sell_pe.quantity, sell_pe.entry_price) == (Side.SELL, 195, 30.0)

    # Four entry orders + a config snapshot are persisted.
    assert len(OrderRepository(temp_db).get_by_run(run_id)) == 4
    snap = temp_db.execute(
        "SELECT COUNT(*) AS n FROM configuration_snapshot WHERE strategy_run_id = ?", (run_id,)
    ).fetchone()
    assert snap["n"] == 1

    # --- 2. Monitor ---------------------------------------------------------------
    # Two benign ticks (MTM stays positive, well inside the 1% stop-loss). MTM tracking
    # must seed from the first observed value, not the old 0.0 sentinel.
    await _feed(runner, cache, {CE_ATM: 95.0, PE_ATM: 95.0, CE_SELL: 25.0, PE_SELL: 25.0})
    assert runner.context.current_mtm == pytest.approx(1300.0)  # -325-325+975+975

    await _feed(runner, cache, {CE_ATM: 90.0, PE_ATM: 90.0, CE_SELL: 20.0, PE_SELL: 20.0})
    assert runner.context.current_mtm == pytest.approx(2600.0)  # -650-650+1950+1950
    assert runner.context.strategy_state == StrategyState.MONITORING  # no stop-loss trip
    assert runner.metrics.highest_mtm == pytest.approx(2600.0)
    assert runner.metrics.lowest_mtm == pytest.approx(1300.0)

    # --- 3. Scheduled exit + finalize ---------------------------------------------
    # Expiry settlement: every leg goes worthless. A past exit_time forces the scheduled
    # exit on the loop's first iteration (deterministic, no wall-clock wait).
    for key in (CE_ATM, PE_ATM, CE_SELL, PE_SELL):
        cache.update(Tick(instrument_key=key, ltp=0.0, timestamp=datetime.now(timezone.utc)))

    ctx = await runner.monitoring_loop("00:00:00")

    # --- 4. End state -------------------------------------------------------------
    assert ctx.strategy_state == StrategyState.COMPLETED
    assert ctx.exit_reason == ExitReason.SCHEDULED_EXIT
    assert all(p.closed for p in ctx.positions)
    assert buy_ce.realized_pnl == pytest.approx((0.0 - 100.0) * 65)   # -6500
    assert buy_pe.realized_pnl == pytest.approx((0.0 - 100.0) * 65)   # -6500
    assert sell_ce.realized_pnl == pytest.approx((30.0 - 0.0) * 195)  # +5850
    assert sell_pe.realized_pnl == pytest.approx((30.0 - 0.0) * 195)  # +5850
    assert ctx.current_mtm == pytest.approx(-1300.0)

    # strategy_runs finalized with the realized P&L and no stop-loss.
    run_row = StrategyRunRepository(temp_db).get_by_date(EXPIRY)
    assert run_row is not None
    assert run_row["exit_reason"] == ExitReason.SCHEDULED_EXIT.value
    assert run_row["total_profit"] == pytest.approx(-1300.0)
    assert run_row["stop_loss_hit"] == 0

    # daily_summary carries the instrument (the D3 on-conflict fix) and reason.
    summary = temp_db.execute(
        "SELECT * FROM daily_summary WHERE trading_date = ?", (EXPIRY.isoformat(),)
    ).fetchone()
    assert summary is not None
    assert summary["instrument"] == "NIFTY"
    assert summary["exit_reason"] == ExitReason.SCHEDULED_EXIT.value

    # Four entry + four exit orders, exit IDs uniquely namespaced (B3).
    orders = OrderRepository(temp_db).get_by_run(run_id)
    assert len(orders) == 8
    assert sum(1 for o in orders if str(o["order_id"]).startswith("EXIT_")) == 4
