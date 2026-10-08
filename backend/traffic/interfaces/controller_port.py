"""
Controller Abstraction / Port (Hexagonal Architecture).

Defines the protocol-agnostic interface through which the system communicates
with signal controllers (hardware or simulators).

Decouples the traffic management domain and application layer from concrete
transport mechanisms (REST, MQTT, WebSocket, Modbus, etc.).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from traffic.constants import ControllerStatus, Direction, SignalColor


@dataclass
class ControllerCommandPayload:
    """Outbound command dispatched to a signal controller."""
    command_id: str
    junction_id: str
    direction: Direction
    requested_state: SignalColor
    sent_at: datetime
    timeout_sec: float = 5.0

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "junction_id": self.junction_id,
            "direction": self.direction.value,
            "requested_state": self.requested_state.value,
            "sent_at": self.sent_at.isoformat(),
            "timeout_sec": self.timeout_sec,
        }


@dataclass
class ControllerResponse:
    """Response returned by a controller to a dispatched command."""
    success: bool
    command_id: str
    junction_id: str
    actual_state: Optional[SignalColor] = None
    status: str = "ACK"  # "ACK", "NACK", "FAILED", "OFFLINE", "TIMEOUT"
    message: str = ""
    timestamp: Optional[datetime] = None


@dataclass
class ControllerTelemetry:
    """Telemetry report representing confirmed physical hardware state."""
    junction_id: str
    controller_status: ControllerStatus
    actual_signals: Dict[Direction, SignalColor]
    reported_at: datetime
    round_trip_ms: float = 0.0
    firmware_version: str = "v1.0.0-sim"


class ControllerPort(ABC):
    """
    Abstract Port for Signal Controller communications.
    Implementations may be REST, MQTT, Mock, or Physical Hardware.
    """

    @abstractmethod
    def send_signal_command(self, payload: ControllerCommandPayload) -> ControllerResponse:
        """
        Dispatches a signal change command to the controller.
        May return an immediate acknowledgement (synchronous REST)
        or an accepted acknowledgment for asynchronous transports (MQTT/Webhook).
        """
        pass

    @abstractmethod
    def query_actual_signals(self, junction_id: str) -> ControllerTelemetry:
        """
        Queries the controller for its confirmed physical signal state.
        Never guesses; returns the exact hardware state or flags controller offline.
        """
        pass

    @abstractmethod
    def is_online(self, junction_id: str) -> bool:
        """Checks if the controller hardware is reachable and responsive."""
        pass
