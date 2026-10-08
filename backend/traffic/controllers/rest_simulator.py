"""
REST Controller Simulator.
Implements ControllerPort to simulate real IoT traffic signal controllers.

Supported demonstration scenarios:
1. Normal immediate ACK
2. Delayed ACK (buffered command for asynchronous confirmation)
3. No ACK (dropped packet causing backend timeout)
4. Controller Failure / Rejection
5. Controller Offline (network disconnection / power loss)
6. Desired vs Actual Mismatch (hardware bulb burnout / discrepancy)
7. Duplicate ACK delivery
"""

from enum import Enum
from typing import Dict, List, Optional
from django.utils import timezone

from traffic.constants import ControllerStatus, Direction, SignalColor
from traffic.interfaces.controller_port import (
    ControllerCommandPayload,
    ControllerPort,
    ControllerResponse,
    ControllerTelemetry,
)


class SimulatorBehaviorMode(str, Enum):
    """Behavioral simulation profiles."""
    NORMAL = "NORMAL"            # Immediately confirms with matching actual state
    DELAYED_ACK = "DELAYED_ACK"  # Buffers command; requires manual or deferred trigger
    NO_ACK = "NO_ACK"            # Discards command without confirmation (triggers timeout)
    FAILURE = "FAILURE"          # Rejects command due to internal hardware fault
    OFFLINE = "OFFLINE"          # Controller unreachable / network down
    MISMATCH = "MISMATCH"        # Confirms with conflicting / unexpected aspect


class RestControllerSimulator(ControllerPort):
    """
    In-memory REST / IoT controller simulator implementing ControllerPort.
    Maintains simulated physical signal aspects and supports dynamic failure injection.
    """

    def __init__(self):
        # Simulated physical hardware state per junction
        self._hardware_signals: Dict[str, Dict[Direction, SignalColor]] = {}
        self._online_status: Dict[str, bool] = {}
        self._behavior_modes: Dict[str, SimulatorBehaviorMode] = {}
        self._received_commands: Dict[str, List[ControllerCommandPayload]] = {}
        self._delayed_buffer: Dict[str, ControllerCommandPayload] = {}

    def _ensure_junction_initialized(self, junction_id: str) -> None:
        if junction_id not in self._hardware_signals:
            self._hardware_signals[junction_id] = {
                Direction.NORTH: SignalColor.GREEN,
                Direction.SOUTH: SignalColor.GREEN,
                Direction.EAST: SignalColor.RED,
                Direction.WEST: SignalColor.RED,
            }
            self._online_status[junction_id] = True
            self._behavior_modes[junction_id] = SimulatorBehaviorMode.NORMAL
            self._received_commands[junction_id] = []

    # -------------------------------------------------------------------------
    # Configuration & Fault Injection Controls
    # -------------------------------------------------------------------------

    def set_behavior_mode(self, junction_id: str, mode: SimulatorBehaviorMode) -> None:
        """Injects a behavioral mode (NORMAL, DELAYED_ACK, NO_ACK, FAILURE, OFFLINE, MISMATCH)."""
        self._ensure_junction_initialized(junction_id)
        self._behavior_modes[junction_id] = mode
        if mode == SimulatorBehaviorMode.OFFLINE:
            self._online_status[junction_id] = False
        else:
            self._online_status[junction_id] = True

    def set_online(self, junction_id: str, is_online: bool) -> None:
        """Toggles connectivity to the controller."""
        self._ensure_junction_initialized(junction_id)
        self._online_status[junction_id] = is_online
        if not is_online:
            self._behavior_modes[junction_id] = SimulatorBehaviorMode.OFFLINE
        elif self._behavior_modes[junction_id] == SimulatorBehaviorMode.OFFLINE:
            self._behavior_modes[junction_id] = SimulatorBehaviorMode.NORMAL

    def force_hardware_signals(self, junction_id: str, signals: Dict[Direction, SignalColor]) -> None:
        """Directly sets simulated physical light states (useful for testing mismatches)."""
        self._ensure_junction_initialized(junction_id)
        self._hardware_signals[junction_id] = dict(signals)

    def get_received_commands(self, junction_id: str) -> List[ControllerCommandPayload]:
        return list(self._received_commands.get(junction_id, []))

    # -------------------------------------------------------------------------
    # ControllerPort Interface Implementation
    # -------------------------------------------------------------------------

    def send_signal_command(self, payload: ControllerCommandPayload) -> ControllerResponse:
        """Handles dispatched signal commands according to active behavior mode."""
        junction_id = payload.junction_id
        self._ensure_junction_initialized(junction_id)
        self._received_commands[junction_id].append(payload)

        mode = self._behavior_modes.get(junction_id, SimulatorBehaviorMode.NORMAL)
        now = timezone.now()

        # Scenario 1: Controller Offline
        if not self._online_status.get(junction_id, True) or mode == SimulatorBehaviorMode.OFFLINE:
            return ControllerResponse(
                success=False,
                command_id=payload.command_id,
                junction_id=junction_id,
                status="OFFLINE",
                message="Controller unreachable (connection refused / timeout).",
                timestamp=now,
            )

        # Scenario 2: Controller Failure
        if mode == SimulatorBehaviorMode.FAILURE:
            return ControllerResponse(
                success=False,
                command_id=payload.command_id,
                junction_id=junction_id,
                status="FAILED",
                message="Controller rejected command: internal relay failure.",
                timestamp=now,
            )

        # Scenario 3: No ACK (dropped packet)
        if mode == SimulatorBehaviorMode.NO_ACK:
            return ControllerResponse(
                success=True,
                command_id=payload.command_id,
                junction_id=junction_id,
                status="PENDING",
                message="Command buffered in controller transmission buffer, awaiting physical confirmation.",
                timestamp=now,
            )

        # Scenario 4: Delayed ACK
        if mode == SimulatorBehaviorMode.DELAYED_ACK:
            self._delayed_buffer[payload.command_id] = payload
            return ControllerResponse(
                success=True,
                command_id=payload.command_id,
                junction_id=junction_id,
                status="PENDING",
                message="Command queued by controller; confirmation delayed.",
                timestamp=now,
            )

        # Scenario 5: Hardware Aspect Mismatch
        if mode == SimulatorBehaviorMode.MISMATCH:
            # Report a conflicting state (e.g., requested GREEN, reports RED)
            conflicting_state = SignalColor.RED if payload.requested_state == SignalColor.GREEN else SignalColor.GREEN
            self._hardware_signals[junction_id][payload.direction] = conflicting_state
            return ControllerResponse(
                success=True,
                command_id=payload.command_id,
                junction_id=junction_id,
                actual_state=conflicting_state,
                status="ACK",
                message="Command acknowledged, but physical aspect sensor reports mismatch.",
                timestamp=now,
            )

        # Scenario 6: Normal Immediate Confirmation
        self._hardware_signals[junction_id][payload.direction] = payload.requested_state
        return ControllerResponse(
            success=True,
            command_id=payload.command_id,
            junction_id=junction_id,
            actual_state=payload.requested_state,
            status="ACK",
            message=f"Signal aspect for {payload.direction.value} confirmed {payload.requested_state.value}.",
            timestamp=now,
        )

    def trigger_delayed_ack(self, command_id: str) -> Optional[ControllerResponse]:
        """Manually releases a delayed ACK from the buffer."""
        payload = self._delayed_buffer.pop(command_id, None)
        if not payload:
            return None

        self._hardware_signals[payload.junction_id][payload.direction] = payload.requested_state
        return ControllerResponse(
            success=True,
            command_id=payload.command_id,
            junction_id=payload.junction_id,
            actual_state=payload.requested_state,
            status="ACK",
            message="Delayed confirmation delivered.",
            timestamp=timezone.now(),
        )

    def query_actual_signals(self, junction_id: str) -> ControllerTelemetry:
        """Queries confirmed physical signal aspects."""
        self._ensure_junction_initialized(junction_id)
        is_online = self._online_status.get(junction_id, True)
        status = ControllerStatus.ONLINE if is_online else ControllerStatus.OFFLINE
        signals = dict(self._hardware_signals[junction_id])

        return ControllerTelemetry(
            junction_id=junction_id,
            controller_status=status,
            actual_signals=signals,
            reported_at=timezone.now(),
            round_trip_ms=12.5 if is_online else 0.0,
        )

    def is_online(self, junction_id: str) -> bool:
        self._ensure_junction_initialized(junction_id)
        return self._online_status.get(junction_id, True)


# Singleton simulator instance for use across application services and tests
simulator_instance = RestControllerSimulator()
