"""
Non-blocking Signal Timing Service.

Architectural Guarantees:
1. Non-blocking: NEVER calls time.sleep() or asyncio.sleep() in API request handlers.
2. Timestamp-Driven: Phase durations and clearance intervals are driven by persistent
   timestamps (last_phase_change_at) and configurable bounds.
3. Concurrency Safe: Uses PostgreSQL row-level locks (select_for_update) to prevent
   duplicate transitions when multiple workers or threads execute.
4. Restart Recovery: Transition state and target phase survive server crashes safely.
   On startup, intermediate clearance is verified and physical state is never blindly assumed.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from traffic.constants import (
    AuditEventType,
    ControllerStatus,
    Direction,
    JunctionMode,
    QueueEntryStatus,
    SignalColor,
    TrafficPhase,
    TransitionStage,
    VehicleType,
)
from traffic.domain.queue_manager import DomainVehicle, QueueManager
from traffic.domain.scheduler import TrafficScheduler
from traffic.models import AuditLog, Junction, QueueEntry
from traffic.services.controller_service import ControllerService


@dataclass
class TimingTickResult:
    """Result summary of a single timing reconciliation tick."""
    junction_id: str
    previous_stage: str
    new_stage: str
    previous_phase: str
    new_phase: str
    state_changed: bool
    action_taken: str
    timestamp: datetime


@dataclass
class StartupTimingRecoveryReport:
    """Summary of transition states recovered on application startup."""
    recovered_junctions_count: int
    details: List[str]


class SignalTimingService:
    """
    Service coordinating non-blocking, timestamp-driven signal phase transitions.
    Can be driven by a background daemon thread, Celery beat, management command,
    or invoked on-demand via the REST API (/api/junctions/{id}/tick).
    """

    @classmethod
    def tick_junction(
        cls,
        junction_id: str,
        current_time: Optional[datetime] = None,
    ) -> TimingTickResult:
        """
        Reconciles the signal state machine for a single junction based on elapsed time.
        Serializes execution via row-level lock (select_for_update) to prevent duplicate transitions.
        """
        now = current_time or timezone.now()

        with transaction.atomic():
            try:
                junction = Junction.objects.select_for_update().get(id=junction_id)
            except Junction.DoesNotExist:
                return TimingTickResult(
                    junction_id=junction_id,
                    previous_stage="",
                    new_stage="",
                    previous_phase="",
                    new_phase="",
                    state_changed=False,
                    action_taken=f"Junction '{junction_id}' does not exist.",
                    timestamp=now,
                )

            # Check and update any timed out controller commands
            ControllerService.check_command_timeouts(now)

            prev_stage = junction.transition_stage
            prev_phase = junction.current_phase
            elapsed = max(0.0, (now - junction.last_phase_change_at).total_seconds())

            yellow_dur = float(junction.yellow_duration_sec)
            all_red_dur = float(junction.all_red_duration_sec)
            min_green = float(junction.min_green_sec)
            max_green = float(junction.max_green_sec)

            # -----------------------------------------------------------------
            # CASE 1: In YELLOW clearance phase
            # -----------------------------------------------------------------
            if junction.transition_stage == TransitionStage.YELLOW:
                if elapsed >= yellow_dur:
                    # Advance to ALL_RED buffer
                    junction.transition_stage = TransitionStage.ALL_RED
                    junction.last_phase_change_at = now
                    junction.desired_north = SignalColor.RED
                    junction.desired_south = SignalColor.RED
                    junction.desired_east = SignalColor.RED
                    junction.desired_west = SignalColor.RED
                    junction.save()

                    # Dispatch controller commands for all-red clearance
                    ControllerService.dispatch_signal_command(junction, Direction.NORTH, SignalColor.RED)
                    ControllerService.dispatch_signal_command(junction, Direction.SOUTH, SignalColor.RED)
                    ControllerService.dispatch_signal_command(junction, Direction.EAST, SignalColor.RED)
                    ControllerService.dispatch_signal_command(junction, Direction.WEST, SignalColor.RED)

                    AuditLog.objects.create(
                        junction=junction,
                        event_type=AuditEventType.SIGNAL_CHANGED,
                        details=(
                            f"Yellow clearance ({yellow_dur:.1f}s) finished. "
                            f"All approaches set to ALL_RED clearance buffer."
                        ),
                        timestamp=now,
                    )

                    return TimingTickResult(
                        junction_id=junction.id,
                        previous_stage=prev_stage,
                        new_stage=junction.transition_stage,
                        previous_phase=prev_phase,
                        new_phase=junction.current_phase,
                        state_changed=True,
                        action_taken="Transitioned from YELLOW to ALL_RED clearance buffer.",
                        timestamp=now,
                    )

                return TimingTickResult(
                    junction_id=junction.id,
                    previous_stage=prev_stage,
                    new_stage=prev_stage,
                    previous_phase=prev_phase,
                    new_phase=prev_phase,
                    state_changed=False,
                    action_taken=f"Yellow clearance active ({elapsed:.1f}s / {yellow_dur:.1f}s elapsed).",
                    timestamp=now,
                )

            # -----------------------------------------------------------------
            # CASE 2: In ALL_RED clearance interval
            # -----------------------------------------------------------------
            elif junction.transition_stage == TransitionStage.ALL_RED:
                if elapsed >= all_red_dur:
                    # All-red clearance completed. Grant GREEN to target_phase
                    target = TrafficPhase(junction.target_phase)
                    junction.current_phase = target.value
                    junction.transition_stage = TransitionStage.NONE
                    junction.last_phase_change_at = now

                    if target == TrafficPhase.NORTH_SOUTH:
                        junction.desired_north = SignalColor.GREEN
                        junction.desired_south = SignalColor.GREEN
                        junction.desired_east = SignalColor.RED
                        junction.desired_west = SignalColor.RED
                        ControllerService.dispatch_signal_command(junction, Direction.NORTH, SignalColor.GREEN)
                        ControllerService.dispatch_signal_command(junction, Direction.SOUTH, SignalColor.GREEN)
                    else:
                        junction.desired_east = SignalColor.GREEN
                        junction.desired_west = SignalColor.GREEN
                        junction.desired_north = SignalColor.RED
                        junction.desired_south = SignalColor.RED
                        ControllerService.dispatch_signal_command(junction, Direction.EAST, SignalColor.GREEN)
                        ControllerService.dispatch_signal_command(junction, Direction.WEST, SignalColor.GREEN)

                    junction.save()

                    AuditLog.objects.create(
                        junction=junction,
                        event_type=AuditEventType.SIGNAL_CHANGED,
                        details=(
                            f"All-red clearance ({all_red_dur:.1f}s) completed. "
                            f"Phase {target.value} granted GREEN."
                        ),
                        timestamp=now,
                    )

                    return TimingTickResult(
                        junction_id=junction.id,
                        previous_stage=prev_stage,
                        new_stage=junction.transition_stage,
                        previous_phase=prev_phase,
                        new_phase=junction.current_phase,
                        state_changed=True,
                        action_taken=f"All-red clearance finished. Granted GREEN to {target.value}.",
                        timestamp=now,
                    )

                return TimingTickResult(
                    junction_id=junction.id,
                    previous_stage=prev_stage,
                    new_stage=prev_stage,
                    previous_phase=prev_phase,
                    new_phase=prev_phase,
                    state_changed=False,
                    action_taken=f"All-red buffer active ({elapsed:.1f}s / {all_red_dur:.1f}s elapsed).",
                    timestamp=now,
                )

            # -----------------------------------------------------------------
            # CASE 3: In Steady GREEN (transition_stage == NONE)
            # -----------------------------------------------------------------
            else:
                current_phase_enum = TrafficPhase(junction.current_phase)
                opposing_phase = (
                    TrafficPhase.EAST_WEST
                    if current_phase_enum == TrafficPhase.NORTH_SOUTH
                    else TrafficPhase.NORTH_SOUTH
                )

                should_initiate_transition = False
                switch_reason = ""
                target_phase_decision = opposing_phase

                # Sub-case 3A: Emergency Preemption Demand
                if junction.emergency_direction:
                    emg_dir = Direction(junction.emergency_direction)
                    emg_phase = (
                        TrafficPhase.NORTH_SOUTH
                        if emg_dir in (Direction.NORTH, Direction.SOUTH)
                        else TrafficPhase.EAST_WEST
                    )
                    if emg_phase != current_phase_enum:
                        should_initiate_transition = True
                        target_phase_decision = emg_phase
                        switch_reason = f"Emergency vehicle on {emg_dir.value} demands preemption."

                # Sub-case 3B: Manual Override Demand
                elif junction.manual_override_direction and junction.mode == JunctionMode.MANUAL:
                    manual_dir = Direction(junction.manual_override_direction)
                    manual_phase = (
                        TrafficPhase.NORTH_SOUTH
                        if manual_dir in (Direction.NORTH, Direction.SOUTH)
                        else TrafficPhase.EAST_WEST
                    )
                    if manual_phase != current_phase_enum:
                        should_initiate_transition = True
                        target_phase_decision = manual_phase
                        switch_reason = f"Manual override demands {manual_dir.value} green."

                # Sub-case 3C: Automatic Priority & Starvation Scheduling
                elif junction.mode == JunctionMode.AUTOMATIC:
                    # Enforce minimum green interval before evaluating switch
                    if elapsed >= min_green:
                        # Build in-memory queue manager to evaluate scoring
                        qm = cls._build_queue_manager_for_junction(junction)
                        target_p, reason, ns_s, ew_s = TrafficScheduler.evaluate(
                            current_phase=current_phase_enum,
                            phase_duration_seconds=elapsed,
                            queue_manager=qm,
                            current_time=now.timestamp(),
                            min_green_seconds=min_green,
                            max_green_seconds=max_green,
                        )
                        if target_p != current_phase_enum:
                            should_initiate_transition = True
                            target_phase_decision = target_p
                            switch_reason = reason

                # If transition required, step into YELLOW clearance
                if should_initiate_transition:
                    junction.target_phase = target_phase_decision.value
                    junction.transition_stage = TransitionStage.YELLOW
                    junction.last_phase_change_at = now

                    if current_phase_enum == TrafficPhase.NORTH_SOUTH:
                        junction.desired_north = SignalColor.YELLOW
                        junction.desired_south = SignalColor.YELLOW
                        ControllerService.dispatch_signal_command(junction, Direction.NORTH, SignalColor.YELLOW)
                        ControllerService.dispatch_signal_command(junction, Direction.SOUTH, SignalColor.YELLOW)
                    else:
                        junction.desired_east = SignalColor.YELLOW
                        junction.desired_west = SignalColor.YELLOW
                        ControllerService.dispatch_signal_command(junction, Direction.EAST, SignalColor.YELLOW)
                        ControllerService.dispatch_signal_command(junction, Direction.WEST, SignalColor.YELLOW)

                    junction.save()

                    AuditLog.objects.create(
                        junction=junction,
                        event_type=AuditEventType.SIGNAL_TRANSITION_STARTED,
                        details=(
                            f"Initiated safe phase transition from {current_phase_enum.value} "
                            f"toward {target_phase_decision.value}. Active signals set to YELLOW. "
                            f"Reason: {switch_reason}"
                        ),
                        timestamp=now,
                    )

                    return TimingTickResult(
                        junction_id=junction.id,
                        previous_stage=prev_stage,
                        new_stage=junction.transition_stage,
                        previous_phase=prev_phase,
                        new_phase=junction.current_phase,
                        state_changed=True,
                        action_taken=f"Initiated YELLOW clearance toward {target_phase_decision.value}. {switch_reason}",
                        timestamp=now,
                    )

                return TimingTickResult(
                    junction_id=junction.id,
                    previous_stage=prev_stage,
                    new_stage=prev_stage,
                    previous_phase=prev_phase,
                    new_phase=prev_phase,
                    state_changed=False,
                    action_taken=f"Steady GREEN maintained on {current_phase_enum.value} ({elapsed:.1f}s elapsed).",
                    timestamp=now,
                )

    @classmethod
    def tick_all_junctions(cls, current_time: Optional[datetime] = None) -> List[TimingTickResult]:
        """Ticks all active junctions in the database."""
        now = current_time or timezone.now()
        results = []
        junction_ids = list(Junction.objects.values_list("id", flat=True))
        for j_id in junction_ids:
            res = cls.tick_junction(j_id, now)
            results.append(res)
        return results

    @classmethod
    def recover_timing_on_startup(cls) -> StartupTimingRecoveryReport:
        """
        Safely recovers in-flight transitions surviving a backend restart.
        1. Recovers stranded controller commands via ControllerService.
        2. Recovers junctions stuck in YELLOW or ALL_RED:
           - Does NOT assume physical signals completed transition.
           - Steps into ALL_RED buffer first to guarantee cross-traffic clearance.
           - Sets controller status to UNKNOWN until verified.
        """
        now = timezone.now()
        cmd_report = ControllerService.recover_pending_commands_on_startup()

        recovered_count = 0
        details = list(cmd_report.details)

        with transaction.atomic():
            mid_transition_junctions = Junction.objects.filter(
                transition_stage__in=[TransitionStage.YELLOW, TransitionStage.ALL_RED]
            ).select_for_update()

            for junc in mid_transition_junctions:
                recovered_count += 1
                stage_was = junc.transition_stage

                # Reset to ALL_RED buffer to guarantee clearance safety
                junc.transition_stage = TransitionStage.ALL_RED
                junc.last_phase_change_at = now
                junc.desired_north = SignalColor.RED
                junc.desired_south = SignalColor.RED
                junc.desired_east = SignalColor.RED
                junc.desired_west = SignalColor.RED
                junc.controller_status = ControllerStatus.UNKNOWN
                junc.mode = JunctionMode.DEGRADED
                junc.save()

                msg = (
                    f"Junction {junc.id} recovered from in-flight {stage_was}. "
                    f"Enforced ALL_RED clearance safety buffer. Controller status marked UNKNOWN."
                )
                details.append(msg)

                AuditLog.objects.create(
                    junction=junc,
                    event_type=AuditEventType.DEVICE_FAILURE,
                    details=f"Startup recovery: {msg}",
                    timestamp=now,
                )

        return StartupTimingRecoveryReport(
            recovered_junctions_count=recovered_count,
            details=details,
        )

    # -------------------------------------------------------------------------
    # Helper: Build QueueManager for Priority Evaluation
    # -------------------------------------------------------------------------

    @classmethod
    def _build_queue_manager_for_junction(cls, junction: Junction) -> QueueManager:
        qm = QueueManager()
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
            qm._queues[dir_enum].append(veh)

        return qm
