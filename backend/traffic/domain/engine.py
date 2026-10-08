"""
Core Traffic Domain Engine for Factory Traffic Management System.

Architectural Guarantees:
1. Pure Python: Zero dependencies on DRF, serializers, HTTP, views, or database queries.
2. Invariant Enforcement:
   - Conflicting green signals are mathematically impossible.
   - All phase changes proceed deterministically through YELLOW -> ALL_RED -> GREEN.
   - Emergency and manual controls NEVER bypass clearance intervals.
   - Directional queues are strictly non-negative (>= 0).
   - Sensor events are strictly idempotent.
3. Mode Hierarchy:
   EMERGENCY > MANUAL > AUTOMATIC (with DEGRADED safety fallback on hardware faults).
4. Competing Emergencies Policy:
   - FIFO based on arrival timestamp.
   - Deterministic directional tie-breaker (NORTH > SOUTH > EAST > WEST).
   - Stale emergency timeout (default 60s) prevents permanent lockup.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from traffic.constants import (
    ControllerStatus,
    Direction,
    JunctionMode,
    SignalColor,
    TrafficPhase,
    TransitionStage,
    VehicleType,
)
from traffic.domain.exceptions import (
    DegradedModeError,
    DuplicateEventError,
    InvalidCommandError,
    InvalidEventError,
    InvalidTransitionError,
    SafetyInvariantViolation,
)
from traffic.domain.queue_manager import DomainVehicle, QueueManager
from traffic.domain.scheduler import PhaseScore, TrafficScheduler
from traffic.domain.state_machine import (
    SignalState,
    TrafficStateMachine,
    assert_signal_safety,
)


@dataclass
class EngineStatusReport:
    """Read-only domain status snapshot returned by the engine."""
    junction_id: str
    mode: JunctionMode
    current_state: SignalState
    phase: TrafficPhase
    transition_stage: TransitionStage
    desired_signals: Dict[Direction, SignalColor]
    actual_signals: Dict[Direction, SignalColor]
    is_synchronized: bool
    controller_status: ControllerStatus
    queues: Dict[Direction, int]
    in_transition: bool
    active_emergency_direction: Optional[Direction]
    manual_override_direction: Optional[Direction]
    last_action: str


class TrafficEngine:
    """
    Central pure-domain coordinator for traffic control at an intersection.
    """

    def __init__(
        self,
        junction_id: str = "A",
        initial_state: SignalState = SignalState.NORTH_SOUTH_GREEN,
        yellow_duration: float = 3.0,
        all_red_duration: float = 2.0,
        min_green: float = 10.0,
        max_green: float = 60.0,
        emergency_timeout: float = 60.0,
        controller_ack_timeout: float = 5.0,
        current_time: float = 0.0,
    ):
        self.junction_id = junction_id
        self.mode = JunctionMode.AUTOMATIC
        self.controller_status = ControllerStatus.ONLINE

        # State Machine & Queues
        self.state_machine = TrafficStateMachine(initial_state=initial_state)
        self.queue_manager = QueueManager()

        # Timing configurations (in seconds)
        self.yellow_duration = yellow_duration
        self.all_red_duration = all_red_duration
        self.min_green = min_green
        self.max_green = max_green
        self.emergency_timeout = emergency_timeout
        self.controller_ack_timeout = controller_ack_timeout

        # In-flight Transition Queue
        self._transition_queue: List[SignalState] = []
        self._last_state_change_time: float = current_time
        self._last_green_start_time: float = current_time

        # Actual Signals confirmed by physical/simulated controller
        self._actual_signals: Dict[Direction, SignalColor] = self.state_machine.get_signals()
        self._last_command_sent_time: Optional[float] = None
        self._last_action_description: str = "Engine initialized."

        # Emergency Preemption State
        self._active_emergency_direction: Optional[Direction] = None
        self._active_emergency_vehicle_id: Optional[str] = None
        self._emergency_granted_time: Optional[float] = None

        # Manual Override State
        self._manual_target_direction: Optional[Direction] = None
        self._manual_requested_by: str = ""
        self._manual_requested_at: Optional[float] = None

        # Run initial safety assertion
        self._assert_invariants()

    # -------------------------------------------------------------------------
    # Properties & Getters
    # -------------------------------------------------------------------------

    @property
    def current_state(self) -> SignalState:
        return self.state_machine.current_state

    @property
    def current_phase(self) -> TrafficPhase:
        return self.state_machine.current_state.phase

    @property
    def transition_stage(self) -> TransitionStage:
        if self.state_machine.current_state.is_yellow:
            return TransitionStage.YELLOW
        elif self.state_machine.current_state.is_all_red:
            return TransitionStage.ALL_RED
        return TransitionStage.NONE

    @property
    def desired_signals(self) -> Dict[Direction, SignalColor]:
        return self.state_machine.get_signals()

    @property
    def actual_signals(self) -> Dict[Direction, SignalColor]:
        return dict(self._actual_signals)

    @property
    def is_synchronized(self) -> bool:
        """True if confirmed hardware signals match desired signal aspects."""
        desired = self.desired_signals
        return (
            self.controller_status == ControllerStatus.ONLINE
            and all(desired[d] == self._actual_signals.get(d) for d in Direction)
        )

    @property
    def in_transition(self) -> bool:
        return len(self._transition_queue) > 0 or not self.state_machine.current_state.is_green

    # -------------------------------------------------------------------------
    # Invariant Verification (Section 9)
    # -------------------------------------------------------------------------

    def _assert_invariants(self) -> None:
        """Validates all core safety invariants."""
        # 1. Desired signals must never have conflicting greens or yellows
        assert_signal_safety(self.desired_signals)

        # 2. Confirmed actual signals must never have conflicting greens
        if self.controller_status == ControllerStatus.ONLINE:
            assert_signal_safety(self._actual_signals)

        # 3. Queue counts must never be negative
        for direction, count in self.queue_manager.get_counts().items():
            if count < 0:
                raise SafetyInvariantViolation(
                    f"Queue count for {direction} became negative: {count}"
                )

    # -------------------------------------------------------------------------
    # Controller Telemetry & Acknowledgement
    # -------------------------------------------------------------------------

    def update_controller_status(self, status: ControllerStatus, current_time: float) -> None:
        """Updates controller connectivity health."""
        self.controller_status = status
        if status in (ControllerStatus.OFFLINE, ControllerStatus.DEGRADED, ControllerStatus.UNKNOWN):
            self.mode = JunctionMode.DEGRADED
            self._last_action_description = f"Controller entered {status.value} mode. Degraded state active."
        elif status == ControllerStatus.ONLINE and self.mode == JunctionMode.DEGRADED:
            # Recover back to automatic
            self.mode = JunctionMode.AUTOMATIC
            self._last_action_description = "Controller returned to ONLINE. Resuming automatic mode."

    def acknowledge_controller_state(self, reported_signals: Dict[Direction, SignalColor]) -> None:
        """Records acknowledged physical signal state reported by the controller."""
        self._actual_signals = dict(reported_signals)
        self._last_command_sent_time = None
        self._assert_invariants()

    # -------------------------------------------------------------------------
    # Vehicle Arrival & Clearance Handling (Section 4 & 8)
    # -------------------------------------------------------------------------

    def handle_vehicle_arrival(
        self,
        vehicle_id: str,
        vehicle_type: VehicleType,
        direction: Direction,
        timestamp: float,
        sequence_no: int = 0,
        event_id: Optional[str] = None,
    ) -> DomainVehicle:
        """
        Processes a vehicle arrival sensor event.
        - Validates parameters and checks idempotency.
        - Adds vehicle to approach queue.
        - Triggers immediate emergency preemption if an EMERGENCY vehicle arrives.
        """
        # 1. Queue manager adds vehicle and enforces idempotency
        vehicle = self.queue_manager.add_vehicle(
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            direction=direction,
            arrived_at=timestamp,
            sequence_no=sequence_no,
            event_id=event_id,
        )

        self._last_action_description = f"Vehicle {vehicle_id} ({vehicle_type.value}) arrived at {direction.value}."

        # 2. Check for Emergency Preemption (Section 5)
        if vehicle_type == VehicleType.EMERGENCY:
            if self.mode != JunctionMode.EMERGENCY or self._active_emergency_direction is None:
                self._trigger_emergency_preemption(direction, vehicle_id, timestamp)
            elif self._active_emergency_direction == direction:
                self._active_emergency_vehicle_id = vehicle_id
            else:
                # Competing emergency from conflicting direction:
                # Earliest emergency (active) is served first.
                self._last_action_description = (
                    f"Competing emergency detected at {direction.value}. "
                    f"Queued behind active emergency at {self._active_emergency_direction.value} (FIFO policy)."
                )

        self._assert_invariants()
        return vehicle

    def handle_vehicle_cleared(
        self,
        direction: Direction,
        vehicle_id: Optional[str] = None,
        timestamp: float = 0.0,
        event_id: Optional[str] = None,
    ) -> Optional[DomainVehicle]:
        """
        Processes a vehicle clearance sensor event.
        - Removes vehicle from queue (non-negative floor preserved).
        - If an emergency vehicle was cleared, evaluates next emergency or returns to normal mode.
        """
        cleared_vehicle = self.queue_manager.clear_vehicle(
            direction=direction,
            vehicle_id=vehicle_id,
            event_id=event_id,
        )

        if cleared_vehicle:
            self._last_action_description = f"Vehicle {cleared_vehicle.vehicle_id} cleared from {direction.value}."
        else:
            self._last_action_description = f"Clearance received for {direction.value}, queue was already empty."

        # Check if active emergency vehicle cleared
        if self.mode == JunctionMode.EMERGENCY and self._active_emergency_direction == direction:
            # Check if any emergency vehicles remain
            remaining_emergencies = self.queue_manager.get_emergency_directions()
            if remaining_emergencies:
                # Competing emergencies: switch to next earliest emergency direction (FIFO)
                next_dir = remaining_emergencies[0]
                self._trigger_emergency_preemption(next_dir, vehicle_id="", current_time=timestamp)
            else:
                # All emergencies cleared
                self._clear_emergency_mode(timestamp)

        self._assert_invariants()
        return cleared_vehicle

    # -------------------------------------------------------------------------
    # Emergency Preemption (Section 5)
    # -------------------------------------------------------------------------

    def _trigger_emergency_preemption(
        self,
        emergency_direction: Direction,
        vehicle_id: str,
        current_time: float,
    ) -> None:
        """
        Preempts intersection for emergency vehicle.
        Mode priority: EMERGENCY > MANUAL > AUTOMATIC.
        CRITICAL SAFETY RULE: Emergency transitions NEVER bypass safety transitions.
        NS_GREEN -> NS_YELLOW -> ALL_RED -> EW_GREEN
        """
        self.mode = JunctionMode.EMERGENCY
        self._active_emergency_direction = emergency_direction
        self._active_emergency_vehicle_id = vehicle_id

        # Determine target green phase
        target_phase = (
            TrafficPhase.NORTH_SOUTH
            if emergency_direction in (Direction.NORTH, Direction.SOUTH)
            else TrafficPhase.EAST_WEST
        )
        target_state = (
            SignalState.NORTH_SOUTH_GREEN
            if target_phase == TrafficPhase.NORTH_SOUTH
            else SignalState.EAST_WEST_GREEN
        )

        # If already green in the emergency phase, maintain green immediately
        if self.state_machine.current_state == target_state and not self._transition_queue:
            self._emergency_granted_time = current_time
            self._last_action_description = (
                f"Emergency preemption: {emergency_direction.value} is ALREADY GREEN. Maintained."
            )
            return

        # Plan safe transition sequence (YELLOW -> ALL_RED -> TARGET_GREEN)
        self._plan_safe_transition(target_state)
        self._emergency_granted_time = current_time
        self._last_action_description = (
            f"Emergency preemption activated for {emergency_direction.value}. Initiating safe clearance transition."
        )

    def _clear_emergency_mode(self, current_time: float) -> None:
        """Restores normal operation after emergency vehicle departs."""
        self._active_emergency_direction = None
        self._active_emergency_vehicle_id = None
        self._emergency_granted_time = None

        if self._manual_target_direction is not None:
            self.mode = JunctionMode.MANUAL
            self._last_action_description = "Emergency cleared. Resumed prior MANUAL override mode."
        else:
            self.mode = JunctionMode.AUTOMATIC
            self._last_action_description = "Emergency cleared. Returned to AUTOMATIC scheduling mode."

    # -------------------------------------------------------------------------
    # Manual Control (Section 6)
    # -------------------------------------------------------------------------

    def handle_manual_green_request(
        self,
        direction: Direction,
        requested_by: str = "operator",
        current_time: float = 0.0,
    ) -> None:
        """
        Requests manual green for a given direction.
        - Does NOT bypass safety transitions.
        - Subordinate to EMERGENCY mode (Emergency > Manual).
        - Simultaneous commands policy: Latest command updates the target safely.
        """
        # Mode Priority check: Emergency takes precedence
        if self.mode == JunctionMode.EMERGENCY:
            self._manual_target_direction = direction
            self._manual_requested_by = requested_by
            self._manual_requested_at = current_time
            self._last_action_description = (
                f"Manual command queued: Active EMERGENCY takes precedence over manual request for {direction.value}."
            )
            return

        if self.mode == JunctionMode.DEGRADED:
            raise DegradedModeError("Cannot accept manual green request while junction is in DEGRADED mode.")

        self.mode = JunctionMode.MANUAL
        self._manual_target_direction = direction
        self._manual_requested_by = requested_by
        self._manual_requested_at = current_time

        target_phase = (
            TrafficPhase.NORTH_SOUTH
            if direction in (Direction.NORTH, Direction.SOUTH)
            else TrafficPhase.EAST_WEST
        )
        target_state = (
            SignalState.NORTH_SOUTH_GREEN
            if target_phase == TrafficPhase.NORTH_SOUTH
            else SignalState.EAST_WEST_GREEN
        )

        if self.state_machine.current_state == target_state and not self._transition_queue:
            self._last_action_description = (
                f"Manual override: {direction.value} is ALREADY GREEN. Maintained."
            )
            return

        # Execute safe transition sequence
        self._plan_safe_transition(target_state)
        self._last_action_description = (
            f"Manual override: Safe transition initiated toward {target_state.value} for {direction.value}."
        )

    def handle_return_to_automatic(self, current_time: float = 0.0) -> None:
        """Cancels manual override and restores automatic scheduling."""
        self._manual_target_direction = None
        self._manual_requested_by = ""
        self._manual_requested_at = None

        if self.mode != JunctionMode.EMERGENCY:
            self.mode = JunctionMode.AUTOMATIC
            self._last_action_description = "Returned to AUTOMATIC scheduling mode."

    # -------------------------------------------------------------------------
    # Transition Execution
    # -------------------------------------------------------------------------

    def _plan_safe_transition(self, target_state: SignalState) -> None:
        """
        Constructs the strict sequence of transitions required to safely reach target_state.
        If a transition is already in flight, replaces subsequent steps while preserving
        immediate clearance steps.
        """
        current = self.state_machine.current_state
        if current == target_state:
            self._transition_queue = []
            return

        sequence = TrafficStateMachine.get_safe_transition_sequence(current, target_state)
        self._transition_queue = sequence

    # -------------------------------------------------------------------------
    # Clock Tick & Scheduling Loop (Sections 2, 3, 5)
    # -------------------------------------------------------------------------

    def tick(self, current_time: float) -> EngineStatusReport:
        """
        Advances the engine by 1 tick / current_time update:
        1. Checks stale emergency timeout.
        2. Advances in-flight clearance transitions (YELLOW -> ALL_RED -> GREEN).
        3. If in AUTOMATIC mode and no transition in-flight, evaluates scheduling score.
        4. Asserts all safety invariants.
        """
        # 1. Stale emergency detection (Section 5)
        if self.mode == JunctionMode.EMERGENCY and self._emergency_granted_time is not None:
            time_in_emergency = current_time - self._emergency_granted_time
            if time_in_emergency >= self.emergency_timeout:
                self._last_action_description = (
                    f"STALE EMERGENCY: Emergency vehicle exceeded {self.emergency_timeout}s timeout. Clearing preemption."
                )
                self._clear_emergency_mode(current_time)

        # 2. Advance In-Flight Transitions
        if self._transition_queue:
            time_in_current_state = current_time - self._last_state_change_time
            curr = self.state_machine.current_state

            can_advance = False
            if curr.is_green:
                # Immediate transition to Yellow allowed
                can_advance = True
            elif curr.is_yellow:
                can_advance = time_in_current_state >= self.yellow_duration
            elif curr.is_all_red:
                can_advance = time_in_current_state >= self.all_red_duration

            if can_advance:
                next_state = self._transition_queue.pop(0)
                self.state_machine.transition_to(next_state)
                self._last_state_change_time = current_time

                if next_state.is_green:
                    self._last_green_start_time = current_time
                    self._last_action_description = f"Reached green phase: {next_state.value}."
                else:
                    self._last_action_description = f"Stepped transition to: {next_state.value}."

        # 3. Evaluate Automatic Scheduling (Section 3)
        elif self.mode == JunctionMode.AUTOMATIC and self.state_machine.current_state.is_green:
            time_in_green = current_time - self._last_green_start_time
            curr_phase = self.state_machine.current_state.phase

            target_phase, reason, ns_score, ew_score = TrafficScheduler.evaluate(
                current_phase=curr_phase,
                phase_duration_seconds=time_in_green,
                queue_manager=self.queue_manager,
                current_time=current_time,
                min_green_seconds=self.min_green,
                max_green_seconds=self.max_green,
            )

            if target_phase != curr_phase:
                target_state = (
                    SignalState.NORTH_SOUTH_GREEN
                    if target_phase == TrafficPhase.NORTH_SOUTH
                    else SignalState.EAST_WEST_GREEN
                )
                self._plan_safe_transition(target_state)
                self._last_action_description = f"Scheduler switch: {reason}"

        # 4. Enforce Invariants
        self._assert_invariants()

        return self.get_status()

    # -------------------------------------------------------------------------
    # Status Inspection
    # -------------------------------------------------------------------------

    def get_status(self) -> EngineStatusReport:
        """Returns a snapshot of the current domain engine state."""
        return EngineStatusReport(
            junction_id=self.junction_id,
            mode=self.mode,
            current_state=self.state_machine.current_state,
            phase=self.state_machine.current_state.phase,
            transition_stage=self.transition_stage,
            desired_signals=self.desired_signals,
            actual_signals=self.actual_signals,
            is_synchronized=self.is_synchronized,
            controller_status=self.controller_status,
            queues=self.queue_manager.get_counts(),
            in_transition=self.in_transition,
            active_emergency_direction=self._active_emergency_direction,
            manual_override_direction=self._manual_target_direction,
            last_action=self._last_action_description,
        )
