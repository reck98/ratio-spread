from datetime import datetime, timezone

from broker.paper_broker import PaperBroker
from database.repository import OrderRepository, PositionRepository
from engine.market_data_cache import MarketDataCache
from engine.pnl_engine import PnLEngine
from state.state_manager import StateManager
from utils.logging import LogManager
from utils.models import ExitReason, Order, Side, StrategyContext, StrategyState


class ExitManager:
    def __init__(
        self,
        broker: PaperBroker,
        pnl_engine: PnLEngine,
        market_cache: MarketDataCache,
        state_manager: StateManager,
        order_repo: OrderRepository,
        position_repo: PositionRepository,
    ) -> None:
        self._broker = broker
        self._pnl_engine = pnl_engine
        self._market_cache = market_cache
        self._state_manager = state_manager
        self._order_repo = order_repo
        self._position_repo = position_repo
        self._logger = LogManager.get_logger("strategy")

    async def exit_all(self, context: StrategyContext, reason: ExitReason) -> StrategyContext:
        context.strategy_state = StrategyState.EXITING
        context.exit_reason = reason
        exit_time = datetime.now(timezone.utc)

        for pos in context.positions:
            instrument_key = pos.instrument_key
            ltp = self._market_cache.get_ltp(instrument_key)
            if ltp is not None:
                pos.current_price = ltp
                pos.exit_price = ltp
            else:
                pos.exit_price = pos.current_price

            pos.realized_pnl = self._pnl_engine.calculate_position_pnl(pos)
            pos.closed = True

            order = Order(
                order_id=f"EXIT_{pos.instrument_key}",
                strategy_run_id=context.run_id or 0,
                instrument_key=pos.instrument_key,
                trading_symbol=pos.trading_symbol,
                option_type=pos.option_type,
                strike=pos.strike,
                side=Side.SELL if pos.side == Side.BUY else Side.BUY,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=pos.exit_price or 0,
                execution_time=exit_time,
            )
            self._order_repo.insert(order)

        context.current_mtm = self._pnl_engine.calculate_total_mtm(context.positions)
        context.exit_time = exit_time
        context.strategy_state = StrategyState.COMPLETED

        self._state_manager.save(context)
        self._logger.info(
            "Exit completed: reason=%s final_mtm=%.2f",
            reason.value, context.current_mtm,
        )
        return context
