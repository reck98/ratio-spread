"""Integration tests for the exit / stop-loss money path.

These drive the real ExitManager and StrategyRunner (with the PaperBroker and a
temp SQLite DB) rather than mocking, to verify the fixed end-to-end behaviour:
worthless-leg P&L (A1), idempotent exit on retry (B2/B3), and a per-tick
stop-loss trip (C4).
"""

from datetime import date, datetime, timezone
from pathlib import Path

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
from utils.models import (
    ExitReason,
    InstrumentType,
    OptionType,
    Position,
    Side,
    StrategyContext,
    StrategyState,
    Tick,
)

EXPIRY = date(2026, 7, 2)


def _seed_run(db: SQLiteManager) -> int:
    return StrategyRunRepository(db).create(
        trading_date=EXPIRY, instrument="NIFTY", expiry_date=EXPIRY,
        entry_time=datetime(2026, 7, 2, 9, 27, tzinfo=timezone.utc), margin_used=650000.0,
    )


def _exit_manager(db: SQLiteManager, cache: MarketDataCache, sm: StateManager) -> ExitManager:
    broker = PaperBroker(UpstoxBroker(AppConfig()))
    return ExitManager(broker, PnLEngine(), cache, sm, OrderRepository(db), PositionRepository(db))


@pytest.mark.asyncio
async def test_exit_all_realizes_zero_price_and_is_idempotent(
    temp_db: SQLiteManager, tmp_path: Path,
) -> None:
    run_id = _seed_run(temp_db)
    cache = MarketDataCache()
    now = datetime.now(timezone.utc)
    # SELL leg settles worthless (0.0) — the best outcome for a short; BUY leg holds value.
    cache.update(Tick(instrument_key="CE_SELL", ltp=0.0, timestamp=now))
    cache.update(Tick(instrument_key="CE_BUY", ltp=90.0, timestamp=now))

    sm = StateManager()
    sm.initialize(str(tmp_path / "state.json"))
    em = _exit_manager(temp_db, cache, sm)

    ctx = StrategyContext(
        strategy_state=StrategyState.MONITORING, run_id=run_id, margin_used=650000.0,
        positions=[
            Position(instrument_key="CE_SELL", trading_symbol="S_SELL", option_type=OptionType.CE,
                     strike=23200, expiry=EXPIRY, side=Side.SELL, quantity=195,
                     entry_price=60.0, current_price=40.0),
            Position(instrument_key="CE_BUY", trading_symbol="S_BUY", option_type=OptionType.CE,
                     strike=23000, expiry=EXPIRY, side=Side.BUY, quantity=65,
                     entry_price=120.0, current_price=100.0),
        ],
    )

    ctx = await em.exit_all(ctx, ExitReason.SCHEDULED_EXIT)

    assert ctx.strategy_state == StrategyState.COMPLETED
    sell, buy = ctx.positions
    # Worthless SELL leg realizes full premium from exit_price 0.0 (not the last 40 tick).
    assert sell.exit_price == 0.0
    assert sell.realized_pnl == pytest.approx((60.0 - 0.0) * 195)
    assert buy.exit_price == 90.0
    assert buy.realized_pnl == pytest.approx((90.0 - 120.0) * 65)
    assert ctx.current_mtm == pytest.approx((60.0 * 195) + ((90.0 - 120.0) * 65))

    orders_after_first = OrderRepository(temp_db).get_by_run(run_id)
    assert len(orders_after_first) == 2

    # Retry (as recovery would): already-closed legs must be skipped — no double exit,
    # no duplicate order rows / primary-key collision.
    ctx = await em.exit_all(ctx, ExitReason.SCHEDULED_EXIT)
    assert len(OrderRepository(temp_db).get_by_run(run_id)) == 2


def _runner(db: SQLiteManager, cache: MarketDataCache, sm: StateManager) -> StrategyRunner:
    config = AppConfig()
    broker = PaperBroker(UpstoxBroker(config))
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


@pytest.mark.asyncio
async def test_handle_tick_trips_stop_loss(temp_db: SQLiteManager, tmp_path: Path) -> None:
    run_id = _seed_run(temp_db)
    cache = MarketDataCache()
    sm = StateManager()
    sm.initialize(str(tmp_path / "state.json"))
    runner = _runner(temp_db, cache, sm)

    # A live BUY leg: 1% of 650000 margin = 6500. Drop the price enough to exceed it.
    runner._context = StrategyContext(
        strategy_state=StrategyState.MONITORING, run_id=run_id, instrument=InstrumentType.NIFTY,
        trading_date=EXPIRY, margin_used=650000.0,
        positions=[
            Position(instrument_key="CE_BUY", trading_symbol="S_BUY", option_type=OptionType.CE,
                     strike=23000, expiry=EXPIRY, side=Side.BUY, quantity=65,
                     entry_price=120.0, current_price=120.0),
        ],
    )

    # (10 - 120) * 65 = -7150 → 1.1% loss > 1% stop-loss → must exit on this tick.
    await runner.handle_tick(Tick(instrument_key="CE_BUY", ltp=10.0, timestamp=datetime.now(timezone.utc)))

    assert runner.context.strategy_state == StrategyState.COMPLETED
    assert runner.context.exit_reason == ExitReason.STOP_LOSS
    assert runner.context.positions[0].closed is True
