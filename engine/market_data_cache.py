from threading import Lock
from typing import Optional

from utils.models import Tick


class MarketDataCache:
    _instance: Optional["MarketDataCache"] = None

    def __new__(cls) -> "MarketDataCache":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._data: dict[str, Tick] = {}
            self._lock = Lock()
            self._initialized = True

    def update(self, tick: Tick) -> None:
        with self._lock:
            self._data[tick.instrument_key] = tick

    def get_ltp(self, instrument_key: str) -> Optional[float]:
        with self._lock:
            tick = self._data.get(instrument_key)
            return tick.ltp if tick else None

    def get_tick(self, instrument_key: str) -> Optional[Tick]:
        with self._lock:
            return self._data.get(instrument_key)

    def get_all(self) -> dict[str, Tick]:
        with self._lock:
            return dict(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
