import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from utils.config import AppConfig
from utils.logging import LogManager

LATE_ENTRY_GRACE_SECONDS = 300


class Scheduler:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._tz = ZoneInfo(config.application.timezone)
        self._entry_time = config.trading.entry_time_obj()
        self._exit_time = config.trading.exit_time_obj()
        self._logger = LogManager.get_logger("scheduler")

    async def wait_for_entry(self) -> bool:
        now_local = datetime.now(self._tz)
        target = datetime.combine(now_local.date(), self._entry_time, tzinfo=self._tz)
        late_cutoff = target + timedelta(seconds=LATE_ENTRY_GRACE_SECONDS)

        if now_local > late_cutoff:
            self._logger.warning(
                "Current time %s is past entry window (cutoff %s) — skipping today",
                now_local.strftime("%H:%M:%S"), late_cutoff.strftime("%H:%M:%S"),
            )
            return False

        if now_local >= target:
            self._logger.info("Within entry window at %s — proceeding", now_local.strftime("%H:%M:%S"))
            return True

        delay = (target - now_local).total_seconds()
        self._logger.info("Waiting %.0f seconds until entry at %s (%s)",
                          delay, self._entry_time, self._tz)
        await asyncio.sleep(delay)
        return True

    @property
    def entry_time(self) -> time:
        return self._entry_time

    @property
    def exit_time(self) -> time:
        return self._exit_time
