from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from utils.models import InstrumentType, StrategyContext, Tick


class BaseStrategy(ABC):
    @abstractmethod
    async def should_trade(self, trading_date: date, instrument: InstrumentType) -> bool: ...

    @abstractmethod
    async def execute(self, instrument: InstrumentType, trading_date: date,
                      expiry_date: date, ltp: float) -> StrategyContext: ...

    @abstractmethod
    async def on_tick(self, tick: Tick) -> None: ...

    @abstractmethod
    async def monitor(self) -> StrategyContext: ...

    @abstractmethod
    async def recover(self) -> Optional[StrategyContext]: ...

    @abstractmethod
    def stop(self) -> None: ...
