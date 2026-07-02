import asyncio
from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

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
    Order,
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
        self._local_tz = ZoneInfo(config.application.timezone)
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
        if self._metrics.lowest_mtm == 0.0 or mtm < self._metrics.lowest_mtm:
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

        option_chain = await self._broker.load_option_chain(instrument.value, expiry_date)

        calls = option_chain.get("calls", [])
        puts = option_chain.get("puts", [])

        all_strikes = sorted(set(
            c["strike"] for c in calls + puts if c.get("strike")
        ))
        if len(all_strikes) >= 2:
            intervals = [all_strikes[i+1] - all_strikes[i] for i in range(len(all_strikes) - 1)]
            strike_interval = min(intervals)
        else:
            strike_interval = self._config.trading.strike_interval

        atm_strike = await self._resolver.resolve_atm_strike(
            instrument, expiry_date, entry_lpt, strike_interval,
        )
        self._context.atm_strike = atm_strike

        def _find_chain_entry(chain: list[dict[str, Any]], strike: int) -> Optional[dict[str, Any]]:
            return next((c for c in chain if c["strike"] == strike), None)

        atm_call = _find_chain_entry(calls, atm_strike)
        atm_put = _find_chain_entry(puts, atm_strike)

        if not atm_call or not atm_put:
            self._logger.error("Failed to resolve ATM options in chain")
            self._context.strategy_state = StrategyState.COMPLETED
            self._context.exit_reason = ExitReason.FAILED
            return self._context

        def _find_premium(chain: list[dict[str, Any]], strike: int) -> float:
            return next((c["premium"] for c in chain if c["strike"] == strike), 0.0)

        atm_call_premium = _find_premium(calls, atm_strike)
        atm_put_premium = _find_premium(puts, atm_strike)
        self._context.atm_call_premium = atm_call_premium
        self._context.atm_put_premium = atm_put_premium

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

        lots = self._config.trading.buy_lots
        sell_qty = lots * self._config.trading.sell_multiplier
        lot_size = self._config.trading.lot_sizes.get(instrument.value, 1)

        orders_specs = [
            (atm_call, Side.BUY, lots, atm_call_premium, OptionType.CE.value),
            (atm_put, Side.BUY, lots, atm_put_premium, OptionType.PE.value),
            (sell_call, Side.SELL, sell_qty, self._context.sell_call_premium, OptionType.CE.value),
            (sell_put, Side.SELL, sell_qty, self._context.sell_put_premium, OptionType.PE.value),
        ]

        margin_used = await self._broker.get_margin([
            Order(
                order_id="", strategy_run_id=0,
                instrument_key=spec.get("instrument_key", ""),
                trading_symbol=spec.get("trading_symbol", ""),
                option_type=OptionType(opt_type.upper()),
                strike=spec.get("strike", 0),
                side=side,
                quantity=qty,
                entry_price=price,
                execution_time=entry_time,
            )
            for spec, side, qty, price, opt_type in orders_specs
        ])
        if margin_used <= 0:
            margin_used = self._broker.estimate_margin()
            self._logger.warning("Margin API returned 0, using fallback: %.2f", margin_used)

        run_id = self._strategy_run_repo.create(
            trading_date=trading_date,
            instrument=instrument.value,
            expiry_date=expiry_date,
            entry_time=entry_time,
            margin_used=margin_used,
            atm_strike=atm_strike,
            sell_call_strike=self._context.sell_call_strike,
            sell_put_strike=self._context.sell_put_strike,
        )
        self._context.run_id = run_id
        self._context.margin_used = margin_used

        ctx_positions: list[Position] = []
        for spec, side, qty, price, opt_type in orders_specs:
            inst_key = spec.get("instrument_key", f"{instrument.value}_FAKE")
            sym_spec_strike = spec.get("strike", 0)
            sym = spec.get("trading_symbol", f"{instrument.value}{sym_spec_strike}{opt_type}")
            strike = spec.get("strike", 0)
            order = await self._broker.place_order(
                run_id, inst_key, sym, opt_type, strike, side.value, qty, price,
            )
            self._order_repo.insert(order)

            pos = Position(
                instrument_key=inst_key,
                trading_symbol=sym,
                option_type=OptionType(opt_type.upper()),
                strike=strike,
                expiry=expiry_date,
                side=Side(side.value),
                quantity=qty * lot_size,
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
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone(self._local_tz)
            now_local_str = now_local.strftime("%H:%M:%S")

            should_exit, reason = self._risk_manager.should_exit(self._context, now_local_str, exit_time_str)
            if should_exit:
                self._context = await self._exit_manager.exit_all(self._context, reason)
                break

            if self._context.current_mtm >= 0:
                pnl_label = "Profit"
            else:
                pnl_label = "Loss"

            pnl_pct = self._pnl_engine.calculate_loss_percentage(
                self._context.current_mtm, self._context.margin_used,
            )
            if self._context.current_mtm >= 0 and self._context.margin_used > 0:
                pnl_pct = self._context.current_mtm / self._context.margin_used * 100.0
                signed_pct = pnl_pct
            elif self._context.current_mtm < 0:
                signed_pct = -pnl_pct
            else:
                signed_pct = 0.0

            self._pnl_history_repo.insert(
                self._context.run_id or 0, now_utc, self._context.current_mtm, signed_pct,
            )

            self._logger.info(
                "PnL: %s MTM=%.2f %s=%.2f%%",
                now_local_str, self._context.current_mtm, pnl_label, pnl_pct,
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
