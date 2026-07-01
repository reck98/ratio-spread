from datetime import date
from typing import Any, Optional

from broker.broker_interface import BrokerInterface
from utils.logging import LogManager
from utils.models import InstrumentType, OptionType


class InstrumentResolver:
    def __init__(self, broker: BrokerInterface) -> None:
        self._broker = broker
        self._logger = LogManager.get_logger("instrument_resolver")

    async def get_weekly_expiry(self, instrument: InstrumentType) -> Optional[date]:
        expiry = await self._broker.get_expiry(instrument.value)
        if expiry:
            self._logger.info("Found expiry for %s: %s", instrument.value, expiry)
        else:
            self._logger.warning("No expiry found for %s", instrument.value)
        return expiry

    def round_to_strike(self, ltp: float, interval: int = 50) -> int:
        return round(ltp / interval) * interval

    async def resolve_atm_strike(self, instrument: InstrumentType, expiry: date,
                                  ltp: float, interval: int = 50) -> int:
        strike = self.round_to_strike(ltp, interval)
        self._logger.info("ATM strike for LTP %.2f: %d", ltp, strike)
        return strike

    async def resolve_option(self, instrument: InstrumentType, strike: int,
                              option_type: OptionType, expiry: date) -> Optional[dict[str, Any]]:
        return await self._broker.resolve_instrument(
            instrument.value, strike, option_type.value, expiry,
        )

    def find_sell_strike(self, buy_premium: float, option_chain: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        target = buy_premium / 3.0
        if buy_premium < 3:
            self._logger.warning("Buy premium %.2f too small for sell strike selection", buy_premium)
            return None

        best: Optional[dict[str, Any]] = None
        for contract in option_chain:
            premium = contract.get("premium", contract.get("ltp", 0))
            if premium is None or premium <= 0:
                continue
            if premium <= target:
                if best is None or premium > best.get("premium", best.get("ltp", 0)):
                    best = contract

        if best:
            self._logger.info(
                "Sell strike selected: strike=%s premium=%s (target=%.2f)",
                best.get("strike"), best.get("premium", best.get("ltp")), target,
            )
        else:
            self._logger.warning("No sell strike found with premium <= %.2f", target)
        return best
