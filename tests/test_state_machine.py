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


def test_position_holding_states_cannot_jump_to_completed() -> None:
    # A run holding open legs must pass through EXITING — it cannot be marked
    # COMPLETED directly from a position-holding state.
    for state in (
        StrategyState.BUILDING_POSITION,
        StrategyState.ENTERED,
        StrategyState.MONITORING,
    ):
        assert not StrategyStateMachine.can_transition(state, StrategyState.COMPLETED)


def test_next_state_never_raises_and_warns_on_invalid() -> None:
    # next_state returns the target even for an invalid transition (never crashes a
    # live trade), unlike transition() which raises.
    assert (
        StrategyStateMachine.next_state(StrategyState.IDLE, StrategyState.MONITORING)
        == StrategyState.MONITORING
    )
    # A no-op self-transition is always allowed.
    assert (
        StrategyStateMachine.next_state(StrategyState.EXITING, StrategyState.EXITING)
        == StrategyState.EXITING
    )
