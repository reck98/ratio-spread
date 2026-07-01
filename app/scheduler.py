import asyncio
from datetime import datetime, time, timedelta, timezone

from utils.config import AppConfig
from utils.logging import LogManager

LATE_ENTRY_GRACE_SECONDS = 300


class Scheduler:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._entry_time = config.trading.entry_time_obj()
        self._exit_time = config.trading.exit_time_obj()
        self._logger = LogManager.get_logger("scheduler")

    async def wait_for_entry(self) -> bool:
        now = datetime.now(timezone.utc)
        target = datetime.combine(now.date(), self._entry_time, tzinfo=timezone.utc)
        late_cutoff = target + timedelta(seconds=LATE_ENTRY_GRACE_SECONDS)

        if now > late_cutoff:
            self._logger.warning(
                "Current time %s is past entry window (cutoff %s) — skipping today",
                now.strftime("%H:%M:%S"), late_cutoff.strftime("%H:%M:%S"),
            )
            return False

        if now >= target:
            self._logger.info("Within entry window at %s — proceeding", now.strftime("%H:%M:%S"))
            return True

        delay = (target - now).total_seconds()
        self._logger.info("Waiting %.0f seconds until entry at %s", delay, self._entry_time)
        await asyncio.sleep(delay)
        return True

    @property
    def entry_time(self) -> time:
        return self._entry_time

    @property
    def exit_time(self) -> time:
        return self._exit_time
