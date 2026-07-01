from datetime import date
from pathlib import Path

from state.state_manager import StateManager
from utils.models import InstrumentType, StrategyContext, StrategyState


def test_save_and_load(tmp_path: Path) -> None:
    state_path = str(tmp_path / "test_state.json")
    sm = StateManager()
    sm.initialize(state_path)

    ctx = StrategyContext(
        strategy_state=StrategyState.MONITORING,
        run_id=1,
        instrument=InstrumentType.NIFTY,
        trading_date=date(2026, 7, 1),
        expiry_date=date(2026, 7, 2),
        margin_used=500000,
        current_mtm=1500,
        atm_strike=25100,
        sell_call_strike=25250,
        sell_put_strike=24950,
    )
    sm.save(ctx)
    loaded = sm.load()
    assert loaded is not None
    assert loaded.strategy_state == StrategyState.MONITORING
    assert loaded.run_id == 1
    assert loaded.instrument == InstrumentType.NIFTY
    assert loaded.margin_used == 500000
    assert loaded.current_mtm == 1500
    assert loaded.atm_strike == 25100


def test_load_nonexistent(tmp_path: Path) -> None:
    sm = StateManager()
    sm.initialize(str(tmp_path / "nonexistent.json"))
    assert sm.load() is None


def test_clear(tmp_path: Path) -> None:
    state_path = str(tmp_path / "test_clear.json")
    sm = StateManager()
    sm.initialize(state_path)
    sm.save(StrategyContext())
    assert sm.load() is not None
    sm.clear()
    assert sm.load() is None
