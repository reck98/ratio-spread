import json
import shutil
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from utils.models import StrategyContext


class StateManager:
    _instance: Optional["StateManager"] = None
    _lock: Lock = Lock()

    def __new__(cls) -> "StateManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._state_file: Path | None = None
            self._initialized = False

    def initialize(self, state_file_path: str) -> None:
        file_path = Path(state_file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_file = file_path
        self._initialized = True

    def save(self, context: StrategyContext) -> None:
        if not self._initialized or not self._state_file:
            return

        data = self._serialize_context(context)
        tmp_path = self._state_file.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
        shutil.move(str(tmp_path), str(self._state_file))

    def load(self) -> Optional[StrategyContext]:
        if not self._initialized or not self._state_file:
            return None
        if not self._state_file.exists():
            return None

        with open(self._state_file, "r") as f:
            data = json.load(f)
        return self._deserialize_context(data)

    def clear(self) -> None:
        if self._state_file and self._state_file.exists():
            self._state_file.unlink(missing_ok=True)

    def _serialize_context(self, context: StrategyContext) -> dict[str, Any]:
        return {
            "strategy_state": context.strategy_state.value,
            "run_id": context.run_id,
            "instrument": context.instrument.value if context.instrument else None,
            "trading_date": str(context.trading_date) if context.trading_date else None,
            "expiry_date": str(context.expiry_date) if context.expiry_date else None,
            "entry_time": context.entry_time.isoformat() if context.entry_time else None,
            "exit_time": context.exit_time.isoformat() if context.exit_time else None,
            "margin_used": context.margin_used,
            "current_mtm": context.current_mtm,
            "stop_loss_triggered": context.stop_loss_triggered,
            "exit_reason": context.exit_reason.value,
            "last_tick_time": context.last_tick_time.isoformat() if context.last_tick_time else None,
            "atm_strike": context.atm_strike,
            "atm_call_premium": context.atm_call_premium,
            "atm_put_premium": context.atm_put_premium,
            "sell_call_strike": context.sell_call_strike,
            "sell_put_strike": context.sell_put_strike,
            "sell_call_premium": context.sell_call_premium,
            "sell_put_premium": context.sell_put_premium,
            "positions": [
                {
                    "instrument_key": p.instrument_key,
                    "trading_symbol": p.trading_symbol,
                    "option_type": p.option_type.value,
                    "strike": p.strike,
                    "expiry": str(p.expiry),
                    "side": p.side.value,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "exit_price": p.exit_price,
                    "realized_pnl": p.realized_pnl,
                    "unrealized_pnl": p.unrealized_pnl,
                    "closed": p.closed,
                }
                for p in context.positions
            ],
        }

    def _deserialize_context(self, data: dict[str, Any]) -> StrategyContext:
        from datetime import date, datetime

        from utils.models import ExitReason, InstrumentType, OptionType, Position, Side, StrategyState

        positions = []
        for p in data.get("positions", []):
            positions.append(
                Position(
                    instrument_key=p["instrument_key"],
                    trading_symbol=p["trading_symbol"],
                    option_type=OptionType(p["option_type"]),
                    strike=p["strike"],
                    expiry=date.fromisoformat(p["expiry"]),
                    side=Side(p["side"]),
                    quantity=p["quantity"],
                    entry_price=p["entry_price"],
                    current_price=p.get("current_price", 0.0),
                    exit_price=p.get("exit_price"),
                    realized_pnl=p.get("realized_pnl", 0.0),
                    unrealized_pnl=p.get("unrealized_pnl", 0.0),
                    closed=p.get("closed", False),
                )
            )

        return StrategyContext(
            strategy_state=StrategyState(data["strategy_state"]),
            run_id=data.get("run_id"),
            instrument=InstrumentType(data["instrument"]) if data.get("instrument") else None,
            trading_date=date.fromisoformat(data["trading_date"]) if data.get("trading_date") else None,
            expiry_date=date.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None,
            entry_time=datetime.fromisoformat(data["entry_time"]) if data.get("entry_time") else None,
            exit_time=datetime.fromisoformat(data["exit_time"]) if data.get("exit_time") else None,
            margin_used=data.get("margin_used", 0.0),
            current_mtm=data.get("current_mtm", 0.0),
            stop_loss_triggered=data.get("stop_loss_triggered", False),
            exit_reason=ExitReason(data.get("exit_reason", "NONE")),
            last_tick_time=datetime.fromisoformat(data["last_tick_time"]) if data.get("last_tick_time") else None,
            atm_strike=data.get("atm_strike"),
            atm_call_premium=data.get("atm_call_premium", 0.0),
            atm_put_premium=data.get("atm_put_premium", 0.0),
            sell_call_strike=data.get("sell_call_strike"),
            sell_put_strike=data.get("sell_put_strike"),
            sell_call_premium=data.get("sell_call_premium", 0.0),
            sell_put_premium=data.get("sell_put_premium", 0.0),
            positions=positions,
        )
