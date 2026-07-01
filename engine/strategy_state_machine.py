from utils.models import StrategyState


class StrategyStateMachine:
    _VALID_TRANSITIONS: dict[StrategyState, set[StrategyState]] = {
        StrategyState.IDLE: {StrategyState.WAITING_FOR_ENTRY, StrategyState.COMPLETED},
        StrategyState.WAITING_FOR_ENTRY: {StrategyState.SELECTING_INSTRUMENTS, StrategyState.COMPLETED},
        StrategyState.SELECTING_INSTRUMENTS: {StrategyState.BUILDING_POSITION, StrategyState.COMPLETED},
        StrategyState.BUILDING_POSITION: {StrategyState.ENTERED, StrategyState.COMPLETED},
        StrategyState.ENTERED: {StrategyState.MONITORING, StrategyState.COMPLETED},
        StrategyState.MONITORING: {StrategyState.EXITING, StrategyState.COMPLETED},
        StrategyState.EXITING: {StrategyState.COMPLETED},
        StrategyState.COMPLETED: set(),
    }

    @classmethod
    def can_transition(cls, current: StrategyState, target: StrategyState) -> bool:
        return target in cls._VALID_TRANSITIONS.get(current, set())

    @classmethod
    def transition(cls, current: StrategyState, target: StrategyState) -> StrategyState:
        if not cls.can_transition(current, target):
            raise ValueError(f"Invalid state transition: {current.value} -> {target.value}")
        return target
