import asyncio
from datetime import date, datetime, timezone
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
from state.state_manager import StateManager
from utils.config import AppConfig
from utils.logging import LogManager
from utils.models import (
    ExitReason,
    InstrumentType,
    OptionType,
    Position,
    Side,
    StrategyContext,
    StrategyMetrics,
    StrategyState,
    Tick,
)


class StrategyRunner:
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
        self._config = config
        self._broker = broker
        self._resolver = instrument_resolver
        self._market_cache = market_cache
        self._pnl_engine = pnl_engine
        self._risk_manager = risk_manager
        self._exit_manager = exit_manager
        self._state_manager = state_manager
        self._strategy_run_repo = strategy_run_repo
        self._order_repo = order_repo
        self._position_repo = position_repo
        self._pnl_history_repo = pnl_history_repo
        self._daily_summary_repo = daily_summary_repo
        self._config_snapshot_repo = config_snapshot_repo
        self._logger = LogManager.get_logger("strategy")
        self._context = StrategyContext()
        self._metrics = StrategyMetrics()
        self._running = False

    @property
    def metrics(self) -> StrategyMetrics:
        return self._metrics

    @property
    def context(self) -> StrategyContext:
        return self._context

    async def handle_tick(self, tick: Tick) -> None:
        if self._context.strategy_state != StrategyState.MONITORING:
            return
        self._market_cache.update(tick)
        self._context.last_tick_time = tick.timestamp
        await self._update_mtm()

    async def _update_mtm(self) -> None:
        prices: dict[str, float] = {}
        for pos in self._context.positions:
            ltp = self._market_cache.get_ltp(pos.instrument_key)
            if ltp is not None:
                prices[pos.instrument_key] = ltp

        if not prices:
            return

        self._pnl_engine.update_position_prices(self._context.positions, prices)
        self._context.current_mtm = self._pnl_engine.calculate_total_mtm(self._context.positions)

        self._update_metrics()
        self._state_manager.save(self._context)

    def _update_metrics(self) -> None:
        mtm = self._context.current_mtm
        if mtm > self._metrics.highest_mtm:
            self._metrics.highest_mtm = mtm
        if mtm < self._metrics.lowest_mtm:
            self._metrics.lowest_mtm = mtm
        if mtm > 0:
            self._metrics.max_favorable_excursion = max(self._metrics.max_favorable_excursion, mtm)
        else:
            self._metrics.max_adverse_excursion = min(self._metrics.max_adverse_excursion, mtm)

    async def run_strategy(self, instrument: InstrumentType, trading_date: date,
                           expiry_date: date, entry_lpt: float) -> StrategyContext:
        self._context = StrategyContext(
            strategy_state=StrategyState.WAITING_FOR_ENTRY,
            instrument=instrument,
            trading_date=trading_date,
            expiry_date=expiry_date,
        )
        self._logger.info("Strategy starting: %s expiry=%s", instrument.value, expiry_date)

        self._context.strategy_state = StrategyState.SELECTING_INSTRUMENTS
        atm_strike = await self._resolver.resolve_atm_strike(
            instrument, expiry_date, entry_lpt, self._config.trading.strike_interval,
        )
        self._context.atm_strike = atm_strike

        option_chain = await self._broker.load_option_chain(instrument.value, expiry_date)

        atm_call = await self._resolver.resolve_option(instrument, atm_strike, OptionType.CE, expiry_date)
        atm_put = await self._resolver.resolve_option(instrument, atm_strike, OptionType.PE, expiry_date)

        if not atm_call or not atm_put:
            self._logger.error("Failed to resolve ATM options")
            self._context.strategy_state = StrategyState.COMPLETED
            self._context.exit_reason = ExitReason.FAILED
            return self._context

        atm_call_premium = atm_call.get("premium", atm_call.get("ltp", entry_lpt * 0.01))
        atm_put_premium = atm_put.get("premium", atm_put.get("ltp", entry_lpt * 0.01))
        self._context.atm_call_premium = atm_call_premium
        self._context.atm_put_premium = atm_put_premium

        calls = option_chain.get("calls", [])
        puts = option_chain.get("puts", [])

        sell_call = self._resolver.find_sell_strike(atm_call_premium, calls) if calls else None
        sell_put = self._resolver.find_sell_strike(atm_put_premium, puts) if puts else None

        if not sell_call or not sell_put:
            self._logger.error("Failed to resolve sell strikes")
            self._context.strategy_state = StrategyState.COMPLETED
            self._context.exit_reason = ExitReason.FAILED
            return self._context

        self._context.sell_call_strike = sell_call.get("strike")
        self._context.sell_put_strike = sell_put.get("strike")
        self._context.sell_call_premium = sell_call.get("premium", sell_call.get("ltp", 0))
        self._context.sell_put_premium = sell_put.get("premium", sell_put.get("ltp", 0))

        self._context.strategy_state = StrategyState.BUILDING_POSITION
        entry_time = datetime.now(timezone.utc)
        self._context.entry_time = entry_time

        run_id = self._strategy_run_repo.create(
            trading_date=trading_date,
            instrument=instrument.value,
            expiry_date=expiry_date,
            entry_time=entry_time,
            margin_used=self._broker.estimate_margin(),
            atm_strike=atm_strike,
            sell_call_strike=self._context.sell_call_strike,
            sell_put_strike=self._context.sell_put_strike,
        )
        self._context.run_id = run_id
        self._context.margin_used = self._broker.estimate_margin()

        lots = self._config.trading.buy_lots
        sell_qty = lots * self._config.trading.sell_multiplier

        orders_specs = [
            (atm_call, Side.BUY, lots, atm_call_premium),
            (atm_put, Side.BUY, lots, atm_put_premium),
            (sell_call, Side.SELL, sell_qty, self._context.sell_call_premium),
            (sell_put, Side.SELL, sell_qty, self._context.sell_put_premium),
        ]

        ctx_positions: list[Position] = []
        for spec, side, qty, price in orders_specs:
            inst_key = spec.get("instrument_key", f"{instrument.value}_FAKE")
            sym_spec_strike = spec.get("strike", 0)
            sym = spec.get("trading_symbol", f"{instrument.value}{sym_spec_strike}{spec.get('option_type', 'CE')}")
            strike = spec.get("strike", 0)
            opt_type = spec.get("option_type", "CE")
            order = await self._broker.place_order(
                run_id, inst_key, sym, opt_type, strike, side.value, qty, price,
            )
            self._order_repo.insert(order)

            pos = Position(
                instrument_key=inst_key,
                trading_symbol=sym,
                option_type=opt_type.upper(),
                strike=strike,
                expiry=expiry_date,
                side=Side(side.value),
                quantity=qty,
                entry_price=price,
                current_price=price,
            )
            ctx_positions.append(pos)
            self._position_repo.insert(run_id, pos)

        self._context.positions = ctx_positions
        self._context.current_mtm = 0.0
        self._context.strategy_state = StrategyState.MONITORING

        self._config_snapshot_repo.save(run_id, self._config.model_dump(mode="json"))
        self._state_manager.save(self._context)

        self._logger.info(
            "Position entered: ATM=%d SELL CE=%d SELL PE=%d MTM=%.2f Margin=%.2f",
            atm_strike, self._context.sell_call_strike, self._context.sell_put_strike,
            self._context.current_mtm, self._context.margin_used,
        )
        return self._context

    async def monitoring_loop(self, exit_time_str: str) -> StrategyContext:
        self._running = True
        self._logger.info("Monitoring started")

        while self._running and self._context.strategy_state == StrategyState.MONITORING:
            now = datetime.now(timezone.utc)
            now_str = now.strftime("%H:%M:%S")

            should_exit, reason = self._risk_manager.should_exit(self._context, now_str, exit_time_str)
            if should_exit:
                self._context = await self._exit_manager.exit_all(self._context, reason)
                break

            loss_pct = (
                abs(self._context.current_mtm) / self._context.margin_used * 100.0
                if self._context.margin_used > 0 else 0
            )
            self._pnl_history_repo.insert(
                self._context.run_id or 0, now, self._context.current_mtm, loss_pct,
            )

            await asyncio.sleep(self._config.trading.monitor_interval)

        if self._context.strategy_state == StrategyState.COMPLETED:
            self._finalize_session()

        return self._context

    def _finalize_session(self) -> None:
        summary = self._pnl_engine.calculate_metrics(self._context.positions, self._context.current_mtm)
        sl_hit = self._context.exit_reason == ExitReason.STOP_LOSS
        self._strategy_run_repo.update_exit(
            run_id=self._context.run_id or 0,
            exit_time=self._context.exit_time or datetime.now(timezone.utc),
            exit_reason=self._context.exit_reason.value,
            total_profit=self._context.current_mtm,
            stop_loss_hit=sl_hit,
            max_mtm=self._metrics.highest_mtm,
            min_mtm=self._metrics.lowest_mtm,
        )
        self._daily_summary_repo.upsert(
            trading_date=self._context.trading_date or date.today(),
            instrument=self._context.instrument.value if self._context.instrument else "",
            gross_profit=summary["gross_profit"],
            gross_loss=summary["gross_loss"],
            net_profit=summary["net_profit"],
            max_mtm=self._metrics.highest_mtm,
            min_mtm=self._metrics.lowest_mtm,
            exit_reason=self._context.exit_reason.value,
            margin_used=self._context.margin_used,
        )
        self._state_manager.save(self._context)
        self._logger.info(
            "Session finalized: PnL=%.2f reason=%s",
            self._context.current_mtm, self._context.exit_reason.value,
        )

    def stop(self) -> None:
        self._running = False

    async def recover(self) -> Optional[StrategyContext]:
        saved = self._state_manager.load()
        if saved is None:
            return None

        if saved.strategy_state in (StrategyState.MONITORING, StrategyState.EXITING):
            self._context = saved
            self._logger.info(
                "Recovered state: run_id=%s state=%s mtm=%.2f",
                saved.run_id, saved.strategy_state.value, saved.current_mtm,
            )
            return self._context

        if saved.strategy_state == StrategyState.COMPLETED:
            self._logger.info("Recovered completed state, no action needed")
            self._context = saved
            return self._context

        self._logger.warning("Unrecoverable state: %s", saved.strategy_state.value)
        return None
