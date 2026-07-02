import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from broker.broker_interface import BrokerInterface
from broker.upstox_broker import UpstoxBroker
from utils.logging import LogManager
from utils.models import BrokerHealth, Order, OrderStatus


class PaperBroker(BrokerInterface):
    def __init__(self, live_broker: UpstoxBroker, margin: float = 650000.0) -> None:
        self._live_broker = live_broker
        self._margin = margin
        self._orders: list[Order] = []
        self._logger = LogManager.get_logger("orders")

    async def connect(self) -> None:
        self._logger.info("Paper broker connected (simulated)")

    async def disconnect(self) -> None:
        self._logger.info("Paper broker disconnected")

    async def authenticate(self) -> None:
        self._logger.info("Paper broker authenticated (simulated)")

    async def load_option_chain(self, instrument: str, expiry: date) -> dict[str, list[dict[str, Any]]]:
        return await self._live_broker.load_option_chain(instrument, expiry)

    async def get_expiry(self, instrument: str) -> Optional[date]:
        return await self._live_broker.get_expiry(instrument)

    async def resolve_instrument(
        self, symbol: str, strike: int, option_type: str, expiry: date,
    ) -> Optional[dict[str, Any]]:
        return await self._live_broker.resolve_instrument(symbol, strike, option_type, expiry)

    async def place_order(self, strategy_run_id: int, instrument_key: str, trading_symbol: str,
                          option_type: str, strike: int, side: str, quantity: int,
                          price: float) -> Order:
        from utils.models import OptionType as OptType
        from utils.models import Side as OrdSide
        order = Order(
            order_id=f"PAPER_{uuid.uuid4().hex[:12].upper()}",
            strategy_run_id=strategy_run_id,
            instrument_key=instrument_key,
            trading_symbol=trading_symbol,
            option_type=OptType(option_type.upper()),
            strike=strike,
            side=OrdSide(side.upper()),
            quantity=quantity,
            entry_price=price,
            current_price=price,
            execution_time=datetime.now(timezone.utc),
            order_status=OrderStatus.FILLED,
        )
        self._orders.append(order)
        self._logger.info(
            "FILLED %s %d %s %s @ %.2f",
            side, quantity, trading_symbol, option_type, price,
        )
        return order

    async def exit_position(self, order: Order) -> Order:
        order.order_status = OrderStatus.FILLED
        order.execution_time = datetime.now(timezone.utc)
        pnl = order.realized_pnl if hasattr(order, "realized_pnl") else 0
        self._logger.info(
            "EXIT %s %s @ %.2f (PnL: %.2f)",
            order.side.value, order.trading_symbol, order.current_price, pnl,
        )
        return order

    async def get_current_ltp(self, instrument_key: str) -> float:
        return 0.0

    async def get_margin(self, orders: list[Order]) -> float:
        try:
            return await self._live_broker.get_margin(orders)
        except Exception as e:
            self._logger.warning("Margin API call failed, using fallback: %s", e)
            return self._margin

    @property
    def health(self) -> BrokerHealth:
        return BrokerHealth.CONNECTED

    def estimate_margin(self) -> float:
        return self._margin
