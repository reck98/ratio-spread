from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class InstrumentType(str, Enum):
    NIFTY = "NIFTY"
    SENSEX = "SENSEX"


class StrategyState(str, Enum):
    IDLE = "IDLE"
    WAITING_FOR_ENTRY = "WAITING_FOR_ENTRY"
    SELECTING_INSTRUMENTS = "SELECTING_INSTRUMENTS"
    BUILDING_POSITION = "BUILDING_POSITION"
    ENTERED = "ENTERED"
    MONITORING = "MONITORING"
    EXITING = "EXITING"
    COMPLETED = "COMPLETED"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    SCHEDULED_EXIT = "SCHEDULED_EXIT"
    MANUAL_EXIT = "MANUAL_EXIT"
    MANUAL = "MANUAL"
    FAILED = "FAILED"
    NONE = "NONE"


class BrokerHealth(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class Tick(BaseModel):
    instrument_key: str
    ltp: float
    timestamp: datetime


class Order(BaseModel):
    order_id: str
    strategy_run_id: int
    instrument_key: str
    trading_symbol: str
    option_type: OptionType
    strike: int
    side: Side
    quantity: int
    entry_price: float
    current_price: float = 0.0
    execution_time: datetime
    order_status: OrderStatus = OrderStatus.FILLED


class Position(BaseModel):
    id: Optional[int] = None
    instrument_key: str
    trading_symbol: str
    option_type: OptionType
    strike: int
    expiry: date
    side: Side
    quantity: int
    entry_price: float
    current_price: float = 0.0
    exit_price: Optional[float] = None
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    closed: bool = False


class StrategyContext(BaseModel):
    strategy_state: StrategyState = StrategyState.IDLE
    run_id: Optional[int] = None
    instrument: Optional[InstrumentType] = None
    trading_date: Optional[date] = None
    expiry_date: Optional[date] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    margin_used: float = 0.0
    current_mtm: float = 0.0
    stop_loss_triggered: bool = False
    exit_reason: ExitReason = ExitReason.NONE
    last_tick_time: Optional[datetime] = None

    atm_strike: Optional[int] = None
    atm_call_premium: float = 0.0
    atm_put_premium: float = 0.0
    sell_call_strike: Optional[int] = None
    sell_put_strike: Optional[int] = None
    sell_call_premium: float = 0.0
    sell_put_premium: float = 0.0

    positions: list[Position] = Field(default_factory=list)


class PnLSnapshot(BaseModel):
    timestamp: datetime
    mtm: float
    profit_percentage: float


class StrategyMetrics(BaseModel):
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0
    time_in_profit_seconds: int = 0
    time_in_loss_seconds: int = 0
    highest_mtm: float = 0.0
    lowest_mtm: float = 0.0
