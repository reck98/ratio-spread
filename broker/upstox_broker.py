import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import aiohttp

from broker.broker_interface import BrokerInterface
from utils.config import AppConfig
from utils.logging import LogManager
from utils.models import BrokerHealth, Order, OrderStatus


class UpstoxBroker(BrokerInterface):
    BASE_URL = "https://api.upstox.com/v2"

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._access_token = config.broker.access_token
        self._api_key = config.broker.api_key
        self._api_secret = config.broker.api_secret
        self._health = BrokerHealth.DISCONNECTED
        self._session: aiohttp.ClientSession | None = None
        self._logger = LogManager.get_logger("broker")
        self._instruments_cache: list[dict[str, Any]] = []
        self._option_chain_cache: dict[str, Any] = {}

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._health = BrokerHealth.CONNECTED
        self._logger.info("Upstox broker session created")

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        self._health = BrokerHealth.DISCONNECTED
        self._logger.info("Upstox broker session closed")

    async def authenticate(self) -> None:
        if self._access_token:
            self._health = BrokerHealth.CONNECTED
            self._logger.info("Authenticated with existing access token")
            return
        self._logger.warning("No access token configured — paper mode uses no auth")
        self._health = BrokerHealth.CONNECTED

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._session:
            raise RuntimeError("Broker session not initialized")
        headers = kwargs.pop("headers", {})
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        headers["Accept"] = "application/json"
        url = f"{self.BASE_URL}{path}"
        async with self._session.request(method, url, headers=headers, **kwargs) as resp:
            if resp.status != 200:
                text = await resp.text()
                self._logger.error("Upstox API error: %s %s — %s", method, path, text)
                resp.raise_for_status()
            return await resp.json()

    async def load_instruments(self) -> list[dict[str, Any]]:
        if self._instruments_cache:
            return self._instruments_cache
        try:
            data = await self._request("GET", "/market/instruments/all")
            self._instruments_cache = data.get("data", []) if isinstance(data, dict) else data
            self._logger.info("Loaded %d instruments", len(self._instruments_cache))
        except Exception:
            self._logger.warning("Could not load instruments from Upstox, using option chain fallback")
            self._instruments_cache = []
        return self._instruments_cache

    async def load_option_chain(self, instrument: str, expiry: date) -> dict[str, list[dict[str, Any]]]:
        cache_key = f"{instrument}_{expiry.isoformat()}"
        if cache_key in self._option_chain_cache:
            return self._option_chain_cache[cache_key]  # type: ignore[no-any-return]

        symbol = "NIFTY" if "NIFTY" in instrument.upper() else "SENSEX"
        try:
            data = await self._request(
                "GET",
                f"/market/option-chain/{symbol}",
                params={"expiry": expiry.isoformat()},
            )
            result = data if isinstance(data, dict) else {}
        except Exception as e:
            self._logger.warning("Option chain fetch failed: %s", e)
            result = {}

        calls = result.get("data", {}).get("calls", []) if isinstance(result.get("data"), dict) else []
        puts = result.get("data", {}).get("puts", []) if isinstance(result.get("data"), dict) else []

        organized: dict[str, list[dict[str, Any]]] = {
            "calls": calls if isinstance(calls, list) else [],
            "puts": puts if isinstance(puts, list) else [],
        }
        self._option_chain_cache[cache_key] = organized
        return organized

    async def get_expiry(self, instrument: str) -> Optional[date]:
        symbol = "NIFTY" if "NIFTY" in instrument.upper() else "SENSEX"
        try:
            data = await self._request("GET", f"/market/instruments/option/{symbol}")
            instruments = data if isinstance(data, list) else data.get("data", [])
            if isinstance(instruments, list):
                expiries: set[date] = set()
                today = date.today()
                for inst in instruments:
                    expiry_str = inst.get("expiry")
                    if expiry_str:
                        try:
                            exp = date.fromisoformat(expiry_str)
                            if exp >= today:
                                expiries.add(exp)
                        except (ValueError, TypeError):
                            continue
                if expiries:
                    return min(expiries)
        except Exception as e:
            self._logger.warning("Could not fetch expiry: %s", e)
        return None

    async def resolve_instrument(
        self, symbol: str, strike: int, option_type: str, expiry: date,
    ) -> Optional[dict[str, Any]]:
        instruments = await self.load_instruments()
        for inst in instruments:
            if (inst.get("symbol", "").upper() == symbol.upper()
                    and inst.get("strike") == strike
                    and inst.get("option_type", "").upper() == option_type.upper()):
                exp_str = inst.get("expiry", "")
                try:
                    if exp_str and date.fromisoformat(exp_str) == expiry:
                        return inst
                except (ValueError, TypeError):
                    continue
        return {
            "instrument_key": f"NSE_FO|{symbol}{strike}{option_type}",
            "trading_symbol": f"{symbol}{expiry.strftime('%y%m%d')}{strike}{option_type}",
            "strike": strike,
            "option_type": option_type,
            "expiry": expiry.isoformat(),
        }

    async def place_order(self, strategy_run_id: int, instrument_key: str, trading_symbol: str,
                          option_type: str, strike: int, side: str, quantity: int,
                          price: float) -> Order:
        from utils.models import OptionType as OptType
        from utils.models import Side as OrdSide
        order_id = f"PAPER_{uuid.uuid4().hex[:12].upper()}"
        order = Order(
            order_id=order_id,
            strategy_run_id=strategy_run_id,
            instrument_key=instrument_key,
            trading_symbol=trading_symbol,
            option_type=OptType(option_type.upper()),
            strike=strike,
            side=OrdSide(side.upper()),
            quantity=quantity,
            entry_price=price,
            execution_time=datetime.now(timezone.utc),
            order_status=OrderStatus.FILLED,
        )
        self._logger.info(
            "Paper order %s: %s %d %s %s @ %.2f",
            order_id, side, quantity, trading_symbol, option_type, price,
        )
        return order

    async def exit_position(self, order: Order) -> Order:
        order.order_status = OrderStatus.FILLED
        order.execution_time = datetime.now(timezone.utc)
        self._logger.info(
            "Paper exit %s: %s %s @ %.2f",
            order.order_id, order.side.value, order.trading_symbol, order.current_price,
        )
        return order

    async def get_current_ltp(self, instrument_key: str) -> float:
        return 0.0

    async def get_margin(self, orders: list[Order]) -> float:
        return 0.0

    @property
    def health(self) -> BrokerHealth:
        return self._health
