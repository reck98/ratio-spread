from typing import Optional

from utils.models import StrategyState

# A logger protocol without importing the concrete LogManager type.
_LoggerLike = object


class StrategyStateMachine:
    # Position-holding states (BUILDING_POSITION, ENTERED, MONITORING) must NOT jump
    # straight to COMPLETED — a run holding open legs has to pass through EXITING so
    # the exit/cleanup logic runs. COMPLETED remains reachable from the pre-position
    # states (IDLE/WAITING_FOR_ENTRY/SELECTING_INSTRUMENTS) for failure aborts.
    _VALID_TRANSITIONS: dict[StrategyState, set[StrategyState]] = {
        StrategyState.IDLE: {StrategyState.WAITING_FOR_ENTRY, StrategyState.COMPLETED},
        StrategyState.WAITING_FOR_ENTRY: {StrategyState.SELECTING_INSTRUMENTS, StrategyState.COMPLETED},
        StrategyState.SELECTING_INSTRUMENTS: {StrategyState.BUILDING_POSITION, StrategyState.COMPLETED},
        StrategyState.BUILDING_POSITION: {StrategyState.ENTERED},
        StrategyState.ENTERED: {StrategyState.MONITORING},
        StrategyState.MONITORING: {StrategyState.EXITING},
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

    @classmethod
    def next_state(
        cls, current: StrategyState, target: StrategyState, logger: Optional[_LoggerLike] = None,
    ) -> StrategyState:
        """Return ``target``, warning (never raising) on an unexpected transition.

        A no-op self-transition (``target == current``) is always allowed silently
        (e.g. re-entering EXITING on recovery). Unlike :meth:`transition`, this never
        raises — a bookkeeping mismatch must not crash a live trade — but it surfaces
        the anomaly so it can be investigated.
        """
        if target != current and not cls.can_transition(current, target):
            if logger is not None:
                logger.warning(  # type: ignore[attr-defined]
                    "Unexpected state transition: %s -> %s", current.value, target.value,
                )
        return target
