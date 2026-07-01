import json
from datetime import date, datetime
from typing import Optional

from database.sqlite_manager import SQLiteManager
from utils.models import Order, Position


class StrategyRunRepository:
    def __init__(self, db: SQLiteManager) -> None:
        self.db = db

    def create(
        self,
        trading_date: date,
        instrument: str,
        expiry_date: date,
        entry_time: Optional[datetime] = None,
        margin_used: float = 0.0,
        atm_strike: Optional[int] = None,
        sell_call_strike: Optional[int] = None,
        sell_put_strike: Optional[int] = None,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO strategy_runs
               (trading_date, instrument, expiry_date, entry_time, margin_used,
                atm_strike, sell_call_strike, sell_put_strike)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trading_date.isoformat(), instrument, expiry_date.isoformat(),
             entry_time.isoformat() if entry_time else None,
             margin_used, atm_strike, sell_call_strike, sell_put_strike),
        )
        self.db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_exit(self, run_id: int, exit_time: datetime, exit_reason: str,
                    total_profit: float, stop_loss_hit: bool,
                    max_mtm: float, min_mtm: float) -> None:
        self.db.execute(
            """UPDATE strategy_runs SET exit_time=?, exit_reason=?, total_profit=?,
               stop_loss_hit=?, max_mtm=?, min_mtm=? WHERE id=?""",
            (exit_time.isoformat(), exit_reason, total_profit,
             1 if stop_loss_hit else 0, max_mtm, min_mtm, run_id),
        )
        self.db.commit()

    def get_by_date(self, trading_date: date) -> Optional[dict[str, object]]:
        cur = self.db.execute(
            "SELECT * FROM strategy_runs WHERE trading_date = ?",
            (trading_date.isoformat(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


class OrderRepository:
    def __init__(self, db: SQLiteManager) -> None:
        self.db = db

    def insert(self, order: Order) -> None:
        self.db.execute(
            """INSERT INTO orders
               (order_id, strategy_run_id, instrument_key, trading_symbol,
                option_type, strike, side, quantity, entry_price,
                execution_time, order_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order.order_id, order.strategy_run_id, order.instrument_key,
             order.trading_symbol, order.option_type.value, order.strike,
             order.side.value, order.quantity, order.entry_price,
             order.execution_time.isoformat(), order.order_status.value),
        )
        self.db.commit()

    def get_by_run(self, strategy_run_id: int) -> list[dict[str, object]]:
        cur = self.db.execute(
            "SELECT * FROM orders WHERE strategy_run_id = ?",
            (strategy_run_id,),
        )
        return [dict(row) for row in cur.fetchall()]


class PositionRepository:
    def __init__(self, db: SQLiteManager) -> None:
        self.db = db

    def insert(self, run_id: int, pos: Position) -> None:
        self.db.execute(
            """INSERT INTO positions
               (strategy_run_id, instrument_key, trading_symbol, option_type,
                strike, expiry, side, quantity, entry_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, pos.instrument_key, pos.trading_symbol, pos.option_type.value,
             pos.strike, pos.expiry.isoformat(), pos.side.value,
             pos.quantity, pos.entry_price),
        )
        self.db.commit()

    def close_position(self, position_id: int, exit_price: float, realized_pnl: float) -> None:
        self.db.execute(
            "UPDATE positions SET exit_price=?, realized_pnl=?, closed=1 WHERE id=?",
            (exit_price, realized_pnl, position_id),
        )
        self.db.commit()

    def get_open_by_run(self, strategy_run_id: int) -> list[dict[str, object]]:
        cur = self.db.execute(
            "SELECT * FROM positions WHERE strategy_run_id = ? AND closed = 0",
            (strategy_run_id,),
        )
        return [dict(row) for row in cur.fetchall()]


class PnLHistoryRepository:
    def __init__(self, db: SQLiteManager) -> None:
        self.db = db

    def insert(self, run_id: int, timestamp: datetime, mtm: float, profit_percentage: float) -> None:
        self.db.execute(
            "INSERT INTO pnl_history (strategy_run_id, timestamp, mtm, profit_percentage) VALUES (?, ?, ?, ?)",
            (run_id, timestamp.isoformat(), mtm, profit_percentage),
        )
        self.db.commit()


class DailySummaryRepository:
    def __init__(self, db: SQLiteManager) -> None:
        self.db = db

    def upsert(self, trading_date: date, instrument: str, gross_profit: float,
               gross_loss: float, net_profit: float, max_mtm: float,
               min_mtm: float, exit_reason: str, margin_used: float,
               strategy_version: str = "ratio_spread_v1.0") -> None:
        self.db.execute(
            """INSERT INTO daily_summary
               (trading_date, instrument, gross_profit, gross_loss, net_profit,
                max_mtm, min_mtm, exit_reason, margin_used, strategy_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trading_date) DO UPDATE SET
               gross_profit=excluded.gross_profit, gross_loss=excluded.gross_loss,
               net_profit=excluded.net_profit, max_mtm=excluded.max_mtm,
               min_mtm=excluded.min_mtm, exit_reason=excluded.exit_reason,
               margin_used=excluded.margin_used""",
            (trading_date.isoformat(), instrument, gross_profit, gross_loss,
             net_profit, max_mtm, min_mtm, exit_reason, margin_used, strategy_version),
        )
        self.db.commit()


class ConfigSnapshotRepository:
    def __init__(self, db: SQLiteManager) -> None:
        self.db = db

    def save(self, run_id: int, config: dict[str, object]) -> None:
        self.db.execute(
            "INSERT INTO configuration_snapshot (strategy_run_id, config_json) VALUES (?, ?)",
            (run_id, json.dumps(config)),
        )
        self.db.commit()
