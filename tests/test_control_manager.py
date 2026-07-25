"""Tests for ControlManager and manual exit integration.

Covers ControlManager in isolation and end-to-end integration with the exit
pipeline, database, and reports.
"""

import json
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
from state.control_manager import ControlCommand, ControlManager
from state.state_manager import StateManager
from utils.config import AppConfig
from utils.logging import LogManager
from utils.models import ExitReason, InstrumentType, OptionType, Position, Side, StrategyContext, StrategyState, Tick

EXPIRY = date(2026, 7, 2)


# ---------------------------------------------------------------------------
# ControlManager unit tests
# ---------------------------------------------------------------------------


def _cm(tmp_path: Path) -> ControlManager:
    return ControlManager(
        control_file_path=str(tmp_path / "control.json"),
        logger=LogManager.get_logger("test"),
    )


def test_default_file_creation_on_init(tmp_path: Path) -> None:
    _cm(tmp_path)
    assert (tmp_path / "control.json").exists()
    with open(tmp_path / "control.json") as f:
        data = json.load(f)
    assert data == {"command": "NONE", "issued_at": None}


def test_get_command_returns_none(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    req = cm.get_command()
    assert req.command == ControlCommand.NONE
    assert req.issued_at is None


def test_get_command_returns_exit(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "EXIT", "issued_at": "2026-07-25T11:18:42+05:30"}, f)
    req = cm.get_command()
    assert req.command == ControlCommand.EXIT
    assert req.issued_at is not None
    assert req.issued_at.isoformat() == "2026-07-25T11:18:42+05:30"


def test_invalid_json_returns_none(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    with open(tmp_path / "control.json", "w") as f:
        f.write("not valid json")
    req = cm.get_command()
    assert req.command == ControlCommand.NONE


def test_missing_file_auto_creates(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    (tmp_path / "control.json").unlink()
    req = cm.get_command()
    assert req.command == ControlCommand.NONE
    assert (tmp_path / "control.json").exists()
    with open(tmp_path / "control.json") as f:
        data = json.load(f)
    assert data == {"command": "NONE", "issued_at": None}


def test_unknown_command_returns_none(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "SOMETHING_RANDOM", "issued_at": None}, f)
    req = cm.get_command()
    assert req.command == ControlCommand.NONE


def test_clear_command_resets_file(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "EXIT", "issued_at": "2026-07-25T11:18:42+05:30"}, f)
    cm.clear_command()
    with open(tmp_path / "control.json") as f:
        data = json.load(f)
    assert data == {"command": "NONE", "issued_at": None}


def test_get_command_returns_exit_without_timestamp(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "EXIT", "issued_at": None}, f)
    req = cm.get_command()
    assert req.command == ControlCommand.EXIT
    assert req.issued_at is None


def test_get_command_handles_invalid_issued_at(tmp_path: Path) -> None:
    cm = _cm(tmp_path)
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "EXIT", "issued_at": "not-a-timestamp"}, f)
    req = cm.get_command()
    assert req.command == ControlCommand.EXIT
    assert req.issued_at is None


# ---------------------------------------------------------------------------
# Integration: ControlManager + ExitManager
# ---------------------------------------------------------------------------


def _seed_run(db: SQLiteManager) -> int:
    return StrategyRunRepository(db).create(
        trading_date=EXPIRY, instrument="NIFTY", expiry_date=EXPIRY,
        entry_time=datetime(2026, 7, 2, 9, 27, tzinfo=timezone.utc), margin_used=650000.0,
    )


def _exit_manager(db: SQLiteManager, cache: MarketDataCache, sm: StateManager) -> ExitManager:
    broker = PaperBroker(UpstoxBroker(AppConfig()))
    return ExitManager(broker, PnLEngine(), cache, sm, OrderRepository(db), PositionRepository(db))


@pytest.mark.asyncio
async def test_manual_exit_triggers_exit_manager_once(
    temp_db: SQLiteManager, tmp_path: Path,
) -> None:
    run_id = _seed_run(temp_db)
    cache = MarketDataCache()
    now = datetime.now(timezone.utc)
    cache.update(Tick(instrument_key="CE_BUY", ltp=90.0, timestamp=now))

    sm = StateManager()
    sm.initialize(str(tmp_path / "state.json"))
    em = _exit_manager(temp_db, cache, sm)

    ctx = StrategyContext(
        strategy_state=StrategyState.MONITORING, run_id=run_id, margin_used=650000.0,
        positions=[
            Position(instrument_key="CE_BUY", trading_symbol="S_BUY", option_type=OptionType.CE,
                     strike=23000, expiry=EXPIRY, side=Side.BUY, quantity=65,
                     entry_price=120.0, current_price=100.0),
        ],
    )

    ctx = await em.exit_all(ctx, ExitReason.MANUAL)
    assert ctx.strategy_state == StrategyState.COMPLETED
    assert ctx.exit_reason == ExitReason.MANUAL
    assert ctx.positions[0].closed is True

    orders = OrderRepository(temp_db).get_by_run(run_id)
    assert len(orders) == 1


def test_exit_reason_stored_as_manual_in_db(temp_db: SQLiteManager) -> None:
    run_id = _seed_run(temp_db)
    repo = StrategyRunRepository(temp_db)
    repo.update_exit(
        run_id=run_id,
        exit_time=datetime.now(timezone.utc),
        exit_reason=ExitReason.MANUAL.value,
        total_profit=-100.0,
        stop_loss_hit=False,
        max_mtm=0.0,
        min_mtm=-200.0,
    )
    run_row = repo.get_by_date(EXPIRY)
    assert run_row is not None
    assert run_row["exit_reason"] == ExitReason.MANUAL.value


@pytest.mark.asyncio
async def test_manual_exit_with_full_session(
    temp_db: SQLiteManager, tmp_path: Path,
) -> None:
    """Full-session integration: entry → monitoring → manual exit → finalize → report."""
    from pathlib import Path as PPath

    from reports.pnl_report import PnLReport
    from reports.session_report import SessionReport
    from reports.statistics import StatisticsReport
    from reports.trade_report import TradeReport

    config = AppConfig()
    broker = PaperBroker(UpstoxBroker(config))
    cache = MarketDataCache()
    pnl = PnLEngine()
    sm = StateManager()
    sm.initialize(str(tmp_path / "state.json"))
    cm = ControlManager(
        control_file_path=str(tmp_path / "control.json"),
        logger=LogManager.get_logger("test"),
    )

    run_repo = StrategyRunRepository(temp_db)
    order_repo = OrderRepository(temp_db)
    pos_repo = PositionRepository(temp_db)
    em = ExitManager(broker, pnl, cache, sm, order_repo, pos_repo)
    runner = StrategyRunner(
        config=config, broker=broker,
        instrument_resolver=InstrumentResolver(broker),
        market_cache=cache, pnl_engine=pnl,
        risk_manager=RiskManager(config.trading.stop_loss_percent),
        exit_manager=em, state_manager=sm, control_manager=cm,
        strategy_run_repo=run_repo, order_repo=order_repo,
        position_repo=pos_repo, pnl_history_repo=PnLHistoryRepository(temp_db),
        daily_summary_repo=DailySummaryRepository(temp_db),
        config_snapshot_repo=ConfigSnapshotRepository(temp_db),
    )

    # Enter a position
    ctx = StrategyContext(
        strategy_state=StrategyState.MONITORING, run_id=_seed_run(temp_db),
        instrument=InstrumentType.NIFTY, trading_date=EXPIRY, margin_used=500000.0,
        positions=[
            Position(instrument_key="CE_BUY", trading_symbol="S_BUY", option_type=OptionType.CE,
                     strike=23000, expiry=EXPIRY, side=Side.BUY, quantity=65,
                     entry_price=120.0, current_price=100.0),
        ],
    )
    runner._context = ctx
    runner._metrics_seeded = True

    # Write EXIT command
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "EXIT", "issued_at": None}, f)

    # Feed a tick so MTM is current and monitoring loop can proceed
    now = datetime.now(timezone.utc)
    cache.update(Tick(instrument_key="CE_BUY", ltp=90.0, timestamp=now))

    # Run the monitoring loop with a future exit time so only manual exit triggers
    ctx = await runner.monitoring_loop("99:99:99")

    assert ctx.strategy_state == StrategyState.COMPLETED
    assert ctx.exit_reason == ExitReason.MANUAL
    assert all(p.closed for p in ctx.positions)

    run_row = run_repo.get_by_date(EXPIRY)
    assert run_row is not None
    assert run_row["exit_reason"] == ExitReason.MANUAL.value

    # Control file reset
    with open(tmp_path / "control.json") as f:
        data = json.load(f)
    assert data["command"] == "NONE"

    # Reports display MANUAL (PnLReport and SessionReport show exit reason)
    report_dir = str(tmp_path / "reports")
    PnLReport(run_repo, DailySummaryRepository(temp_db)).generate(ctx, report_dir)
    SessionReport().generate(ctx, runner.metrics, report_dir)
    TradeReport(order_repo, pos_repo).generate(ctx, report_dir)
    StatisticsReport().generate(ctx, runner.metrics, report_dir)

    pnl_text = (PPath(report_dir) / str(EXPIRY) / "pnl_report.txt").read_text()
    assert "MANUAL" in pnl_text
    session_text = (PPath(report_dir) / str(EXPIRY) / "session_report.txt").read_text()
    assert "MANUAL" in session_text


@pytest.mark.asyncio
async def test_manual_exit_ignored_after_completed(
    temp_db: SQLiteManager, tmp_path: Path,
) -> None:
    """A manual EXIT command left in the file must not re-trigger after exit completes."""
    config = AppConfig()
    broker = PaperBroker(UpstoxBroker(config))
    cache = MarketDataCache()
    pnl = PnLEngine()
    sm = StateManager()
    sm.initialize(str(tmp_path / "state.json"))
    cm = ControlManager(
        control_file_path=str(tmp_path / "control.json"),
        logger=LogManager.get_logger("test"),
    )

    run_repo = StrategyRunRepository(temp_db)
    order_repo = OrderRepository(temp_db)
    pos_repo = PositionRepository(temp_db)
    em = ExitManager(broker, pnl, cache, sm, order_repo, pos_repo)

    runner = StrategyRunner(
        config=config, broker=broker,
        instrument_resolver=InstrumentResolver(broker),
        market_cache=cache, pnl_engine=pnl,
        risk_manager=RiskManager(config.trading.stop_loss_percent),
        exit_manager=em, state_manager=sm, control_manager=cm,
        strategy_run_repo=run_repo, order_repo=order_repo,
        position_repo=pos_repo, pnl_history_repo=PnLHistoryRepository(temp_db),
        daily_summary_repo=DailySummaryRepository(temp_db),
        config_snapshot_repo=ConfigSnapshotRepository(temp_db),
    )

    ctx = StrategyContext(
        strategy_state=StrategyState.COMPLETED, run_id=_seed_run(temp_db),
        instrument=InstrumentType.NIFTY, trading_date=EXPIRY, margin_used=500000.0,
        exit_reason=ExitReason.MANUAL,
        positions=[
            Position(instrument_key="CE_BUY", trading_symbol="S_BUY", option_type=OptionType.CE,
                     strike=23000, expiry=EXPIRY, side=Side.BUY, quantity=65,
                     entry_price=120.0, current_price=90.0, exit_price=90.0,
                     realized_pnl=-1950.0, closed=True),
        ],
    )
    runner._context = ctx
    runner._finalized = True

    # Leave EXIT command in the file — should be ignored since already COMPLETED
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "EXIT", "issued_at": None}, f)

    # monitoring_loop exits immediately when state is not MONITORING
    result = await runner.monitoring_loop("99:99:99")

    assert result.strategy_state == StrategyState.COMPLETED
    assert result.exit_reason == ExitReason.MANUAL
    # No second exit — original orders are intact
    orders = order_repo.get_by_run(ctx.run_id or 0)
    assert len(orders) == 0  # no exit orders placed


@pytest.mark.asyncio
async def test_command_processed_exactly_once(
    temp_db: SQLiteManager, tmp_path: Path,
) -> None:
    """After manual exit, the command is cleared — a second monitoring loop does nothing."""
    config = AppConfig()
    broker = PaperBroker(UpstoxBroker(config))
    cache = MarketDataCache()
    pnl = PnLEngine()
    sm = StateManager()
    sm.initialize(str(tmp_path / "state.json"))
    cm = ControlManager(
        control_file_path=str(tmp_path / "control.json"),
        logger=LogManager.get_logger("test"),
    )

    run_repo = StrategyRunRepository(temp_db)
    order_repo = OrderRepository(temp_db)
    pos_repo = PositionRepository(temp_db)
    em = ExitManager(broker, pnl, cache, sm, order_repo, pos_repo)

    runner = StrategyRunner(
        config=config, broker=broker,
        instrument_resolver=InstrumentResolver(broker),
        market_cache=cache, pnl_engine=pnl,
        risk_manager=RiskManager(config.trading.stop_loss_percent),
        exit_manager=em, state_manager=sm, control_manager=cm,
        strategy_run_repo=run_repo, order_repo=order_repo,
        position_repo=pos_repo, pnl_history_repo=PnLHistoryRepository(temp_db),
        daily_summary_repo=DailySummaryRepository(temp_db),
        config_snapshot_repo=ConfigSnapshotRepository(temp_db),
    )

    run_id = _seed_run(temp_db)
    now = datetime.now(timezone.utc)
    cache.update(Tick(instrument_key="CE_BUY", ltp=90.0, timestamp=now))

    ctx = StrategyContext(
        strategy_state=StrategyState.MONITORING, run_id=run_id,
        instrument=InstrumentType.NIFTY, trading_date=EXPIRY, margin_used=500000.0,
        positions=[
            Position(instrument_key="CE_BUY", trading_symbol="S_BUY", option_type=OptionType.CE,
                     strike=23000, expiry=EXPIRY, side=Side.BUY, quantity=65,
                     entry_price=120.0, current_price=100.0),
        ],
    )
    runner._context = ctx
    runner._metrics_seeded = True

    # Write EXIT
    with open(tmp_path / "control.json", "w") as f:
        json.dump({"command": "EXIT", "issued_at": None}, f)

    # First monitoring loop — should exit with MANUAL
    ctx = await runner.monitoring_loop("99:99:99")
    assert ctx.exit_reason == ExitReason.MANUAL
    assert ctx.strategy_state == StrategyState.COMPLETED

    orders_after_first = order_repo.get_by_run(run_id)
    assert len(orders_after_first) == 1

    # Control file is now NONE — a second monitoring loop with COMPLETED state
    # should do nothing and produce no additional orders
    result = await runner.monitoring_loop("99:99:99")
    assert result.exit_reason == ExitReason.MANUAL
    assert result.strategy_state == StrategyState.COMPLETED

    orders_after_second = order_repo.get_by_run(run_id)
    assert len(orders_after_second) == 1  # still exactly one exit order
