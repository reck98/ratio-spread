from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Optional

from utils.models import BrokerHealth, Order


class BrokerInterface(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def authenticate(self) -> None: ...

    @abstractmethod
    async def load_option_chain(self, instrument: str, expiry: date) -> dict[str, list[dict[str, Any]]]: ...

    @abstractmethod
    async def get_expiry(self, instrument: str) -> Optional[date]: ...

    @abstractmethod
    async def resolve_instrument(
        self, symbol: str, strike: int, option_type: str, expiry: date,
    ) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    async def place_order(self, strategy_run_id: int, instrument_key: str, trading_symbol: str,
                          option_type: str, strike: int, side: str, quantity: int,
                          price: float) -> Order: ...

    @abstractmethod
    async def exit_position(self, order: Order) -> Order: ...

    @abstractmethod
    async def get_current_ltp(self, instrument_key: str) -> float: ...

    @abstractmethod
    async def get_margin(self, orders: list[Order]) -> float: ...

    @property
    @abstractmethod
    def health(self) -> BrokerHealth: ...
