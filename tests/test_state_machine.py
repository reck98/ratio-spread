import pytest

from engine.strategy_state_machine import StrategyStateMachine
from utils.models import StrategyState


def test_valid_transitions() -> None:
    transitions = [
        (StrategyState.IDLE, StrategyState.WAITING_FOR_ENTRY),
        (StrategyState.WAITING_FOR_ENTRY, StrategyState.SELECTING_INSTRUMENTS),
        (StrategyState.SELECTING_INSTRUMENTS, StrategyState.BUILDING_POSITION),
        (StrategyState.BUILDING_POSITION, StrategyState.ENTERED),
        (StrategyState.ENTERED, StrategyState.MONITORING),
        (StrategyState.MONITORING, StrategyState.EXITING),
        (StrategyState.EXITING, StrategyState.COMPLETED),
    ]
    for current, target in transitions:
        assert StrategyStateMachine.can_transition(current, target)
        result = StrategyStateMachine.transition(current, target)
        assert result == target


def test_invalid_skip() -> None:
    assert not StrategyStateMachine.can_transition(StrategyState.IDLE, StrategyState.MONITORING)
    with pytest.raises(ValueError):
        StrategyStateMachine.transition(StrategyState.IDLE, StrategyState.MONITORING)


def test_completed_no_outgoing() -> None:
    for state in StrategyState:
        if state != StrategyState.COMPLETED:
            assert not StrategyStateMachine.can_transition(StrategyState.COMPLETED, state)


def test_idle_to_completed() -> None:
    assert StrategyStateMachine.can_transition(StrategyState.IDLE, StrategyState.COMPLETED)
