"""
Queue tracking and FIFO vehicle management for Factory Traffic Management System.
Enforces:
- Mathematical non-negative queue bounds (queue size >= 0 always).
- FIFO arrival order preservation.
- Priority category retention (EMERGENCY, TRUCK, FORKLIFT, EMPLOYEE_VEHICLE).
- Idempotent event deduplication.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from traffic.constants import Direction, VehicleType
from traffic.domain.exceptions import DuplicateEventError, InvalidEventError


@dataclass
class DomainVehicle:
    """Pure domain entity representing a queued vehicle."""
    vehicle_id: str
    vehicle_type: VehicleType
    direction: Direction
    arrived_at: float  # monotonic or epoch seconds
    sequence_no: int = 0

    def waiting_seconds(self, current_time: float) -> float:
        return max(0.0, current_time - self.arrived_at)


class QueueManager:
    """
    Manages directional vehicle queues at a junction.
    Maintains FIFO ordering per approach and guarantees queue counts never become negative.
    """

    def __init__(self):
        self._queues: Dict[Direction, List[DomainVehicle]] = {
            Direction.NORTH: [],
            Direction.SOUTH: [],
            Direction.EAST: [],
            Direction.WEST: [],
        }
        self._processed_events: Set[str] = set()

    def is_event_processed(self, event_id: str) -> bool:
        return event_id in self._processed_events

    def record_processed_event(self, event_id: str) -> None:
        if event_id in self._processed_events:
            raise DuplicateEventError(f"Sensor event '{event_id}' has already been processed.")
        self._processed_events.add(event_id)

    def add_vehicle(
        self,
        vehicle_id: str,
        vehicle_type: VehicleType,
        direction: Direction,
        arrived_at: float,
        sequence_no: int = 0,
        event_id: Optional[str] = None,
    ) -> DomainVehicle:
        """
        Adds a newly detected vehicle to the corresponding approach queue.
        Validates vehicle type and direction. Rejects duplicate event IDs.
        """
        if event_id:
            self.record_processed_event(event_id)

        if not vehicle_id:
            raise InvalidEventError("vehicle_id cannot be empty.")

        if direction not in self._queues:
            raise InvalidEventError(f"Invalid approach direction: {direction}")

        # Ensure vehicle_type is a valid enum choice
        if vehicle_type not in VehicleType.values:
            raise InvalidEventError(f"Invalid vehicle type: {vehicle_type}")

        vehicle = DomainVehicle(
            vehicle_id=vehicle_id,
            vehicle_type=VehicleType(vehicle_type),
            direction=direction,
            arrived_at=arrived_at,
            sequence_no=sequence_no,
        )
        self._queues[direction].append(vehicle)
        return vehicle

    def clear_vehicle(
        self,
        direction: Direction,
        vehicle_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> Optional[DomainVehicle]:
        """
        Removes a departing vehicle from the approach queue.
        - If the queue is already empty, returns None (count remains strictly 0, never negative).
        - If vehicle_id is provided and present, removes that vehicle.
        - Otherwise removes the oldest vehicle (FIFO, index 0).
        """
        if event_id:
            self.record_processed_event(event_id)

        if direction not in self._queues:
            raise InvalidEventError(f"Invalid approach direction: {direction}")

        queue = self._queues[direction]
        if not queue:
            # Queue is already 0; mathematical floor prevents negative queue
            return None

        # Look for matching vehicle_id if supplied
        if vehicle_id:
            for idx, veh in enumerate(queue):
                if veh.vehicle_id == vehicle_id:
                    return queue.pop(idx)

        # Default FIFO departure (oldest vehicle in queue departs first)
        return queue.pop(0)

    def get_count(self, direction: Direction) -> int:
        """Returns the non-negative queue length for a given direction."""
        return len(self._queues.get(direction, []))

    def get_counts(self) -> Dict[Direction, int]:
        """Returns non-negative queue counts for all 4 approaches."""
        return {
            Direction.NORTH: len(self._queues[Direction.NORTH]),
            Direction.SOUTH: len(self._queues[Direction.SOUTH]),
            Direction.EAST: len(self._queues[Direction.EAST]),
            Direction.WEST: len(self._queues[Direction.WEST]),
        }

    def get_total_count(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def get_waiting_vehicles(self, direction: Direction) -> List[DomainVehicle]:
        return list(self._queues.get(direction, []))

    def has_emergency(self, direction: Optional[Direction] = None) -> bool:
        """Checks if any vehicle in the specified direction (or all) is an EMERGENCY vehicle."""
        if direction:
            return any(v.vehicle_type == VehicleType.EMERGENCY for v in self._queues.get(direction, []))
        return any(
            v.vehicle_type == VehicleType.EMERGENCY
            for q in self._queues.values()
            for v in q
        )

    def get_emergency_directions(self) -> List[Direction]:
        """
        Returns list of directions containing waiting emergency vehicles,
        ordered by earliest arrival time (FIFO policy for competing emergencies).
        """
        emergency_dirs = []
        for direction, queue in self._queues.items():
            emergencies = [v for v in queue if v.vehicle_type == VehicleType.EMERGENCY]
            if emergencies:
                earliest_arrival = min(v.arrived_at for v in emergencies)
                emergency_dirs.append((earliest_arrival, direction))

        # Sort by earliest arrival timestamp (deterministic FIFO)
        emergency_dirs.sort(key=lambda item: item[0])
        return [direction for _, direction in emergency_dirs]

    def get_longest_waiting_seconds(self, direction: Direction, current_time: float) -> float:
        """Returns the waiting duration of the oldest vehicle in the queue."""
        queue = self._queues.get(direction, [])
        if not queue:
            return 0.0
        return queue[0].waiting_seconds(current_time)
