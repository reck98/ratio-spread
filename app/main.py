import asyncio
import sys
from datetime import date
from logging import Logger
from typing import Optional

from app.scheduler import Scheduler
from app.shutdown import ShutdownManager
from app.startup import ApplicationComponents, Startup
from utils.logging import LogManager
from utils.models import InstrumentType, StrategyContext, StrategyState, Tick


class TradingApp:
    def __init__(self) -> None:
        self._components: Optional[ApplicationComponents] = None
        self._scheduler: Optional[Scheduler] = None
        self._logger: Optional[Logger] = None
        self._instrument: Optional[InstrumentType] = None
        self._expiry_date: Optional[date] = None
        self._ws_task: Optional[asyncio.Task[None]] = None

    async def run(self) -> None:
        try:
            self._components = await Startup.initialize()
            self._logger = LogManager.get_logger("app")
            self._scheduler = Scheduler(self._components.config)

            recovered = await self._try_recovery()
            if recovered:
                self._logger.info("Resumed from crash recovery (state=%s)", recovered.strategy_state.value)
                if recovered.strategy_state == StrategyState.MONITORING:
                    await self._resume_monitoring(recovered)
                elif recovered.strategy_state == StrategyState.COMPLETED:
                    # recover() already completed/finalized any mid-exit — still emit
                    # the session reports so the run isn't left without output.
                    await self._generate_reports(recovered)
                else:
                    self._logger.warning(
                        "Recovered in unmanaged state %s — no positions to monitor",
                        recovered.strategy_state.value,
                    )
                return

            if not await self._resolve_expiry():
                self._logger.info("No expiry today for NIFTY or SENSEX — no trade")
                return

            assert self._instrument is not None and self._expiry_date is not None

            self._logger.info(
                "Trading %s (expiry: %s)", self._instrument.value, self._expiry_date,
            )

            if not await self._scheduler.wait_for_entry():
                self._logger.error("Entry window passed — aborting today's trade")
                return

            ltp = await self._get_ltp()
            if ltp <= 0:
                self._logger.error("Cannot get LTP, aborting")
                return

            context = await self._components.strategy.execute(
                self._instrument, date.today(), self._expiry_date, ltp,
            )

            if context.strategy_state != StrategyState.MONITORING:
                self._logger.error("Strategy failed to enter — state=%s", context.strategy_state.value)
                return

            await self._start_websocket(context)
            final_context = await self._components.strategy.monitor()
            await self._generate_reports(final_context)

        except Exception as e:
            logger = LogManager.get_logger("error")
            logger.exception("Fatal application error: %s", e)
            raise
        finally:
            await self._cancel_ws_task()
            if self._components:
                await ShutdownManager.shutdown(self._components)

    async def _resolve_expiry(self) -> bool:
        config = self._components.config  # type: ignore[union-attr]
        today = date.today()
        instruments_to_check: list[InstrumentType] = []
        if config.symbols.nifty.enabled:
            instruments_to_check.append(InstrumentType.NIFTY)
        if config.symbols.sensex.enabled:
            instruments_to_check.append(InstrumentType.SENSEX)

        for instrument in instruments_to_check:
            expiry = await self._components.instrument_resolver.get_weekly_expiry(instrument)  # type: ignore[union-attr]
            if expiry == today:
                self._instrument = instrument
                self._expiry_date = expiry
                self._logger.info("Today is %s expiry — trading", instrument.value)  # type: ignore[union-attr]
                return True
            self._logger.info(  # type: ignore[union-attr]
                "%s expiry=%s != today=%s — skipping", instrument.value, expiry, today,
            )
        return False

    async def _try_recovery(self) -> Optional[StrategyContext]:
        recovered = await self._components.strategy.recover()  # type: ignore[union-attr]
        if recovered and recovered.instrument:
            self._instrument = recovered.instrument
        return recovered

    async def _resume_monitoring(self, context: StrategyContext) -> None:
        await self._start_websocket(context)
        positions = context.positions
        if positions:
            instrument_keys = [p.instrument_key for p in positions]
            await self._components.websocket_manager.subscribe(instrument_keys)  # type: ignore[union-attr]
        final_context = await self._components.strategy.monitor()  # type: ignore[union-attr]
        await self._generate_reports(final_context)

    async def _start_websocket(self, context: StrategyContext) -> None:
        ws = self._components.websocket_manager  # type: ignore[union-attr]
        async def tick_handler(tick: Tick) -> None:
            await self._components.strategy.on_tick(tick)  # type: ignore[union-attr]
        ws.set_tick_handler(tick_handler)

        try:
            await ws.connect()
        except Exception as e:
            self._logger.error("WebSocket connection failed: %s", e)  # type: ignore[union-attr]
            return

        instrument_keys = [p.instrument_key for p in context.positions]
        if instrument_keys:
            await ws.subscribe(instrument_keys)

        # Keep a reference so the task isn't garbage-collected mid-run, and surface
        # any exception it raises instead of silently swallowing it.
        self._ws_task = asyncio.create_task(ws.listen())
        self._ws_task.add_done_callback(self._on_ws_task_done)

    def _on_ws_task_done(self, task: "asyncio.Task[None]") -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            LogManager.get_logger("websocket").error(
                "WebSocket listen task exited with error: %s", exc, exc_info=exc,
            )

    async def _cancel_ws_task(self) -> None:
        if self._ws_task is not None and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except (asyncio.CancelledError, Exception):
                pass
        self._ws_task = None

    async def _get_ltp(self) -> float:
        assert self._instrument is not None
        assert self._components is not None
        broker = self._components.upstox_broker
        instrument_key = broker.INSTRUMENT_KEYS.get(self._instrument.value, self._instrument.value)
        ltp = await broker.get_current_ltp(instrument_key)
        if ltp > 0:
            self._logger.info("Current LTP for %s: %.2f", self._instrument.value, ltp)  # type: ignore[union-attr]
        return ltp

    async def _generate_reports(self, context: StrategyContext) -> None:
        report_dir = self._components.config.reports.directory  # type: ignore[union-attr]
        metrics = self._components.strategy.metrics  # type: ignore[union-attr]
        self._components.pnl_report.generate(context, report_dir)  # type: ignore[union-attr]
        self._components.trade_report.generate(context, report_dir)  # type: ignore[union-attr]
        self._components.session_report.generate(context, metrics, report_dir)  # type: ignore[union-attr]
        self._components.statistics_report.generate(context, metrics, report_dir)  # type: ignore[union-attr]
        self._logger.info("All reports generated")  # type: ignore[union-attr]


def main() -> None:
    app = TradingApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
