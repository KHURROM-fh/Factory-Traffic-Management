"""
Unit tests for the Core Traffic Domain Engine.
Tests all 17 requirements specified in the assessment:
1. Initial state
2. NS → EW safe transition
3. EW → NS safe transition
4. Invalid direct conflicting transition
5. Queue increase
6. Queue decrease
7. Queue cannot become negative
8. Truck priority
9. Emergency priority
10. Waiting-time/starvation protection
11. Manual override
12. Return to automatic
13. Emergency during manual mode
14. Multiple emergency requests
15. Duplicate event
16. Invalid event
17. Deterministic scheduling

These tests are pure Python unit tests; they require NO HTTP, NO DRF, and NO DB queries.
"""

import unittest

from traffic.constants import (
    ControllerStatus,
    Direction,
    JunctionMode,
    SignalColor,
    TrafficPhase,
    TransitionStage,
    VehicleType,
)
from traffic.domain.engine import TrafficEngine
from traffic.domain.exceptions import (
    DuplicateEventError,
    InvalidEventError,
    InvalidTransitionError,
    SafetyInvariantViolation,
)
from traffic.domain.queue_manager import QueueManager
from traffic.domain.scheduler import TrafficScheduler
from traffic.domain.state_machine import (
    SignalState,
    TrafficStateMachine,
    assert_signal_safety,
)


class CoreTrafficDomainEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = TrafficEngine(
            junction_id="A",
            initial_state=SignalState.NORTH_SOUTH_GREEN,
            yellow_duration=3.0,
            all_red_duration=2.0,
            min_green=10.0,
            max_green=60.0,
            current_time=0.0,
        )

    # 1. Initial State
    def test_01_initial_state(self):
        status = self.engine.get_status()
        self.assertEqual(status.junction_id, "A")
        self.assertEqual(status.mode, JunctionMode.AUTOMATIC)
        self.assertEqual(status.current_state, SignalState.NORTH_SOUTH_GREEN)
        self.assertEqual(status.phase, TrafficPhase.NORTH_SOUTH)
        self.assertEqual(status.transition_stage, TransitionStage.NONE)

        # Desired signals
        self.assertEqual(status.desired_signals[Direction.NORTH], SignalColor.GREEN)
        self.assertEqual(status.desired_signals[Direction.SOUTH], SignalColor.GREEN)
        self.assertEqual(status.desired_signals[Direction.EAST], SignalColor.RED)
        self.assertEqual(status.desired_signals[Direction.WEST], SignalColor.RED)

        # Initial queue sizes all 0
        for direction in Direction:
            self.assertEqual(status.queues[direction], 0)

        self.assertTrue(status.is_synchronized)
        self.assertFalse(status.in_transition)

    # 2. NS → EW Safe Transition
    def test_02_ns_to_ew_safe_transition(self):
        """
        Transitioning from NS_GREEN to EW_GREEN must strictly step through:
        NS_GREEN -> NS_YELLOW -> ALL_RED -> EW_GREEN
        """
        self.assertEqual(self.engine.current_state, SignalState.NORTH_SOUTH_GREEN)

        # Manual request for EAST
        self.engine.handle_manual_green_request(Direction.EAST, current_time=0.0)

        # Tick 1: Steps into NS_YELLOW
        status = self.engine.tick(current_time=0.0)
        self.assertEqual(status.current_state, SignalState.NORTH_SOUTH_YELLOW)
        self.assertEqual(status.desired_signals[Direction.NORTH], SignalColor.YELLOW)
        self.assertEqual(status.desired_signals[Direction.EAST], SignalColor.RED)

        # During yellow (t=1.5s): remains in NS_YELLOW
        status = self.engine.tick(current_time=1.5)
        self.assertEqual(status.current_state, SignalState.NORTH_SOUTH_YELLOW)

        # Yellow duration (3.0s) elapses at t=3.0s: Steps into ALL_RED
        status = self.engine.tick(current_time=3.0)
        self.assertEqual(status.current_state, SignalState.ALL_RED)
        for d in Direction:
            self.assertEqual(status.desired_signals[d], SignalColor.RED)

        # All-red duration (2.0s) elapses at t=5.0s: Steps into EW_GREEN
        status = self.engine.tick(current_time=5.0)
        self.assertEqual(status.current_state, SignalState.EAST_WEST_GREEN)
        self.assertEqual(status.desired_signals[Direction.EAST], SignalColor.GREEN)
        self.assertEqual(status.desired_signals[Direction.WEST], SignalColor.GREEN)
        self.assertEqual(status.desired_signals[Direction.NORTH], SignalColor.RED)
        self.assertEqual(status.desired_signals[Direction.SOUTH], SignalColor.RED)

    # 3. EW → NS Safe Transition
    def test_03_ew_to_ns_safe_transition(self):
        """
        Transitioning from EW_GREEN to NS_GREEN must strictly step through:
        EW_GREEN -> EW_YELLOW -> ALL_RED -> NS_GREEN
        """
        sm = TrafficStateMachine(initial_state=SignalState.EAST_WEST_GREEN)
        seq = sm.get_safe_transition_sequence(sm.current_state, SignalState.NORTH_SOUTH_GREEN)
        self.assertEqual(
            seq,
            [
                SignalState.EAST_WEST_YELLOW,
                SignalState.ALL_RED,
                SignalState.NORTH_SOUTH_GREEN,
            ],
        )

        # Execute step 1
        s1 = sm.transition_to(seq[0])
        self.assertEqual(s1, SignalState.EAST_WEST_YELLOW)

        # Execute step 2
        s2 = sm.transition_to(seq[1])
        self.assertEqual(s2, SignalState.ALL_RED)

        # Execute step 3
        s3 = sm.transition_to(seq[2])
        self.assertEqual(s3, SignalState.NORTH_SOUTH_GREEN)

    # 4. Invalid Direct Conflicting Transition
    def test_04_invalid_direct_conflicting_transition(self):
        sm = TrafficStateMachine(initial_state=SignalState.NORTH_SOUTH_GREEN)

        # Direct transition from NS_GREEN to EW_GREEN must be rejected
        with self.assertRaises(InvalidTransitionError):
            sm.transition_to(SignalState.EAST_WEST_GREEN)

        # Direct transition from NS_GREEN to ALL_RED (skipping yellow) must be rejected
        with self.assertRaises(InvalidTransitionError):
            sm.transition_to(SignalState.ALL_RED)

        # Verify assert_signal_safety catches conflicting GREEN
        corrupt_signals = {
            Direction.NORTH: SignalColor.GREEN,
            Direction.SOUTH: SignalColor.RED,
            Direction.EAST: SignalColor.GREEN,
            Direction.WEST: SignalColor.RED,
        }
        with self.assertRaises(SafetyInvariantViolation):
            assert_signal_safety(corrupt_signals)

    # 5. Queue Increase
    def test_05_queue_increase(self):
        self.engine.handle_vehicle_arrival(
            vehicle_id="TRK-01",
            vehicle_type=VehicleType.TRUCK,
            direction=Direction.NORTH,
            timestamp=10.0,
        )
        self.assertEqual(self.engine.queue_manager.get_count(Direction.NORTH), 1)

        self.engine.handle_vehicle_arrival(
            vehicle_id="FL-01",
            vehicle_type=VehicleType.FORKLIFT,
            direction=Direction.NORTH,
            timestamp=15.0,
        )
        self.assertEqual(self.engine.queue_manager.get_count(Direction.NORTH), 2)

    # 6. Queue Decrease
    def test_06_queue_decrease(self):
        self.engine.handle_vehicle_arrival("TRK-01", VehicleType.TRUCK, Direction.SOUTH, 10.0)
        self.engine.handle_vehicle_arrival("TRK-02", VehicleType.TRUCK, Direction.SOUTH, 12.0)
        self.assertEqual(self.engine.queue_manager.get_count(Direction.SOUTH), 2)

        # Clear first vehicle (FIFO)
        cleared = self.engine.handle_vehicle_cleared(Direction.SOUTH, timestamp=20.0)
        self.assertIsNotNone(cleared)
        self.assertEqual(cleared.vehicle_id, "TRK-01")
        self.assertEqual(self.engine.queue_manager.get_count(Direction.SOUTH), 1)

        # Clear second vehicle
        cleared2 = self.engine.handle_vehicle_cleared(Direction.SOUTH, timestamp=25.0)
        self.assertEqual(cleared2.vehicle_id, "TRK-02")
        self.assertEqual(self.engine.queue_manager.get_count(Direction.SOUTH), 0)

    # 7. Queue Cannot Become Negative
    def test_07_queue_cannot_become_negative(self):
        self.assertEqual(self.engine.queue_manager.get_count(Direction.WEST), 0)

        # Attempt to clear a non-existent vehicle
        cleared = self.engine.handle_vehicle_cleared(Direction.WEST, timestamp=30.0)
        self.assertIsNone(cleared)
        self.assertEqual(self.engine.queue_manager.get_count(Direction.WEST), 0)

        # Status inspection also reflects non-negative queue
        status = self.engine.get_status()
        self.assertEqual(status.queues[Direction.WEST], 0)

    # 8. Truck Priority
    def test_08_truck_priority(self):
        qm = QueueManager()
        # Add 1 employee car at NORTH
        qm.add_vehicle("CAR-01", VehicleType.EMPLOYEE_VEHICLE, Direction.NORTH, arrived_at=0.0)
        # Add 1 truck at EAST
        qm.add_vehicle("TRK-01", VehicleType.TRUCK, Direction.EAST, arrived_at=0.0)

        ns_score = TrafficScheduler.calculate_phase_score(TrafficPhase.NORTH_SOUTH, qm, current_time=0.0)
        ew_score = TrafficScheduler.calculate_phase_score(TrafficPhase.EAST_WEST, qm, current_time=0.0)

        # Truck priority (25.0) must exceed Employee Vehicle (5.0)
        self.assertGreater(ew_score.total_score, ns_score.total_score)
        self.assertEqual(ew_score.priority_score, 25.0)
        self.assertEqual(ns_score.priority_score, 5.0)

    # 8b. Forklift Priority
    def test_forklift_priority(self):
        qm = QueueManager()
        # Employee car at NORTH
        qm.add_vehicle("CAR-01", VehicleType.EMPLOYEE_VEHICLE, Direction.NORTH, arrived_at=0.0)
        # Forklift at EAST
        qm.add_vehicle("FL-01", VehicleType.FORKLIFT, Direction.EAST, arrived_at=0.0)

        ns_score = TrafficScheduler.calculate_phase_score(TrafficPhase.NORTH_SOUTH, qm, current_time=0.0)
        ew_score = TrafficScheduler.calculate_phase_score(TrafficPhase.EAST_WEST, qm, current_time=0.0)

        # Forklift priority (15.0) must exceed Employee Vehicle (5.0)
        self.assertGreater(ew_score.total_score, ns_score.total_score)
        self.assertEqual(ew_score.priority_score, 15.0)
        self.assertEqual(ns_score.priority_score, 5.0)

        # Furthermore, Truck (25.0) exceeds Forklift (15.0)
        qm.add_vehicle("TRK-01", VehicleType.TRUCK, Direction.NORTH, arrived_at=0.0)
        ns_score_updated = TrafficScheduler.calculate_phase_score(TrafficPhase.NORTH_SOUTH, qm, current_time=0.0)
        self.assertGreater(ns_score_updated.total_score, ew_score.total_score)

    # 8c. Employee Vehicle Priority and Lifecycle
    def test_employee_vehicle(self):
        qm = QueueManager()
        # Single employee vehicle arriving
        vehicle = qm.add_vehicle("EMP-01", VehicleType.EMPLOYEE_VEHICLE, Direction.SOUTH, arrived_at=10.0)
        self.assertEqual(vehicle.vehicle_type, VehicleType.EMPLOYEE_VEHICLE)
        self.assertEqual(qm.get_count(Direction.SOUTH), 1)

        ns_score = TrafficScheduler.calculate_phase_score(TrafficPhase.NORTH_SOUTH, qm, current_time=10.0)
        # Priority weight is 5.0, queue weight is 10.0 (1 vehicle), wait score is 0.0
        self.assertEqual(ns_score.priority_score, 5.0)
        self.assertEqual(ns_score.queue_score, 10.0)
        self.assertEqual(ns_score.total_score, 15.0)

    # 8d. Normal Traffic Flow
    def test_normal_traffic(self):
        self.assertEqual(self.engine.current_state, SignalState.NORTH_SOUTH_GREEN)
        # Vehicle arrives at East
        self.engine.handle_vehicle_arrival("CAR-EW", VehicleType.EMPLOYEE_VEHICLE, Direction.EAST, timestamp=0.0)
        # t=15.0: min_green (10s) elapsed, scheduler selects EW and plans transition
        self.engine.tick(current_time=15.0)
        # Next tick executes step to NS_YELLOW
        self.engine.tick(current_time=15.0)
        self.assertEqual(self.engine.current_state, SignalState.NORTH_SOUTH_YELLOW)
        # Yellow duration (3s) elapses at t=18.0
        self.engine.tick(current_time=18.0)
        self.assertEqual(self.engine.current_state, SignalState.ALL_RED)
        # All-red duration (2s) elapses at t=20.0
        self.engine.tick(current_time=20.0)
        self.assertEqual(self.engine.current_state, SignalState.EAST_WEST_GREEN)
        # Vehicle clears
        self.engine.handle_vehicle_cleared(direction=Direction.EAST, vehicle_id="CAR-EW", timestamp=21.0)
        self.assertEqual(self.engine.queue_manager.get_count(Direction.EAST), 0)

    # 9. Emergency Priority
    def test_09_emergency_priority(self):
        self.assertEqual(self.engine.current_state, SignalState.NORTH_SOUTH_GREEN)

        # Emergency vehicle arrives at EAST
        self.engine.handle_vehicle_arrival(
            vehicle_id="AMB-911",
            vehicle_type=VehicleType.EMERGENCY,
            direction=Direction.EAST,
            timestamp=5.0,
        )

        # Engine immediately switches to EMERGENCY mode
        self.assertEqual(self.engine.mode, JunctionMode.EMERGENCY)
        self.assertTrue(self.engine.in_transition)

        # Transition safely proceeds through Yellow -> All-Red -> EW_Green
        self.engine.tick(current_time=5.0)
        self.assertEqual(self.engine.current_state, SignalState.NORTH_SOUTH_YELLOW)

        self.engine.tick(current_time=8.0)
        self.assertEqual(self.engine.current_state, SignalState.ALL_RED)

        self.engine.tick(current_time=10.0)
        self.assertEqual(self.engine.current_state, SignalState.EAST_WEST_GREEN)
        self.assertEqual(self.engine.desired_signals[Direction.EAST], SignalColor.GREEN)

    # 10. Waiting-time / Starvation Protection
    def test_10_waiting_time_and_starvation_protection(self):
        qm = QueueManager()
        # Employee car has waited 35 seconds (past starvation threshold 20.0s)
        qm.add_vehicle("CAR-OLD", VehicleType.EMPLOYEE_VEHICLE, Direction.EAST, arrived_at=0.0)

        # Truck just arrived at NORTH (0 seconds waited)
        qm.add_vehicle("TRK-NEW", VehicleType.TRUCK, Direction.NORTH, arrived_at=35.0)

        current_time = 35.0
        ns_score = TrafficScheduler.calculate_phase_score(TrafficPhase.NORTH_SOUTH, qm, current_time)
        ew_score = TrafficScheduler.calculate_phase_score(TrafficPhase.EAST_WEST, qm, current_time)

        # Due to starvation bonus + wait time, the old employee vehicle beats the new truck!
        self.assertGreater(ew_score.total_score, ns_score.total_score)
        self.assertGreater(ew_score.starvation_bonus, 0.0)

    # 11. Manual Override
    def test_11_manual_override(self):
        self.assertEqual(self.engine.mode, JunctionMode.AUTOMATIC)

        self.engine.handle_manual_green_request(Direction.WEST, requested_by="operator_bob", current_time=0.0)
        self.assertEqual(self.engine.mode, JunctionMode.MANUAL)
        self.assertTrue(self.engine.in_transition)

        # Safety transitions must still be respected
        self.engine.tick(current_time=0.0)
        self.assertEqual(self.engine.current_state, SignalState.NORTH_SOUTH_YELLOW)
        self.engine.tick(current_time=3.0)
        self.assertEqual(self.engine.current_state, SignalState.ALL_RED)
        self.engine.tick(current_time=5.0)
        self.assertEqual(self.engine.current_state, SignalState.EAST_WEST_GREEN)

    # 12. Return to Automatic
    def test_12_return_to_automatic(self):
        self.engine.handle_manual_green_request(Direction.WEST, requested_by="operator_bob", current_time=0.0)
        self.assertEqual(self.engine.mode, JunctionMode.MANUAL)

        self.engine.handle_return_to_automatic(current_time=1.0)
        self.assertEqual(self.engine.mode, JunctionMode.AUTOMATIC)

    # 13. Emergency During Manual Mode
    def test_13_emergency_during_manual_mode(self):
        # Put system in MANUAL mode holding NS_GREEN
        self.engine.handle_manual_green_request(Direction.NORTH, requested_by="operator_bob", current_time=0.0)
        self.assertEqual(self.engine.mode, JunctionMode.MANUAL)

        # Emergency vehicle arrives at EAST
        self.engine.handle_vehicle_arrival("AMB-101", VehicleType.EMERGENCY, Direction.EAST, timestamp=5.0)

        # Emergency supersedes Manual mode (Priority: EMERGENCY > MANUAL > AUTOMATIC)
        self.assertEqual(self.engine.mode, JunctionMode.EMERGENCY)
        self.assertEqual(self.engine._active_emergency_direction, Direction.EAST)

    # 14. Multiple Emergency Requests (Competing Emergencies)
    def test_14_multiple_emergency_requests(self):
        # Emergency 1 arrives at EAST at t=5.0
        self.engine.handle_vehicle_arrival("AMB-01", VehicleType.EMERGENCY, Direction.EAST, timestamp=5.0)
        self.assertEqual(self.engine._active_emergency_direction, Direction.EAST)

        # Emergency 2 arrives at NORTH at t=6.0 (conflicting phase)
        self.engine.handle_vehicle_arrival("AMB-02", VehicleType.EMERGENCY, Direction.NORTH, timestamp=6.0)

        # Primary active emergency remains EAST (FIFO arrival)
        self.assertEqual(self.engine._active_emergency_direction, Direction.EAST)

        # Advance to EW_GREEN
        self.engine.tick(5.0)   # Yellow
        self.engine.tick(8.0)   # All-red
        self.engine.tick(10.0)  # EW Green granted
        self.assertEqual(self.engine.current_state, SignalState.EAST_WEST_GREEN)

        # Emergency 1 clears at EAST
        self.engine.handle_vehicle_cleared(Direction.EAST, "AMB-01", timestamp=15.0)

        # Engine detects remaining emergency at NORTH and immediately re-routes to NORTH!
        self.assertEqual(self.engine.mode, JunctionMode.EMERGENCY)
        self.assertEqual(self.engine._active_emergency_direction, Direction.NORTH)

    # 15. Duplicate Event (Idempotency)
    def test_15_duplicate_event(self):
        # First arrival with event_id
        self.engine.handle_vehicle_arrival(
            vehicle_id="TRK-99",
            vehicle_type=VehicleType.TRUCK,
            direction=Direction.NORTH,
            timestamp=10.0,
            event_id="EVT_UNIQUE_101",
        )
        self.assertEqual(self.engine.queue_manager.get_count(Direction.NORTH), 1)

        # Re-sending same event_id must raise DuplicateEventError
        with self.assertRaises(DuplicateEventError):
            self.engine.handle_vehicle_arrival(
                vehicle_id="TRK-99",
                vehicle_type=VehicleType.TRUCK,
                direction=Direction.NORTH,
                timestamp=10.0,
                event_id="EVT_UNIQUE_101",
            )

        # Queue count did not change
        self.assertEqual(self.engine.queue_manager.get_count(Direction.NORTH), 1)

    # 16. Invalid Event
    def test_16_invalid_event(self):
        # Empty vehicle_id
        with self.assertRaises(InvalidEventError):
            self.engine.handle_vehicle_arrival(
                vehicle_id="",
                vehicle_type=VehicleType.TRUCK,
                direction=Direction.NORTH,
                timestamp=10.0,
            )

        # Invalid vehicle type string
        with self.assertRaises(InvalidEventError):
            self.engine.handle_vehicle_arrival(
                vehicle_id="TRK-01",
                vehicle_type="FLYING_SAUCER",  # type: ignore
                direction=Direction.NORTH,
                timestamp=10.0,
            )

    # 17. Deterministic Scheduling
    def test_17_deterministic_scheduling(self):
        qm = QueueManager()
        qm.add_vehicle("TRK-1", VehicleType.TRUCK, Direction.NORTH, 10.0)
        qm.add_vehicle("CAR-1", VehicleType.EMPLOYEE_VEHICLE, Direction.EAST, 15.0)

        # Run scheduler 10 times with identical inputs
        results = [
            TrafficScheduler.evaluate(
                current_phase=TrafficPhase.NORTH_SOUTH,
                phase_duration_seconds=15.0,
                queue_manager=qm,
                current_time=30.0,
                min_green_seconds=10.0,
                max_green_seconds=60.0,
            )
            for _ in range(10)
        ]

        # Every single invocation must return the exact same target phase and scores
        first_phase, first_reason, first_ns, first_ew = results[0]
        for phase, reason, ns, ew in results[1:]:
            self.assertEqual(phase, first_phase)
            self.assertEqual(reason, first_reason)
            self.assertEqual(ns.total_score, first_ns.total_score)
            self.assertEqual(ew.total_score, first_ew.total_score)


if __name__ == "__main__":
    unittest.main()
