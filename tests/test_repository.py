from datetime import date, datetime, timezone

from database.repository import (
    ConfigSnapshotRepository,
    DailySummaryRepository,
    OrderRepository,
    PnLHistoryRepository,
    PositionRepository,
    StrategyRunRepository,
)
from database.sqlite_manager import SQLiteManager
from utils.models import OptionType, Order, Position, Side


def _make_run(db: SQLiteManager, trading_date: date = date(2026, 7, 2)) -> int:
    repo = StrategyRunRepository(db)
    return repo.create(
        trading_date=trading_date,
        instrument="NIFTY",
        expiry_date=trading_date,
        entry_time=datetime(2026, 7, 2, 9, 27, tzinfo=timezone.utc),
        margin_used=650000.0,
        atm_strike=23000,
        sell_call_strike=23200,
        sell_put_strike=22800,
    )


def test_strategy_run_create_and_get_by_date(temp_db: SQLiteManager) -> None:
    run_id = _make_run(temp_db)
    assert run_id > 0
    row = StrategyRunRepository(temp_db).get_by_date(date(2026, 7, 2))
    assert row is not None
    assert row["instrument"] == "NIFTY"
    assert row["margin_used"] == 650000.0


def test_get_by_date_returns_latest_run(temp_db: SQLiteManager) -> None:
    # Two runs for the same date (crash-restart / double-start) → get_by_date must
    # return the most recent, not an arbitrary row.
    first = _make_run(temp_db)
    second = _make_run(temp_db)
    assert second > first
    row = StrategyRunRepository(temp_db).get_by_date(date(2026, 7, 2))
    assert row is not None
    assert row["id"] == second


def test_update_exit(temp_db: SQLiteManager) -> None:
    run_id = _make_run(temp_db)
    StrategyRunRepository(temp_db).update_exit(
        run_id=run_id,
        exit_time=datetime(2026, 7, 2, 15, 27, tzinfo=timezone.utc),
        exit_reason="STOP_LOSS",
        total_profit=-6500.0,
        stop_loss_hit=True,
        max_mtm=1000.0,
        min_mtm=-6500.0,
    )
    row = StrategyRunRepository(temp_db).get_by_date(date(2026, 7, 2))
    assert row is not None
    assert row["exit_reason"] == "STOP_LOSS"
    assert row["stop_loss_hit"] == 1
    assert row["total_profit"] == -6500.0


def test_order_insert_and_get_by_run(temp_db: SQLiteManager) -> None:
    run_id = _make_run(temp_db)
    order = Order(
        order_id="PAPER_ABC123",
        strategy_run_id=run_id,
        instrument_key="NSE_FO|1234",
        trading_symbol="NIFTY23000CE",
        option_type=OptionType.CE,
        strike=23000,
        side=Side.BUY,
        quantity=65,
        entry_price=120.5,
        execution_time=datetime(2026, 7, 2, 9, 27, tzinfo=timezone.utc),
    )
    OrderRepository(temp_db).insert(order)
    rows = OrderRepository(temp_db).get_by_run(run_id)
    assert len(rows) == 1
    assert rows[0]["order_id"] == "PAPER_ABC123"
    assert rows[0]["side"] == "BUY"


def test_position_insert_close_and_open_query(temp_db: SQLiteManager) -> None:
    run_id = _make_run(temp_db)
    pos = Position(
        instrument_key="NSE_FO|1234",
        trading_symbol="NIFTY23000CE",
        option_type=OptionType.CE,
        strike=23000,
        expiry=date(2026, 7, 2),
        side=Side.BUY,
        quantity=65,
        entry_price=120.5,
    )
    pos_repo = PositionRepository(temp_db)
    pos_repo.insert(run_id, pos)
    open_before = pos_repo.get_open_by_run(run_id)
    assert len(open_before) == 1
    position_id = int(open_before[0]["id"])  # type: ignore[call-overload]

    pos_repo.close_position(position_id, exit_price=0.0, realized_pnl=7832.5)
    open_after = pos_repo.get_open_by_run(run_id)
    assert open_after == []


def test_pnl_history_insert(temp_db: SQLiteManager) -> None:
    run_id = _make_run(temp_db)
    PnLHistoryRepository(temp_db).insert(
        run_id, datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc), -1500.0, -0.23,
    )
    cur = temp_db.execute("SELECT * FROM pnl_history WHERE strategy_run_id = ?", (run_id,))
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["mtm"] == -1500.0


def test_daily_summary_upsert_updates_instrument_on_conflict(temp_db: SQLiteManager) -> None:
    repo = DailySummaryRepository(temp_db)
    trading_date = date(2026, 7, 2)
    repo.upsert(trading_date, "NIFTY", 0.0, 0.0, 0.0, 0.0, 0.0, "SCHEDULED_EXIT", 650000.0)
    # Re-run for the same date with a different instrument — the conflict update must
    # refresh instrument (previously it was left stale).
    repo.upsert(trading_date, "SENSEX", 100.0, 50.0, 50.0, 200.0, -50.0, "STOP_LOSS", 700000.0)

    cur = temp_db.execute("SELECT * FROM daily_summary WHERE trading_date = ?", (trading_date.isoformat(),))
    rows = cur.fetchall()
    assert len(rows) == 1  # UNIQUE(trading_date) — still a single row
    assert rows[0]["instrument"] == "SENSEX"
    assert rows[0]["net_profit"] == 50.0
    assert rows[0]["exit_reason"] == "STOP_LOSS"


def test_config_snapshot_save(temp_db: SQLiteManager) -> None:
    run_id = _make_run(temp_db)
    ConfigSnapshotRepository(temp_db).save(run_id, {"trading": {"buy_lots": 1}})
    cur = temp_db.execute(
        "SELECT config_json FROM configuration_snapshot WHERE strategy_run_id = ?", (run_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert "buy_lots" in row["config_json"]
