"""
Transparent, deterministic traffic scheduling algorithm for Factory Traffic Management System.

Scoring Formula:
  Phase Score = Σ (Vehicle Priority Weight + Queue Size Weight + Waiting Time Weight + Starvation Bonus)

Weights & Rationale:
1. Vehicle Priority:
   - EMERGENCY:        1000.0 pts (highest preemption demand)
   - TRUCK:              25.0 pts (factory logistics, shipping deadline)
   - FORKLIFT:           15.0 pts (in-factory assembly transit)
   - EMPLOYEE_VEHICLE:    5.0 pts (commuter transport)

2. Queue Size Weight:
   - 10.0 pts per queued vehicle (encourages clearing high-density backups)

3. Waiting Time Weight:
   - 1.0 pt per second waited per vehicle (gradually increases urgency)

4. Starvation Protection:
   - If a vehicle waits >= 20.0 seconds:
     Bonus = 50.0 + (waiting_seconds - 20.0) * 3.0 pts
   - Guarantees low-priority vehicles (e.g. employee cars) eventually overcome trucks.

5. Unnecessary Switching Prevention (Inertia / Hysteresis):
   - Switching introduces ~5s clearance overhead (yellow + all-red).
   - The opposite phase must beat the active phase by at least SWITCHING_PENALTY (20.0 pts).
   - If opposite phase has 0 vehicles, NEVER switch.
   - Respects min_green (cannot switch before min_green unless emergency) and max_green.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from traffic.constants import Direction, TrafficPhase, VehicleType
from traffic.domain.queue_manager import QueueManager

# Documented Scoring Constants
PRIORITY_WEIGHTS: Dict[VehicleType, float] = {
    VehicleType.EMERGENCY: 1000.0,
    VehicleType.TRUCK: 25.0,
    VehicleType.FORKLIFT: 15.0,
    VehicleType.EMPLOYEE_VEHICLE: 5.0,
}

QUEUE_SIZE_WEIGHT: float = 10.0
WAITING_TIME_WEIGHT: float = 1.0
STARVATION_THRESHOLD_SEC: float = 20.0
SWITCHING_PENALTY: float = 20.0


@dataclass
class PhaseScore:
    """Detailed transparent breakdown of a phase's calculated priority score."""
    phase: TrafficPhase
    vehicle_count: int
    priority_score: float
    queue_score: float
    wait_score: float
    starvation_bonus: float
    total_score: float

    def __repr__(self) -> str:
        return (
            f"PhaseScore({self.phase.value}: total={self.total_score:.1f}, "
            f"count={self.vehicle_count}, prio={self.priority_score:.1f}, "
            f"wait={self.wait_score:.1f}, starv={self.starvation_bonus:.1f})"
        )


class TrafficScheduler:
    """
    Evaluates traffic demand across intersection phases and deterministically
    decides whether to maintain the active phase or initiate a transition.
    """

    PHASE_DIRECTIONS: Dict[TrafficPhase, List[Direction]] = {
        TrafficPhase.NORTH_SOUTH: [Direction.NORTH, Direction.SOUTH],
        TrafficPhase.EAST_WEST: [Direction.EAST, Direction.WEST],
    }

    @classmethod
    def calculate_phase_score(
        cls,
        phase: TrafficPhase,
        queue_manager: QueueManager,
        current_time: float,
    ) -> PhaseScore:
        """Computes the deterministic score for a traffic phase based on active queue contents."""
        directions = cls.PHASE_DIRECTIONS.get(phase, [])
        vehicles = []
        for d in directions:
            vehicles.extend(queue_manager.get_waiting_vehicles(d))

        vehicle_count = len(vehicles)
        if vehicle_count == 0:
            return PhaseScore(
                phase=phase,
                vehicle_count=0,
                priority_score=0.0,
                queue_score=0.0,
                wait_score=0.0,
                starvation_bonus=0.0,
                total_score=0.0,
            )

        priority_score = 0.0
        queue_score = vehicle_count * QUEUE_SIZE_WEIGHT
        wait_score = 0.0
        starvation_bonus = 0.0

        for v in vehicles:
            prio = PRIORITY_WEIGHTS.get(v.vehicle_type, 5.0)
            priority_score += prio

            wait_sec = v.waiting_seconds(current_time)
            wait_score += wait_sec * WAITING_TIME_WEIGHT

            if wait_sec >= STARVATION_THRESHOLD_SEC:
                starvation_bonus += 50.0 + (wait_sec - STARVATION_THRESHOLD_SEC) * 3.0

        total_score = priority_score + queue_score + wait_score + starvation_bonus

        return PhaseScore(
            phase=phase,
            vehicle_count=vehicle_count,
            priority_score=priority_score,
            queue_score=queue_score,
            wait_score=wait_score,
            starvation_bonus=starvation_bonus,
            total_score=total_score,
        )

    @classmethod
    def evaluate(
        cls,
        current_phase: TrafficPhase,
        phase_duration_seconds: float,
        queue_manager: QueueManager,
        current_time: float,
        min_green_seconds: float = 10.0,
        max_green_seconds: float = 60.0,
    ) -> Tuple[TrafficPhase, str, PhaseScore, PhaseScore]:
        """
        Determines the optimal phase according to queue demand and timing constraints.
        Returns:
            (target_phase, reason, ns_score, ew_score)
        """
        ns_score = cls.calculate_phase_score(TrafficPhase.NORTH_SOUTH, queue_manager, current_time)
        ew_score = cls.calculate_phase_score(TrafficPhase.EAST_WEST, queue_manager, current_time)

        # Identify active vs opposing score
        if current_phase == TrafficPhase.NORTH_SOUTH:
            active_score = ns_score
            opposing_score = ew_score
            opposing_phase = TrafficPhase.EAST_WEST
        else:
            active_score = ew_score
            opposing_score = ns_score
            opposing_phase = TrafficPhase.NORTH_SOUTH

        # Rule 1: Avoid unnecessary switching if opposite phase is completely empty
        if opposing_score.vehicle_count == 0:
            return current_phase, "Opposing phase is empty. Maintaining green.", ns_score, ew_score

        # Rule 2: Minimum Green Enforcement (unless emergency in opposing phase)
        has_opposing_emergency = any(
            queue_manager.has_emergency(d)
            for d in cls.PHASE_DIRECTIONS[opposing_phase]
        )
        if phase_duration_seconds < min_green_seconds and not has_opposing_emergency:
            remaining_min = min_green_seconds - phase_duration_seconds
            return (
                current_phase,
                f"Minimum green interval active ({remaining_min:.1f}s remaining).",
                ns_score,
                ew_score,
            )

        # Rule 3: Maximum Green Expiry (Starvation Protection against perpetual green)
        if phase_duration_seconds >= max_green_seconds and opposing_score.vehicle_count > 0:
            return (
                opposing_phase,
                f"Maximum green elapsed ({phase_duration_seconds:.1f}s >= {max_green_seconds}s). Forcing phase switch.",
                ns_score,
                ew_score,
            )

        # Rule 4: Priority & Starvation Scoring with Switching Inertia
        # Opposing phase must beat active score + switching penalty
        if opposing_score.total_score > (active_score.total_score + SWITCHING_PENALTY):
            return (
                opposing_phase,
                f"Opposing phase score ({opposing_score.total_score:.1f}) exceeds active score ({active_score.total_score:.1f}) + penalty ({SWITCHING_PENALTY}).",
                ns_score,
                ew_score,
            )

        return (
            current_phase,
            f"Active phase maintained (Active: {active_score.total_score:.1f} vs Opposing: {opposing_score.total_score:.1f}).",
            ns_score,
            ew_score,
        )
