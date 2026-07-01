from datetime import date
from typing import Optional

from broker.instrument_resolver import InstrumentResolver
from broker.paper_broker import PaperBroker
from database.repository import (
    ConfigSnapshotRepository,
    DailySummaryRepository,
    OrderRepository,
    PnLHistoryRepository,
    PositionRepository,
    StrategyRunRepository,
)
from engine.exit_manager import ExitManager
from engine.market_data_cache import MarketDataCache
from engine.pnl_engine import PnLEngine
from engine.risk_manager import RiskManager
from engine.strategy_runner import StrategyRunner
from state.state_manager import StateManager
from strategy.base_strategy import BaseStrategy
from utils.config import AppConfig
from utils.logging import LogManager
from utils.models import InstrumentType, StrategyContext, Tick


class RatioSpreadStrategy(BaseStrategy):
    def __init__(
        self,
        config: AppConfig,
        broker: PaperBroker,
        instrument_resolver: InstrumentResolver,
        market_cache: MarketDataCache,
        pnl_engine: PnLEngine,
        risk_manager: RiskManager,
        exit_manager: ExitManager,
        state_manager: StateManager,
        strategy_run_repo: StrategyRunRepository,
        order_repo: OrderRepository,
        position_repo: PositionRepository,
        pnl_history_repo: PnLHistoryRepository,
        daily_summary_repo: DailySummaryRepository,
        config_snapshot_repo: ConfigSnapshotRepository,
    ) -> None:
        self._runner = StrategyRunner(
            config=config,
            broker=broker,
            instrument_resolver=instrument_resolver,
            market_cache=market_cache,
            pnl_engine=pnl_engine,
            risk_manager=risk_manager,
            exit_manager=exit_manager,
            state_manager=state_manager,
            strategy_run_repo=strategy_run_repo,
            order_repo=order_repo,
            position_repo=position_repo,
            pnl_history_repo=pnl_history_repo,
            daily_summary_repo=daily_summary_repo,
            config_snapshot_repo=config_snapshot_repo,
        )
        self._logger = LogManager.get_logger("strategy")

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
