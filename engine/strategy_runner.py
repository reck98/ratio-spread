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
from engine.strategy_state_machine import StrategyStateMachine
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
        self._finalized = False
        self._metrics_seeded = False

    @property
    def metrics(self) -> StrategyMetrics:
        return self._metrics

    @property
    def context(self) -> StrategyContext:
        return self._context

    def _set_state(self, target: StrategyState) -> None:
        self._context.strategy_state = StrategyStateMachine.next_state(
            self._context.strategy_state, target, self._logger,
        )

    async def handle_tick(self, tick: Tick) -> None:
        if self._context.strategy_state != StrategyState.MONITORING:
            return
        self._market_cache.update(tick)
        self._context.last_tick_time = tick.timestamp
        await self._update_mtm()

        # React to the stop-loss on every price update, not only on the monitor timer —
        # a fast adverse move can blow past the limit between timer wakeups. exit_all
        # runs synchronously, so no interleaving with the monitoring loop can occur.
        if (
            self._context.strategy_state == StrategyState.MONITORING
            and self._risk_manager.check_stop_loss(self._context)
        ):
            self._context = await self._exit_manager.exit_all(
                self._context, ExitReason.STOP_LOSS,
            )
            # The monitoring loop will observe COMPLETED on its next wake and finalize;
            # we don't finalize here to avoid a double finalize.

    async def _update_mtm(self) -> None:
        prices: dict[str, float] = {}
        missing: list[str] = []
        for pos in self._context.positions:
            ltp = self._market_cache.get_ltp(pos.instrument_key)
            if ltp is not None:
                prices[pos.instrument_key] = ltp
            else:
                missing.append(pos.instrument_key)

        if not prices:
            return

        if missing:
            # MTM (a risk-bearing number) is being computed from a mix of fresh and
            # stale leg prices — surface it rather than blending silently.
            self._logger.debug("No fresh LTP for legs %s — using last-known price", missing)

        self._pnl_engine.update_position_prices(self._context.positions, prices)
        self._context.current_mtm = self._pnl_engine.calculate_total_mtm(self._context.positions)

        self._update_metrics()
        self._state_manager.save(self._context)

    def _update_metrics(self) -> None:
        mtm = self._context.current_mtm
        # Seed both extremes from the first observed MTM so an always-losing session
        # doesn't report highest_mtm=0 (a value it never actually held), and so the
        # fragile "lowest == 0.0" sentinel is removed.
        if not self._metrics_seeded:
            self._metrics.highest_mtm = mtm
            self._metrics.lowest_mtm = mtm
            self._metrics_seeded = True
        else:
            self._metrics.highest_mtm = max(self._metrics.highest_mtm, mtm)
            self._metrics.lowest_mtm = min(self._metrics.lowest_mtm, mtm)
        if mtm > 0:
            self._metrics.max_favorable_excursion = max(self._metrics.max_favorable_excursion, mtm)
        elif mtm < 0:
            self._metrics.max_adverse_excursion = min(self._metrics.max_adverse_excursion, mtm)

    async def run_strategy(self, instrument: InstrumentType, trading_date: date,
                           expiry_date: date, entry_lpt: float) -> StrategyContext:
        # Guard against re-entry: if a position is already live (double trigger /
        # re-scheduled run), refuse rather than orphan it and place a second set.
        active_states = (
            StrategyState.SELECTING_INSTRUMENTS,
            StrategyState.BUILDING_POSITION,
            StrategyState.MONITORING,
            StrategyState.EXITING,
        )
        if self._context.strategy_state in active_states:
            self._logger.error(
                "run_strategy called while already active (state=%s) — refusing to re-enter",
                self._context.strategy_state.value,
            )
            return self._context

        self._context = StrategyContext(
            strategy_state=StrategyState.WAITING_FOR_ENTRY,
            instrument=instrument,
            trading_date=trading_date,
            expiry_date=expiry_date,
        )
        self._logger.info("Strategy starting: %s expiry=%s", instrument.value, expiry_date)

        self._set_state(StrategyState.SELECTING_INSTRUMENTS)

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
            self._set_state(StrategyState.COMPLETED)
            self._context.exit_reason = ExitReason.FAILED
            return self._context

        def _find_premium(chain: list[dict[str, Any]], strike: int) -> float:
            return next((c["premium"] for c in chain if c["strike"] == strike), 0.0)

        atm_call_premium = _find_premium(calls, atm_strike)
        atm_put_premium = _find_premium(puts, atm_strike)
        self._context.atm_call_premium = atm_call_premium
        self._context.atm_put_premium = atm_put_premium

        sell_multiplier = self._config.trading.sell_multiplier
        sell_call = self._resolver.find_sell_strike(atm_call_premium, calls, sell_multiplier) if calls else None
        sell_put = self._resolver.find_sell_strike(atm_put_premium, puts, sell_multiplier) if puts else None

        if not sell_call or not sell_put:
            self._logger.error("Failed to resolve sell strikes")
            self._set_state(StrategyState.COMPLETED)
            self._context.exit_reason = ExitReason.FAILED
            return self._context

        self._context.sell_call_strike = sell_call.get("strike")
        self._context.sell_put_strike = sell_put.get("strike")
        self._context.sell_call_premium = sell_call.get("premium", sell_call.get("ltp", 0))
        self._context.sell_put_premium = sell_put.get("premium", sell_put.get("ltp", 0))

        # Stay in SELECTING_INSTRUMENTS through the pre-flight checks below so a failed
        # check can abort straight to COMPLETED. Only move to BUILDING_POSITION once we
        # are actually about to place orders.
        entry_time = datetime.now(timezone.utc)
        self._context.entry_time = entry_time

        lots = self._config.trading.buy_lots
        sell_qty = lots * self._config.trading.sell_multiplier
        lot_size = self._config.trading.lot_sizes.get(instrument.value)
        if not lot_size or lot_size <= 0:
            # A missing/zero lot size would silently scale every P&L, MTM and
            # stop-loss figure wrong (quantity = lots × 1). Refuse to enter.
            self._logger.error(
                "No valid lot_size configured for %s — aborting entry", instrument.value,
            )
            self._set_state(StrategyState.COMPLETED)
            self._context.exit_reason = ExitReason.FAILED
            return self._context

        orders_specs = [
            (atm_call, Side.BUY, lots, atm_call_premium, OptionType.CE.value),
            (atm_put, Side.BUY, lots, atm_put_premium, OptionType.PE.value),
            (sell_call, Side.SELL, sell_qty, self._context.sell_call_premium, OptionType.CE.value),
            (sell_put, Side.SELL, sell_qty, self._context.sell_put_premium, OptionType.PE.value),
        ]

        # Upstox /charges/margin expects the quantity in shares (a multiple of the
        # instrument lot size), not the lot count. Sending raw lots (1, 3) fails with
        # UDAPI1104 "Quantity should be multiple of lot size", so scale by lot_size —
        # mirroring the real Position quantity built below.
        margin_used = await self._broker.get_margin([
            Order(
                order_id="", strategy_run_id=0,
                instrument_key=spec.get("instrument_key", ""),
                trading_symbol=spec.get("trading_symbol", ""),
                option_type=OptionType(opt_type.upper()),
                strike=spec.get("strike", 0),
                side=side,
                quantity=qty * lot_size,
                entry_price=price,
                execution_time=entry_time,
            )
            for spec, side, qty, price, opt_type in orders_specs
        ])
        if margin_used <= 0:
            margin_used = self._broker.estimate_margin()
            self._logger.warning("Margin API returned 0, using fallback: %.2f", margin_used)
        if margin_used <= 0:
            # Without a positive margin the stop-loss cannot be sized — refuse to enter
            # rather than run an unprotected naked-short position.
            self._logger.error("Margin is %.2f (<= 0) — aborting entry", margin_used)
            self._set_state(StrategyState.COMPLETED)
            self._context.exit_reason = ExitReason.FAILED
            return self._context

        # Pre-flight checks passed — we are committing to place orders now.
        self._set_state(StrategyState.BUILDING_POSITION)

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
        self._set_state(StrategyState.ENTERED)
        self._set_state(StrategyState.MONITORING)

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

            # Detect a frozen/dead feed: if ticks stop arriving, MTM (and thus the
            # stop-loss) is silently stuck on the last-known price.
            if self._context.last_tick_time is not None:
                stale_for = (now_utc - self._context.last_tick_time).total_seconds()
                stale_threshold = max(30, self._config.trading.monitor_interval * 10)
                if stale_for > stale_threshold:
                    self._logger.warning(
                        "No market ticks for %.0fs (threshold %ds) — MTM/stop-loss may be stale",
                        stale_for, stale_threshold,
                    )

            should_exit, reason = self._risk_manager.should_exit(self._context, now_local_str, exit_time_str)
            if should_exit:
                self._context = await self._exit_manager.exit_all(self._context, reason)
                break

            pnl_label = "Profit" if self._context.current_mtm >= 0 else "Loss"

            # Signed % of margin, correct for both profit and loss (previously a profit
            # with margin<=0 was mis-recorded as 0%).
            if self._context.margin_used > 0:
                signed_pct = self._context.current_mtm / self._context.margin_used * 100.0
            else:
                signed_pct = 0.0
            pnl_pct = abs(signed_pct)

            self._pnl_history_repo.insert(
                self._context.run_id or 0, now_utc, self._context.current_mtm, signed_pct,
            )

            self._logger.info(
                "PnL: %s MTM=%.2f %s=%.2f%%",
                now_local_str, self._context.current_mtm, pnl_label, pnl_pct,
            )

            await asyncio.sleep(self._config.trading.monitor_interval)

        # If the loop was stopped gracefully (stop()) while still MONITORING, the
        # positions are still open — exit them before finalizing rather than leaving
        # naked shorts running unmonitored.
        if not self._running and self._context.strategy_state == StrategyState.MONITORING:
            self._logger.warning("Monitoring stopped while positions open — exiting all")
            self._context = await self._exit_manager.exit_all(
                self._context, ExitReason.MANUAL_EXIT,
            )

        if self._context.strategy_state == StrategyState.COMPLETED:
            self._finalize_session()

        return self._context

    def _finalize_session(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        if self._context.run_id is None:
            # Entry never created a DB run row (e.g. pre-entry failure) — nothing to
            # finalize. Writing run_id=0 would corrupt reporting for a trade that
            # never entered.
            self._logger.info("No run_id — skipping session finalization (no trade entered)")
            self._state_manager.save(self._context)
            return

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

        today_local = datetime.now(self._local_tz).date()
        if saved.trading_date != today_local:
            has_open = any(not p.closed for p in saved.positions)
            if has_open and saved.strategy_state in (
                StrategyState.MONITORING, StrategyState.EXITING,
            ):
                # A prior day's session left open positions. Complete the exit and
                # finalize before discarding rather than silently forgetting a
                # possibly-still-open position.
                self._logger.warning(
                    "Stale state from %s has open positions (state=%s) — completing exit "
                    "before discarding",
                    saved.trading_date, saved.strategy_state.value,
                )
                self._context = saved
                resume_reason = (
                    saved.exit_reason if saved.exit_reason != ExitReason.NONE
                    else ExitReason.SCHEDULED_EXIT
                )
                self._context = await self._exit_manager.exit_all(self._context, resume_reason)
                self._finalize_session()
                self._state_manager.clear()
                return None

            self._logger.info(
                "Discarding stale state from %s (state=%s) — starting fresh",
                saved.trading_date, saved.strategy_state.value,
            )
            self._state_manager.clear()
            return None

        if saved.strategy_state == StrategyState.MONITORING:
            self._context = saved
            self._logger.info(
                "Recovered state: run_id=%s state=%s mtm=%.2f",
                saved.run_id, saved.strategy_state.value, saved.current_mtm,
            )
            return self._context

        if saved.strategy_state == StrategyState.EXITING:
            # Crashed mid-exit. Complete the exit (exit_all skips already-closed legs)
            # and finalize, rather than resuming a monitoring loop that would never run
            # for a non-MONITORING state.
            self._context = saved
            self._logger.warning(
                "Recovered mid-exit (run_id=%s) — completing exit", saved.run_id,
            )
            resume_reason = (
                saved.exit_reason if saved.exit_reason != ExitReason.NONE
                else ExitReason.SCHEDULED_EXIT
            )
            self._context = await self._exit_manager.exit_all(self._context, resume_reason)
            self._finalize_session()
            return self._context

        if saved.strategy_state == StrategyState.COMPLETED:
            self._logger.info("Recovered completed state, no action needed")
            self._context = saved
            return self._context

        self._logger.warning("Unrecoverable state: %s", saved.strategy_state.value)
        return None
