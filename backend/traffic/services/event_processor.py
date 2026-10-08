"""
Event Processor / Application Service Layer for Factory Traffic Management System.

Connects incoming API / sensor events to the pure traffic domain engine.

Orchestration Flow:
1. Receive & validate event payload.
2. Check duplicate event_id (idempotency check at application level).
3. Acquire pessimistic row-level lock on Junction (select_for_update within transaction.atomic()).
4. Detect delayed & out-of-order sequence events.
5. Hydrate pure-domain TrafficEngine from DB state.
6. Process domain event (VEHICLE_ARRIVED, VEHICLE_CLEARED).
7. Advance engine clock tick (trigger scheduler or transition stages).
8. Persist new state back to PostgreSQL (Junction, QueueEntry, ProcessedEvent).
9. Write comprehensive immutable AuditLog entry.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from traffic.constants import (
    AuditEventType,
    Direction,
    JunctionMode,
    QueueEntryStatus,
    SensorEventType,
    SignalColor,
    TrafficPhase,
    TransitionStage,
    VehicleType,
)
from traffic.domain.engine import TrafficEngine
from traffic.domain.exceptions import (
    DuplicateEventError,
    InvalidEventError,
    SafetyInvariantViolation,
    TrafficDomainError,
)
from traffic.domain.queue_manager import DomainVehicle
from traffic.domain.state_machine import SignalState
from traffic.models import AuditLog, Junction, ProcessedEvent, QueueEntry


@dataclass
class EventProcessingResult:
    """Result object returned by EventProcessor."""
    success: bool
    status: str  # "PROCESSED", "DUPLICATE", "REJECTED", "ERROR"
    event_id: str
    junction_id: str
    message: str
    is_duplicate: bool = False
    is_out_of_order: bool = False
    delay_seconds: float = 0.0
    queue_counts: Optional[Dict[str, int]] = None
    current_phase: Optional[str] = None
    desired_signals: Optional[Dict[str, str]] = None
    actual_signals: Optional[Dict[str, str]] = None
    audit_log_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "event_id": self.event_id,
            "junction_id": self.junction_id,
            "message": self.message,
            "is_duplicate": self.is_duplicate,
            "is_out_of_order": self.is_out_of_order,
            "delay_seconds": round(self.delay_seconds, 2),
            "queue_counts": self.queue_counts or {},
            "current_phase": self.current_phase,
            "desired_signals": self.desired_signals or {},
            "actual_signals": self.actual_signals or {},
        }


class EventProcessorService:
    """
    Application Service coordinating transactions, concurrency locking,
    idempotency, domain execution, and audit trail persistence.
    """

    @classmethod
    def process_sensor_event(cls, payload: Dict[str, Any]) -> EventProcessingResult:
        """
        Processes an incoming sensor detection event (VEHICLE_ARRIVED or VEHICLE_CLEARED).
        Enforces idempotency, serializes junction access via select_for_update,
        and delegates traffic logic to pure domain engine.
        """
        # Step 1: Basic validation
        validation_error, event_id, junction_id, direction, event_type, vehicle_type, vehicle_id, seq_no, sensor_time = (
            cls._validate_sensor_payload(payload)
        )
        if validation_error:
            # If junction is known, record rejected event audit
            if junction_id and Junction.objects.filter(id=junction_id).exists():
                cls._record_audit_log(
                    junction_id=junction_id,
                    event_type=AuditEventType.REJECTED_EVENT,
                    details=f"Rejected event {event_id}: {validation_error}",
                )
            return EventProcessingResult(
                success=False,
                status="REJECTED",
                event_id=event_id,
                junction_id=junction_id,
                message=validation_error,
            )

        # Step 2: Application-level check for duplicate event_id
        if ProcessedEvent.objects.filter(event_id=event_id).exists():
            return EventProcessingResult(
                success=True,
                status="DUPLICATE",
                event_id=event_id,
                junction_id=junction_id,
                is_duplicate=True,
                message=f"Event '{event_id}' has already been processed. Duplicate ignored without queue alteration.",
            )

        # Step 3: Concurrency Control - Acquire row lock on the Junction
        server_received_at = timezone.now()
        delay_seconds = max(0.0, (server_received_at - sensor_time).total_seconds())

        try:
            with transaction.atomic():
                # Verify junction exists with pessimistic lock
                try:
                    junction = Junction.objects.select_for_update().get(id=junction_id)
                except Junction.DoesNotExist:
                    return EventProcessingResult(
                        success=False,
                        status="UNKNOWN_JUNCTION",
                        event_id=event_id,
                        junction_id=junction_id,
                        message=f"Junction '{junction_id}' does not exist in system configuration.",
                    )

                # Re-check duplicate inside locked transaction (guards concurrent threads)
                if ProcessedEvent.objects.filter(event_id=event_id).exists():
                    return EventProcessingResult(
                        success=True,
                        status="DUPLICATE",
                        event_id=event_id,
                        junction_id=junction_id,
                        is_duplicate=True,
                        message=f"Event '{event_id}' already processed by concurrent request.",
                    )

                # Step 4: Out-of-order sequence check
                is_out_of_order = False
                last_seq = ProcessedEvent.objects.filter(
                    junction=junction,
                    direction=direction.value,
                ).aggregate(Max("sequence_no"))["sequence_no__max"] or 0

                if seq_no > 0 and seq_no < last_seq:
                    is_out_of_order = True

                # Step 5: Hydrate domain engine from persistent junction & queue entries
                engine = cls._hydrate_domain_engine(junction, server_received_at.timestamp())

                # Step 6: Process domain event
                audit_type = AuditEventType.VEHICLE_ARRIVED
                audit_details = ""

                if event_type == SensorEventType.VEHICLE_ARRIVED:
                    engine.handle_vehicle_arrival(
                        vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type,
                        direction=direction,
                        timestamp=sensor_time.timestamp(),
                        sequence_no=seq_no,
                        event_id=event_id,
                    )
                    # Persist vehicle queue entry
                    QueueEntry.objects.create(
                        junction=junction,
                        direction=direction.value,
                        vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type.value,
                        sequence_no=seq_no,
                        status=QueueEntryStatus.WAITING,
                        arrived_at=sensor_time,
                    )
                    audit_type = (
                        AuditEventType.EMERGENCY_DETECTED
                        if vehicle_type == VehicleType.EMERGENCY
                        else AuditEventType.VEHICLE_DETECTED
                    )
                    audit_details = (
                        f"Vehicle {vehicle_id} ({vehicle_type.value}) arrived at {direction.value}. "
                        f"Seq: {seq_no}. Sensor delay: {delay_seconds:.2f}s."
                    )
                    if is_out_of_order:
                        audit_details += f" [OUT_OF_ORDER: seq {seq_no} < max {last_seq}]"

                elif event_type == SensorEventType.VEHICLE_CLEARED:
                    cleared = engine.handle_vehicle_cleared(
                        direction=direction,
                        vehicle_id=vehicle_id,
                        timestamp=sensor_time.timestamp(),
                        event_id=event_id,
                    )
                    # Update DB QueueEntry
                    waiting_entry = QueueEntry.objects.filter(
                        junction=junction,
                        direction=direction.value,
                        status=QueueEntryStatus.WAITING,
                    )
                    if vehicle_id:
                        matched = waiting_entry.filter(vehicle_id=vehicle_id).first()
                        if matched:
                            matched.status = QueueEntryStatus.CLEARED
                            matched.cleared_at = server_received_at
                            matched.save(update_fields=["status", "cleared_at"])
                        else:
                            oldest = waiting_entry.order_by("arrived_at").first()
                            if oldest:
                                oldest.status = QueueEntryStatus.CLEARED
                                oldest.cleared_at = server_received_at
                                oldest.save(update_fields=["status", "cleared_at"])
                    else:
                        oldest = waiting_entry.order_by("arrived_at").first()
                        if oldest:
                            oldest.status = QueueEntryStatus.CLEARED
                            oldest.cleared_at = server_received_at
                            oldest.save(update_fields=["status", "cleared_at"])

                    audit_type = AuditEventType.VEHICLE_CLEARED
                    audit_details = (
                        f"Vehicle cleared from {direction.value}. "
                        f"{'Matched ' + cleared.vehicle_id if cleared else 'Queue was empty.'}"
                    )

                # Step 7: Advance engine clock tick to evaluate phase transitions or scheduling
                engine.tick(server_received_at.timestamp())

                # Step 8: Persist ProcessedEvent & Sync domain state back to Junction
                ProcessedEvent.objects.create(
                    event_id=event_id,
                    junction=junction,
                    direction=direction.value,
                    event_type=event_type.value,
                    vehicle_id=vehicle_id,
                    vehicle_type=vehicle_type.value if vehicle_type else "",
                    sequence_no=seq_no,
                    timestamp=sensor_time,
                    raw_payload=payload,
                )

                cls._sync_domain_engine_to_junction(engine, junction)
                junction.save()

                # Step 9: Create audit log
                audit_log = AuditLog.objects.create(
                    junction=junction,
                    event_type=audit_type,
                    direction=direction.value,
                    vehicle_id=vehicle_id,
                    vehicle_type=vehicle_type.value if vehicle_type else "",
                    details=audit_details,
                    timestamp=server_received_at,
                )

                return EventProcessingResult(
                    success=True,
                    status="PROCESSED",
                    event_id=event_id,
                    junction_id=junction_id,
                    message=audit_details,
                    is_out_of_order=is_out_of_order,
                    delay_seconds=delay_seconds,
                    queue_counts={d.value: engine.queue_manager.get_count(d) for d in Direction},
                    current_phase=junction.current_phase,
                    desired_signals={d.value: junction.desired_signals[d] for d in Direction},
                    actual_signals={d.value: junction.actual_signals[d] for d in Direction},
                    audit_log_id=audit_log.id,
                )

        except IntegrityError:
            # Database constraint caught concurrent duplicate insert
            return EventProcessingResult(
                success=True,
                status="DUPLICATE",
                event_id=event_id,
                junction_id=junction_id,
                is_duplicate=True,
                message=f"Event '{event_id}' caught by database unique constraint. Duplicate ignored.",
            )
        except TrafficDomainError as e:
            return EventProcessingResult(
                success=False,
                status="ERROR",
                event_id=event_id,
                junction_id=junction_id,
                message=f"Domain error during processing: {str(e)}",
            )

    @classmethod
    def process_manual_command(
        cls,
        junction_id: str,
        command: str,
        direction: Optional[str] = None,
        admin_id: str = "operator",
    ) -> EventProcessingResult:
        """
        Executes manual control requests (MANUAL_GREEN_REQUEST, RETURN_TO_AUTOMATIC).
        Acquires row-lock and routes through domain state machine to ensure safe clearance.
        """
        now = timezone.now()
        with transaction.atomic():
            try:
                junction = Junction.objects.select_for_update().get(id=junction_id)
            except Junction.DoesNotExist:
                return EventProcessingResult(
                    success=False,
                    status="UNKNOWN_JUNCTION",
                    event_id="",
                    junction_id=junction_id,
                    message=f"Junction '{junction_id}' does not exist.",
                )

            engine = cls._hydrate_domain_engine(junction, now.timestamp())

            if command == "MANUAL_GREEN_REQUEST":
                if not direction or direction not in Direction.values:
                    return EventProcessingResult(
                        success=False,
                        status="REJECTED",
                        event_id="",
                        junction_id=junction_id,
                        message=f"Invalid direction '{direction}' for manual green request.",
                    )
                target_dir = Direction(direction)
                engine.handle_manual_green_request(target_dir, requested_by=admin_id, current_time=now.timestamp())
                engine.tick(now.timestamp())
                cls._sync_domain_engine_to_junction(engine, junction)
                junction.manual_override_direction = target_dir.value
                junction.manual_override_by = admin_id
                junction.manual_override_at = now
                junction.save()

                AuditLog.objects.create(
                    junction=junction,
                    event_type=AuditEventType.MANUAL_OVERRIDE,
                    direction=target_dir.value,
                    details=f"Manual green requested for {target_dir.value} by {admin_id}. Safe transition initiated.",
                    timestamp=now,
                )

                return EventProcessingResult(
                    success=True,
                    status="PROCESSED",
                    event_id="",
                    junction_id=junction_id,
                    message=f"Manual green granted to {target_dir.value}.",
                    current_phase=junction.current_phase,
                    desired_signals={d.value: junction.desired_signals[d] for d in Direction},
                )

            elif command == "RETURN_TO_AUTOMATIC":
                engine.handle_return_to_automatic(now.timestamp())
                engine.tick(now.timestamp())
                cls._sync_domain_engine_to_junction(engine, junction)
                junction.manual_override_direction = None
                junction.manual_override_by = ""
                junction.manual_override_at = None
                junction.save()

                AuditLog.objects.create(
                    junction=junction,
                    event_type=AuditEventType.RETURN_TO_AUTOMATIC,
                    details=f"Returned to automatic scheduling mode by {admin_id}.",
                    timestamp=now,
                )

                return EventProcessingResult(
                    success=True,
                    status="PROCESSED",
                    event_id="",
                    junction_id=junction_id,
                    message="Junction returned to AUTOMATIC scheduling mode.",
                    current_phase=junction.current_phase,
                    desired_signals={d.value: junction.desired_signals[d] for d in Direction},
                )

            elif command == "EMERGENCY_CLEAR":
                engine._clear_emergency_mode(now.timestamp())
                engine.tick(now.timestamp())
                cls._sync_domain_engine_to_junction(engine, junction)
                junction.emergency_direction = None
                junction.emergency_vehicle_id = ""
                junction.save()

                AuditLog.objects.create(
                    junction=junction,
                    event_type=AuditEventType.EMERGENCY_CLEARED,
                    details=f"Emergency preemption cleared manually by {admin_id}.",
                    timestamp=now,
                )

                return EventProcessingResult(
                    success=True,
                    status="PROCESSED",
                    event_id="",
                    junction_id=junction_id,
                    message="Emergency cleared. Returned to previous operating mode.",
                    current_phase=junction.current_phase,
                    desired_signals={d.value: junction.desired_signals[d] for d in Direction},
                )

            else:
                return EventProcessingResult(
                    success=False,
                    status="REJECTED",
                    event_id="",
                    junction_id=junction_id,
                    message=f"Unsupported manual command: '{command}'.",
                )

    # -------------------------------------------------------------------------
    # Helper: Payload Validation
    # -------------------------------------------------------------------------

    @classmethod
    def _validate_sensor_payload(
        cls,
        payload: Dict[str, Any],
    ) -> Tuple[Optional[str], str, str, Optional[Direction], Optional[SensorEventType], Optional[VehicleType], str, int, datetime]:
        """Validates payload structure and parses timestamps and enums."""
        event_id = str(payload.get("event_id", "")).strip()
        if not event_id:
            return "Missing or empty 'event_id'.", "", "", None, None, None, "", 0, timezone.now()

        junction_id = str(payload.get("junction_id", "")).strip()
        if not junction_id:
            return "Missing or empty 'junction_id'.", event_id, "", None, None, None, "", 0, timezone.now()

        direction_raw = payload.get("direction")
        if direction_raw not in Direction.values:
            return f"Invalid or missing direction '{direction_raw}'.", event_id, junction_id, None, None, None, "", 0, timezone.now()
        direction = Direction(direction_raw)

        event_type_raw = payload.get("event_type")
        if event_type_raw not in SensorEventType.values:
            return f"Invalid or missing event_type '{event_type_raw}'.", event_id, junction_id, direction, None, None, "", 0, timezone.now()
        event_type = SensorEventType(event_type_raw)

        vehicle_type = None
        if event_type == SensorEventType.VEHICLE_ARRIVED:
            vehicle_type_raw = payload.get("vehicle_type")
            if vehicle_type_raw not in VehicleType.values:
                return f"Invalid vehicle_type '{vehicle_type_raw}' for arrival event.", event_id, junction_id, direction, event_type, None, "", 0, timezone.now()
            vehicle_type = VehicleType(vehicle_type_raw)

        vehicle_id = str(payload.get("vehicle_id", "")).strip()
        if not vehicle_id and event_type == SensorEventType.VEHICLE_ARRIVED:
            # Fall back to auto-generated vehicle identifier
            vehicle_id = f"VEH-{event_id[:8]}"

        seq_no = int(payload.get("sequence_no", 0))

        timestamp_raw = payload.get("timestamp")
        if timestamp_raw:
            parsed_dt = parse_datetime(str(timestamp_raw))
            sensor_time = parsed_dt if parsed_dt else timezone.now()
        else:
            sensor_time = timezone.now()

        return None, event_id, junction_id, direction, event_type, vehicle_type, vehicle_id, seq_no, sensor_time

    # -------------------------------------------------------------------------
    # Helper: Domain Engine Hydration & Sync
    # -------------------------------------------------------------------------

    @classmethod
    def _hydrate_domain_engine(cls, junction: Junction, current_time: float) -> TrafficEngine:
        """Hydrates a pure domain TrafficEngine instance from PostgreSQL persistent state."""
        # Determine initial SignalState from junction
        if junction.current_phase == TrafficPhase.NORTH_SOUTH:
            if junction.transition_stage == TransitionStage.YELLOW:
                initial_state = SignalState.NORTH_SOUTH_YELLOW
            elif junction.transition_stage == TransitionStage.ALL_RED:
                initial_state = SignalState.ALL_RED
            else:
                initial_state = SignalState.NORTH_SOUTH_GREEN
        elif junction.current_phase == TrafficPhase.EAST_WEST:
            if junction.transition_stage == TransitionStage.YELLOW:
                initial_state = SignalState.EAST_WEST_YELLOW
            elif junction.transition_stage == TransitionStage.ALL_RED:
                initial_state = SignalState.ALL_RED
            else:
                initial_state = SignalState.EAST_WEST_GREEN
        else:
            initial_state = SignalState.ALL_RED

        engine = TrafficEngine(
            junction_id=junction.id,
            initial_state=initial_state,
            yellow_duration=float(junction.yellow_duration_sec),
            all_red_duration=float(junction.all_red_duration_sec),
            min_green=float(junction.min_green_sec),
            max_green=float(junction.max_green_sec),
            current_time=current_time,
        )

        engine.mode = JunctionMode(junction.mode)
        engine.controller_status = junction.controller_status
        engine._actual_signals = junction.actual_signals

        if junction.emergency_direction:
            engine._active_emergency_direction = Direction(junction.emergency_direction)
            engine._active_emergency_vehicle_id = junction.emergency_vehicle_id

        if junction.manual_override_direction:
            engine._manual_target_direction = Direction(junction.manual_override_direction)
            engine._manual_requested_by = junction.manual_override_by

        # Hydrate waiting queue entries
        waiting_entries = QueueEntry.objects.filter(
            junction=junction,
            status=QueueEntryStatus.WAITING,
        ).order_by("arrived_at")

        for entry in waiting_entries:
            dir_enum = Direction(entry.direction)
            veh = DomainVehicle(
                vehicle_id=entry.vehicle_id,
                vehicle_type=VehicleType(entry.vehicle_type),
                direction=dir_enum,
                arrived_at=entry.arrived_at.timestamp(),
                sequence_no=entry.sequence_no,
            )
            engine.queue_manager._queues[dir_enum].append(veh)

        return engine

    @classmethod
    def _sync_domain_engine_to_junction(cls, engine: TrafficEngine, junction: Junction) -> None:
        """Persists pure domain engine results back onto the Junction model."""
        junction.mode = engine.mode.value
        junction.current_phase = engine.current_phase.value
        junction.transition_stage = engine.transition_stage.value

        # Desired signal aspects
        signals = engine.desired_signals
        junction.desired_north = signals[Direction.NORTH].value
        junction.desired_south = signals[Direction.SOUTH].value
        junction.desired_east = signals[Direction.EAST].value
        junction.desired_west = signals[Direction.WEST].value

        # Non-negative queue counts
        counts = engine.queue_manager.get_counts()
        junction.queue_count_north = counts[Direction.NORTH]
        junction.queue_count_south = counts[Direction.SOUTH]
        junction.queue_count_east = counts[Direction.EAST]
        junction.queue_count_west = counts[Direction.WEST]

        if engine._active_emergency_direction:
            junction.emergency_direction = engine._active_emergency_direction.value
            junction.emergency_vehicle_id = engine._active_emergency_vehicle_id or ""
        else:
            junction.emergency_direction = None
            junction.emergency_vehicle_id = ""

        if engine._manual_target_direction:
            junction.manual_override_direction = engine._manual_target_direction.value
        else:
            junction.manual_override_direction = None

    @classmethod
    def _record_audit_log(cls, junction_id: str, event_type: AuditEventType, details: str) -> None:
        try:
            j = Junction.objects.get(id=junction_id)
            AuditLog.objects.create(
                junction=j,
                event_type=event_type,
                details=details,
                timestamp=timezone.now(),
            )
        except Junction.DoesNotExist:
            pass
