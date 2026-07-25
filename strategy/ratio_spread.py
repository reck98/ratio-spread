from datetime import date
from typing import Optional

from engine.strategy_runner import StrategyRunner
from strategy.base_strategy import BaseStrategy
from utils.logging import LogManager
from utils.models import InstrumentType, StrategyContext, StrategyMetrics, Tick


class RatioSpreadStrategy(BaseStrategy):
    def __init__(
        self,
        runner: StrategyRunner,
    ) -> None:
        self._runner = runner
        self._logger = LogManager.get_logger("strategy")

    @property
    def metrics(self) -> StrategyMetrics:
        return self._runner.metrics

    async def should_trade(self, trading_date: date, instrument: InstrumentType) -> bool:
        expiry = await self._runner._resolver.get_weekly_expiry(instrument)
        if expiry is None:
            self._logger.warning("No expiry found for %s", instrument.value)
            return False
        result = expiry == trading_date
        self._logger.info(
            "Expiry check: %s expiry=%s today=%s trade=%s",
            instrument.value, expiry, trading_date, result,
        )
        return result

    async def execute(self, instrument: InstrumentType, trading_date: date,
                      expiry_date: date, ltp: float) -> StrategyContext:
        return await self._runner.run_strategy(instrument, trading_date, expiry_date, ltp)

    async def on_tick(self, tick: Tick) -> None:
        await self._runner.handle_tick(tick)

    async def monitor(self) -> StrategyContext:
        return await self._runner.monitoring_loop(
            self._runner._config.trading.exit_time,
        )

    async def recover(self) -> Optional[StrategyContext]:
        return await self._runner.recover()

    def stop(self) -> None:
        self._runner.stop()
