"""
Controller Service Layer.
Coordinates commands dispatched to signal controllers and processes acknowledgements,
timeouts, hardware telemetry, and restart recovery.

Safety Invariants:
1. Desired vs Actual Separation: Sending a command NEVER updates actual state.
   Only a verified, valid controller ACK updates actual state.
2. Duplicate ACK Protection: A duplicate ACK never causes duplicate state transitions.
3. Timeout Safety: If a command times out, physical state is NEVER assumed to have changed.
   The intersection enters DEGRADED / UNKNOWN mode.
4. Restart Recovery: Pending commands surviving a server restart are safely timed out
   and physical status is marked UNKNOWN until verified.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from django.db import transaction
from django.utils import timezone

from traffic.constants import (
    AuditEventType,
    CommandStatus,
    ControllerStatus,
    Direction,
    JunctionMode,
    SignalColor,
)
from traffic.controllers.rest_simulator import simulator_instance
from traffic.domain.state_machine import assert_signal_safety
from traffic.interfaces.controller_port import (
    ControllerCommandPayload,
    ControllerPort,
    ControllerResponse,
)
from traffic.models import AuditLog, ControllerCommand, Junction


@dataclass
class AckProcessingResult:
    """Result of processing a controller ACK."""
    success: bool
    status: str  # "ACK_PROCESSED", "DUPLICATE_ACK", "UNKNOWN_COMMAND", "MISMATCH", "REJECTED"
    command_id: str
    junction_id: str
    message: str
    is_duplicate: bool = False
    is_mismatch: bool = False
    actual_state: Optional[str] = None
    desired_state: Optional[str] = None


@dataclass
class StartupRecoveryReport:
    """Summary of commands recovered upon backend restart."""
    recovered_commands_count: int
    affected_junction_ids: List[str]
    details: List[str]


class ControllerService:
    """
    Application service managing the lifecycle of controller commands.
    Decoupled from protocol details via ControllerPort.
    """

    @classmethod
    def dispatch_signal_command(
        cls,
        junction: Junction,
        direction: Direction,
        requested_state: SignalColor,
        port: Optional[ControllerPort] = None,
        custom_command_id: Optional[str] = None,
    ) -> ControllerCommand:
        """
        Dispatches a signal change command.
        - Generates unique command_id.
        - Persists command in PENDING status.
        - Desired state is recorded, but ACTUAL STATE IS NOT UPDATED.
        - Dispatches via ControllerPort.
        """
        controller_port = port or simulator_instance
        now = timezone.now()

        # Generate unique command_id if not provided
        command_id = custom_command_id or f"CMD-{junction.id}-{direction.value}-{now.strftime('%H%M%S%f')[:10]}-{uuid.uuid4().hex[:4]}"

        # 1. Create ControllerCommand in database (status=PENDING)
        command = ControllerCommand.objects.create(
            command_id=command_id,
            junction=junction,
            direction=direction.value,
            requested_state=requested_state.value,
            status=CommandStatus.PENDING,
            sent_at=now,
        )

        # 2. Update Desired state on junction (Actual state remains untouched!)
        dir_attr = f"desired_{direction.value.lower()}"
        setattr(junction, dir_attr, requested_state.value)
        junction.save(update_fields=[dir_attr])

        # 3. Transmit command via protocol-agnostic ControllerPort
        payload = ControllerCommandPayload(
            command_id=command_id,
            junction_id=junction.id,
            direction=direction,
            requested_state=requested_state,
            sent_at=now,
            timeout_sec=float(junction.controller_timeout_sec),
        )

        response = controller_port.send_signal_command(payload)

        # 4. Handle immediate response from port
        if response.status == "OFFLINE":
            cls.handle_controller_failure(
                junction_id=junction.id,
                status=ControllerStatus.OFFLINE,
                reason="Controller connection refused / offline during dispatch.",
            )
            command.status = CommandStatus.FAILED
            command.error_message = response.message
            command.save(update_fields=["status", "error_message"])

        elif response.status == "FAILED":
            command.status = CommandStatus.FAILED
            command.error_message = response.message
            command.save(update_fields=["status", "error_message"])
            cls.handle_controller_failure(
                junction_id=junction.id,
                status=ControllerStatus.DEGRADED,
                reason=f"Controller rejected command {command_id}: {response.message}",
            )

        elif response.status == "ACK" and response.actual_state:
            # Immediate synchronous acknowledgement
            cls.handle_controller_ack(
                command_id=command_id,
                reported_actual_state=response.actual_state,
                status="ACK",
            )

        return command

    @classmethod
    def handle_controller_ack(
        cls,
        command_id: str,
        reported_actual_state: SignalColor,
        status: str = "ACK",
        error_message: str = "",
    ) -> AckProcessingResult:
        """
        Processes an incoming controller acknowledgement.
        1. Identifies command_id and verifies existence.
        2. Rejects unknown commands.
        3. Protects against duplicate ACKs (idempotent, never duplicates state transitions).
        4. Updates actual confirmed signal state ONLY when valid.
        5. Detects desired vs actual discrepancies (signal mismatches).
        6. Creates comprehensive audit trail.
        """
        now = timezone.now()

        # Step 1 & 2: Identify and verify command exists
        try:
            command = ControllerCommand.objects.get(command_id=command_id)
        except ControllerCommand.DoesNotExist:
            return AckProcessingResult(
                success=False,
                status="UNKNOWN_COMMAND",
                command_id=command_id,
                junction_id="",
                message=f"Received ACK for unknown command '{command_id}'. Ignored.",
            )

        junction = command.junction
        direction_str = command.direction
        direction = Direction(direction_str)

        # Step 3: Handle Duplicate ACK safely
        if command.status in (CommandStatus.ACK, CommandStatus.ACKNOWLEDGED):
            return AckProcessingResult(
                success=True,
                status="DUPLICATE_ACK",
                command_id=command_id,
                junction_id=junction.id,
                is_duplicate=True,
                message=f"Duplicate ACK received for command '{command_id}'. Already confirmed, ignored.",
                actual_state=command.actual_state,
                desired_state=command.requested_state,
            )

        # Step 4: Update actual state under junction row-lock
        with transaction.atomic():
            locked_junction = Junction.objects.select_for_update().get(id=junction.id)

            # Update command record
            command.status = CommandStatus.ACKNOWLEDGED
            command.actual_state = reported_actual_state.value
            command.acknowledged_at = now
            command.error_message = error_message
            command.save()

            # Update confirmed actual signal on the junction
            actual_attr = f"actual_{direction_str.lower()}"
            setattr(locked_junction, actual_attr, reported_actual_state.value)
            locked_junction.controller_status = ControllerStatus.ONLINE
            locked_junction.last_controller_heartbeat_at = now

            # Step 5: Check Desired vs Actual Mismatch
            desired_val = getattr(locked_junction, f"desired_{direction_str.lower()}")
            is_mismatch = (desired_val != reported_actual_state.value)

            if is_mismatch:
                locked_junction.controller_status = ControllerStatus.WARNING
                locked_junction.save()

                AuditLog.objects.create(
                    junction=locked_junction,
                    event_type=AuditEventType.DEVICE_FAILURE,
                    direction=direction_str,
                    command_id=command_id,
                    previous_state=desired_val,
                    new_state=reported_actual_state.value,
                    details=(
                        f"SIGNAL MISMATCH on {direction_str}: Desired {desired_val} != Confirmed Actual {reported_actual_state.value}. "
                        f"Hardware aspect anomaly detected."
                    ),
                    timestamp=now,
                )

                return AckProcessingResult(
                    success=True,
                    status="MISMATCH",
                    command_id=command_id,
                    junction_id=locked_junction.id,
                    is_mismatch=True,
                    message=f"Signal mismatch detected on {direction_str}.",
                    actual_state=reported_actual_state.value,
                    desired_state=desired_val,
                )

            locked_junction.save()

            # Step 6: Create Audit Log for Confirmed Signal
            AuditLog.objects.create(
                junction=locked_junction,
                event_type=AuditEventType.SIGNAL_CONFIRMED,
                direction=direction_str,
                command_id=command_id,
                new_state=reported_actual_state.value,
                details=f"Signal controller confirmed {direction_str} = {reported_actual_state.value}.",
                timestamp=now,
            )

        return AckProcessingResult(
            success=True,
            status="ACK_PROCESSED",
            command_id=command_id,
            junction_id=junction.id,
            is_mismatch=False,
            actual_state=reported_actual_state.value,
            desired_state=desired_val,
            message=f"Command {command_id} acknowledged: {direction_str} confirmed {reported_actual_state.value}.",
        )

    @classmethod
    def check_command_timeouts(cls, current_time: Optional[datetime] = None) -> List[ControllerCommand]:
        """
        Identifies PENDING commands that have exceeded their junction timeout.
        - Marks command as TIMEOUT.
        - Enters DEGRADED mode on junction.
        - NEVER assumes physical signal changed.
        - Audits timeout event.
        """
        now = current_time or timezone.now()
        timed_out_commands = []

        pending_commands = ControllerCommand.objects.filter(status=CommandStatus.PENDING).select_related("junction")

        for cmd in pending_commands:
            timeout_sec = float(cmd.junction.controller_timeout_sec)
            elapsed = (now - cmd.sent_at).total_seconds()

            if elapsed >= timeout_sec:
                with transaction.atomic():
                    cmd.status = CommandStatus.TIMEOUT
                    cmd.error_message = f"Timed out after {elapsed:.1f}s without controller ACK (limit: {timeout_sec}s)."
                    cmd.save()

                    # Put junction in degraded state
                    junc = Junction.objects.select_for_update().get(id=cmd.junction_id)
                    junc.controller_status = ControllerStatus.DEGRADED
                    junc.mode = JunctionMode.DEGRADED
                    junc.save()

                    AuditLog.objects.create(
                        junction=junc,
                        event_type=AuditEventType.CONTROLLER_TIMEOUT,
                        direction=cmd.direction,
                        command_id=cmd.command_id,
                        details=(
                            f"Command {cmd.command_id} timed out on {cmd.direction}. "
                            f"Physical signal state NOT assumed confirmed. Junction entered DEGRADED mode."
                        ),
                        timestamp=now,
                    )

                timed_out_commands.append(cmd)

        return timed_out_commands

    @classmethod
    def handle_controller_failure(
        cls,
        junction_id: str,
        status: ControllerStatus = ControllerStatus.OFFLINE,
        reason: str = "",
    ) -> None:
        """
        Handles controller disconnect, power loss, or hardware failure.
        - Sets controller_status to OFFLINE or DEGRADED.
        - Sets junction mode to DEGRADED.
        - Ensures physical state is NOT treated as confirmed.
        - Audits failure.
        """
        now = timezone.now()
        with transaction.atomic():
            try:
                junction = Junction.objects.select_for_update().get(id=junction_id)
            except Junction.DoesNotExist:
                return

            junction.controller_status = status
            junction.mode = JunctionMode.DEGRADED
            junction.save()

            AuditLog.objects.create(
                junction=junction,
                event_type=AuditEventType.DEVICE_FAILURE,
                details=f"Controller failure detected for Junction {junction_id}: {status.value}. {reason}".strip(),
                timestamp=now,
            )

    @classmethod
    def recover_pending_commands_on_startup(cls) -> StartupRecoveryReport:
        """
        Executed on backend startup to safely recover from unexpected restarts.
        - Queries all commands stranded in PENDING status.
        - Marks stranded commands as TIMEOUT.
        - Never assumes physical signals were successfully set.
        - Sets controller health to UNKNOWN / DEGRADED until verified.
        """
        now = timezone.now()
        stranded_commands = ControllerCommand.objects.filter(status=CommandStatus.PENDING)
        count = stranded_commands.count()
        affected_junctions = set()
        details = []

        with transaction.atomic():
            for cmd in stranded_commands:
                affected_junctions.add(cmd.junction_id)
                cmd.status = CommandStatus.TIMEOUT
                cmd.error_message = "Backend restarted while command was pending. Physical execution unconfirmed."
                cmd.save()
                details.append(f"Command {cmd.command_id} ({cmd.junction_id}/{cmd.direction}) marked TIMEOUT on startup.")

            for junc_id in affected_junctions:
                try:
                    junc = Junction.objects.select_for_update().get(id=junc_id)
                    junc.controller_status = ControllerStatus.UNKNOWN
                    junc.mode = JunctionMode.DEGRADED
                    junc.save()

                    AuditLog.objects.create(
                        junction=junc,
                        event_type=AuditEventType.DEVICE_FAILURE,
                        details="Startup recovery: Pending command stranded by server restart. Status set to UNKNOWN.",
                        timestamp=now,
                    )
                except Junction.DoesNotExist:
                    pass

        return StartupRecoveryReport(
            recovered_commands_count=count,
            affected_junction_ids=list(affected_junctions),
            details=details,
        )
