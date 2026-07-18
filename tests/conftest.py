"""Shared test fixtures.

The app uses several process-global singletons (ConfigLoader, StateManager,
SQLiteManager). Without resetting them between tests the suite becomes
order-dependent: a config/db/state set up by one test leaks into the next. The
autouse fixture below gives every test a clean slate.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from database.sqlite_manager import SQLiteManager
from engine.market_data_cache import MarketDataCache
from state.state_manager import StateManager
from utils.config import ConfigLoader


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    ConfigLoader.reset()
    StateManager.reset()
    SQLiteManager.reset()
    MarketDataCache().clear()
    yield
    ConfigLoader.reset()
    StateManager.reset()
    SQLiteManager.reset()
    MarketDataCache().clear()


@pytest.fixture()
def temp_db(tmp_path: Path) -> Iterator[SQLiteManager]:
    """A fresh, isolated SQLite database initialized with the real schema."""
    db_path = tmp_path / "test.db"
    db = SQLiteManager()
    db.initialize(str(db_path))
    yield db
    db.close()
