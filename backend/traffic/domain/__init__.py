"""
Traffic Control Domain Layer.
Pure Python implementations of the core state machine, queue manager,
scoring scheduler, domain invariants, and central traffic engine.
"""

from traffic.domain.engine import EngineStatusReport, TrafficEngine
from traffic.domain.exceptions import (
    DegradedModeError,
    DuplicateEventError,
    InvalidCommandError,
    InvalidEventError,
    InvalidTransitionError,
    SafetyInvariantViolation,
    TrafficDomainError,
)
from traffic.domain.queue_manager import DomainVehicle, QueueManager
from traffic.domain.scheduler import PhaseScore, TrafficScheduler
from traffic.domain.state_machine import (
    STATE_SIGNALS_MAP,
    VALID_TRANSITIONS,
    SignalState,
    TrafficStateMachine,
    assert_signal_safety,
)

__all__ = [
    "TrafficEngine",
    "EngineStatusReport",
    "TrafficStateMachine",
    "SignalState",
    "STATE_SIGNALS_MAP",
    "VALID_TRANSITIONS",
    "assert_signal_safety",
    "QueueManager",
    "DomainVehicle",
    "TrafficScheduler",
    "PhaseScore",
    "TrafficDomainError",
    "InvalidTransitionError",
    "SafetyInvariantViolation",
    "DuplicateEventError",
    "InvalidEventError",
    "InvalidCommandError",
    "DegradedModeError",
]
