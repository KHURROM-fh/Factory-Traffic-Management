"""
Domain-level exceptions for the Factory Traffic Management System.
These exceptions are pure Python and do not depend on Django or DRF.
"""


class TrafficDomainError(Exception):
    """Base exception for all traffic domain errors."""
    pass


class InvalidTransitionError(TrafficDomainError):
    """Raised when an illegal state machine transition is attempted."""
    pass


class SafetyInvariantViolation(TrafficDomainError):
    """Raised when a core safety invariant (e.g. conflicting greens) is breached."""
    pass


class DuplicateEventError(TrafficDomainError):
    """Raised when an event ID has already been processed (idempotency violation)."""
    pass


class InvalidEventError(TrafficDomainError):
    """Raised when a sensor or system event has invalid or incomplete domain data."""
    pass


class InvalidCommandError(TrafficDomainError):
    """Raised when an invalid command or parameter is submitted."""
    pass


class DegradedModeError(TrafficDomainError):
    """Raised when an action is prohibited because the intersection is in DEGRADED mode."""
    pass
