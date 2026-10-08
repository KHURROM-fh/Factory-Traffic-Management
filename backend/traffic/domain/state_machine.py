"""
Explicit deterministic state machine for factory traffic signal transitions.
Enforces signal safety invariants:
- Conflicting green signals (NS and EW) are impossible.
- Direct phase jumps (e.g. NS_GREEN -> EW_GREEN) are strictly rejected.
- All conflicting transitions must proceed through YELLOW -> ALL_RED -> GREEN.
"""

from enum import Enum
from typing import Dict, List, Optional

from traffic.constants import Direction, SignalColor, TrafficPhase
from traffic.domain.exceptions import InvalidTransitionError, SafetyInvariantViolation


class SignalState(str, Enum):
    """Explicit traffic controller state machine states."""
    NORTH_SOUTH_GREEN = "NORTH_SOUTH_GREEN"
    NORTH_SOUTH_YELLOW = "NORTH_SOUTH_YELLOW"
    ALL_RED = "ALL_RED"
    EAST_WEST_GREEN = "EAST_WEST_GREEN"
    EAST_WEST_YELLOW = "EAST_WEST_YELLOW"

    @property
    def phase(self) -> TrafficPhase:
        if self in (SignalState.NORTH_SOUTH_GREEN, SignalState.NORTH_SOUTH_YELLOW):
            return TrafficPhase.NORTH_SOUTH
        elif self in (SignalState.EAST_WEST_GREEN, SignalState.EAST_WEST_YELLOW):
            return TrafficPhase.EAST_WEST
        return TrafficPhase.ALL_RED

    @property
    def is_green(self) -> bool:
        return self in (SignalState.NORTH_SOUTH_GREEN, SignalState.EAST_WEST_GREEN)

    @property
    def is_yellow(self) -> bool:
        return self in (SignalState.NORTH_SOUTH_YELLOW, SignalState.EAST_WEST_YELLOW)

    @property
    def is_all_red(self) -> bool:
        return self == SignalState.ALL_RED


# Mapping of each state to the exact 4-way desired signal aspects
STATE_SIGNALS_MAP: Dict[SignalState, Dict[Direction, SignalColor]] = {
    SignalState.NORTH_SOUTH_GREEN: {
        Direction.NORTH: SignalColor.GREEN,
        Direction.SOUTH: SignalColor.GREEN,
        Direction.EAST: SignalColor.RED,
        Direction.WEST: SignalColor.RED,
    },
    SignalState.NORTH_SOUTH_YELLOW: {
        Direction.NORTH: SignalColor.YELLOW,
        Direction.SOUTH: SignalColor.YELLOW,
        Direction.EAST: SignalColor.RED,
        Direction.WEST: SignalColor.RED,
    },
    SignalState.ALL_RED: {
        Direction.NORTH: SignalColor.RED,
        Direction.SOUTH: SignalColor.RED,
        Direction.EAST: SignalColor.RED,
        Direction.WEST: SignalColor.RED,
    },
    SignalState.EAST_WEST_GREEN: {
        Direction.NORTH: SignalColor.RED,
        Direction.SOUTH: SignalColor.RED,
        Direction.EAST: SignalColor.GREEN,
        Direction.WEST: SignalColor.GREEN,
    },
    SignalState.EAST_WEST_YELLOW: {
        Direction.NORTH: SignalColor.RED,
        Direction.SOUTH: SignalColor.RED,
        Direction.EAST: SignalColor.YELLOW,
        Direction.WEST: SignalColor.YELLOW,
    },
}

# Strict whitelist of valid single-step transitions
VALID_TRANSITIONS: Dict[SignalState, List[SignalState]] = {
    SignalState.NORTH_SOUTH_GREEN: [
        SignalState.NORTH_SOUTH_YELLOW,
    ],
    SignalState.NORTH_SOUTH_YELLOW: [
        SignalState.ALL_RED,
    ],
    SignalState.ALL_RED: [
        SignalState.NORTH_SOUTH_GREEN,
        SignalState.EAST_WEST_GREEN,
    ],
    SignalState.EAST_WEST_GREEN: [
        SignalState.EAST_WEST_YELLOW,
    ],
    SignalState.EAST_WEST_YELLOW: [
        SignalState.ALL_RED,
    ],
}


def assert_signal_safety(signals: Dict[Direction, SignalColor]) -> None:
    """
    Validates that the provided 4-way signal aspects strictly obey safety invariants:
    1. North/South GREEN and East/West GREEN must NEVER happen simultaneously.
    2. Green and conflicting Yellow must NEVER happen simultaneously.
    3. Conflicting Yellows must NEVER happen simultaneously.
    """
    ns_green = signals.get(Direction.NORTH) == SignalColor.GREEN or signals.get(Direction.SOUTH) == SignalColor.GREEN
    ew_green = signals.get(Direction.EAST) == SignalColor.GREEN or signals.get(Direction.WEST) == SignalColor.GREEN

    if ns_green and ew_green:
        raise SafetyInvariantViolation(
            f"CRITICAL SAFETY BREACH: Conflicting GREEN signals detected simultaneously! "
            f"Signals: {signals}"
        )

    ns_yellow = signals.get(Direction.NORTH) == SignalColor.YELLOW or signals.get(Direction.SOUTH) == SignalColor.YELLOW
    ew_yellow = signals.get(Direction.EAST) == SignalColor.YELLOW or signals.get(Direction.WEST) == SignalColor.YELLOW

    if (ns_green and ew_yellow) or (ew_green and ns_yellow):
        raise SafetyInvariantViolation(
            f"CRITICAL SAFETY BREACH: Simultaneous GREEN and conflicting YELLOW! "
            f"Signals: {signals}"
        )

    if ns_yellow and ew_yellow:
        raise SafetyInvariantViolation(
            f"CRITICAL SAFETY BREACH: Simultaneous conflicting YELLOW signals! "
            f"Signals: {signals}"
        )


class TrafficStateMachine:
    """
    Deterministic state machine managing signal phase transitions.
    Guarantees that transitions proceed strictly through safe intermediate stages:
    GREEN -> YELLOW -> ALL_RED -> GREEN.
    """

    def __init__(self, initial_state: SignalState = SignalState.NORTH_SOUTH_GREEN):
        self._current_state = initial_state
        assert_signal_safety(self.get_signals())

    @property
    def current_state(self) -> SignalState:
        return self._current_state

    def get_signals(self) -> Dict[Direction, SignalColor]:
        """Returns the 4-way signal aspects for the current state."""
        return dict(STATE_SIGNALS_MAP[self._current_state])

    def can_transition_to(self, target_state: SignalState) -> bool:
        """Checks whether a single-step transition to target_state is allowed."""
        if target_state == self._current_state:
            return True
        return target_state in VALID_TRANSITIONS.get(self._current_state, [])

    def transition_to(self, next_state: SignalState) -> SignalState:
        """
        Executes a single-step state transition.
        Raises InvalidTransitionError if the requested transition is not in VALID_TRANSITIONS.
        """
        if next_state == self._current_state:
            return self._current_state

        valid_next_states = VALID_TRANSITIONS.get(self._current_state, [])
        if next_state not in valid_next_states:
            raise InvalidTransitionError(
                f"Invalid transition from {self._current_state.value} to {next_state.value}. "
                f"Valid next states: {[s.value for s in valid_next_states]}."
            )

        new_signals = STATE_SIGNALS_MAP[next_state]
        assert_signal_safety(new_signals)

        self._current_state = next_state
        return self._current_state

    @staticmethod
    def get_safe_transition_sequence(from_state: SignalState, to_state: SignalState) -> List[SignalState]:
        """
        Calculates the complete deterministic list of intermediate states
        required to transition safely from from_state to to_state.
        Example:
        NS_GREEN -> EW_GREEN returns: [NS_YELLOW, ALL_RED, EW_GREEN]
        EW_GREEN -> NS_GREEN returns: [EW_YELLOW, ALL_RED, NS_GREEN]
        """
        if from_state == to_state:
            return []

        # From NS_GREEN to EW_GREEN
        if from_state == SignalState.NORTH_SOUTH_GREEN and to_state == SignalState.EAST_WEST_GREEN:
            return [
                SignalState.NORTH_SOUTH_YELLOW,
                SignalState.ALL_RED,
                SignalState.EAST_WEST_GREEN,
            ]

        # From EW_GREEN to NS_GREEN
        if from_state == SignalState.EAST_WEST_GREEN and to_state == SignalState.NORTH_SOUTH_GREEN:
            return [
                SignalState.EAST_WEST_YELLOW,
                SignalState.ALL_RED,
                SignalState.NORTH_SOUTH_GREEN,
            ]

        # From NS_YELLOW to EW_GREEN
        if from_state == SignalState.NORTH_SOUTH_YELLOW and to_state == SignalState.EAST_WEST_GREEN:
            return [SignalState.ALL_RED, SignalState.EAST_WEST_GREEN]

        # From EW_YELLOW to NS_GREEN
        if from_state == SignalState.EAST_WEST_YELLOW and to_state == SignalState.NORTH_SOUTH_GREEN:
            return [SignalState.ALL_RED, SignalState.NORTH_SOUTH_GREEN]

        # From ALL_RED to either green
        if from_state == SignalState.ALL_RED:
            if to_state in (SignalState.NORTH_SOUTH_GREEN, SignalState.EAST_WEST_GREEN):
                return [to_state]

        # If already in the target phase, no intermediate transitions needed
        if from_state == to_state:
            return []

        raise InvalidTransitionError(
            f"No safe transition sequence known from {from_state.value} to {to_state.value}."
        )
