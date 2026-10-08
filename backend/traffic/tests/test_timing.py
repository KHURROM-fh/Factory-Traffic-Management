"""
Unit and integration tests for non-blocking signal timing and transitions:
1. Steady GREEN duration retention
2. Transition initiation from GREEN to YELLOW
3. Advance from YELLOW to ALL_RED buffer after yellow_duration_sec
4. Advance from ALL_RED to Target GREEN after all_red_duration_sec
5. Multi-worker concurrency safety (no duplicate transitions under concurrent ticks)
6. Restart recovery of in-flight transitions (enforces ALL_RED buffer and UNKNOWN status)
7. Emergency preemption immediate yellow trigger
8. Non-blocking /api/junctions/{id}/tick API endpoint execution
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

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
from traffic.models import AuditLog, Junction, QueueEntry
from traffic.services.timing_service import SignalTimingService


def _run_worker_tick(junction_id, current_time):
    try:
        return SignalTimingService.tick_junction(junction_id, current_time)
    finally:
        connections.close_all()


class SignalTimingServiceTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        self.t0 = timezone.now()
        self.junction = Junction.objects.create(
            id="A",
            name="Junction A - Main Plant",
            yellow_duration_sec=3,
            all_red_duration_sec=2,
            min_green_sec=10,
            max_green_sec=60,
            mode=JunctionMode.AUTOMATIC,
            current_phase=TrafficPhase.NORTH_SOUTH,
            target_phase=TrafficPhase.NORTH_SOUTH,
            transition_stage=TransitionStage.NONE,
            last_phase_change_at=self.t0,
            desired_north=SignalColor.GREEN,
            desired_south=SignalColor.GREEN,
            desired_east=SignalColor.RED,
            desired_west=SignalColor.RED,
            actual_north=SignalColor.GREEN,
            actual_south=SignalColor.GREEN,
            actual_east=SignalColor.RED,
            actual_west=SignalColor.RED,
            controller_status=ControllerStatus.ONLINE,
        )

    def tearDown(self):
        connections.close_all()

    # 1. Steady Green Duration
    def test_steady_green_duration_retention(self):
        # 5 seconds in: still within min_green (10s), no traffic on EW -> remains GREEN
        t_5 = self.t0 + timedelta(seconds=5)
        res = SignalTimingService.tick_junction("A", t_5)

        self.assertFalse(res.state_changed)
        self.assertEqual(res.new_stage, TransitionStage.NONE)
        self.assertEqual(res.new_phase, TrafficPhase.NORTH_SOUTH)

    # 2. Transition Initiation from GREEN to YELLOW
    def test_yellow_transition_initiation(self):
        # Add a waiting truck on EAST
        QueueEntry.objects.create(
            junction=self.junction,
            direction=Direction.EAST.value,
            vehicle_id="TRK-99",
            vehicle_type=VehicleType.TRUCK.value,
            status=QueueEntryStatus.WAITING,
            arrived_at=self.t0,
        )

        # Advance beyond min_green (10s) to 15s
        t_15 = self.t0 + timedelta(seconds=15)
        res = SignalTimingService.tick_junction("A", t_15)

        self.assertTrue(res.state_changed)
        self.assertEqual(res.new_stage, TransitionStage.YELLOW)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.transition_stage, TransitionStage.YELLOW)
        self.assertEqual(self.junction.desired_north, SignalColor.YELLOW)
        self.assertEqual(self.junction.desired_south, SignalColor.YELLOW)
        self.assertEqual(self.junction.target_phase, TrafficPhase.EAST_WEST)

    # 3. Advance from YELLOW to ALL_RED
    def test_yellow_duration_to_all_red(self):
        # Set junction to YELLOW at t0
        self.junction.transition_stage = TransitionStage.YELLOW
        self.junction.target_phase = TrafficPhase.EAST_WEST
        self.junction.last_phase_change_at = self.t0
        self.junction.save()

        # At t=1.5s (before yellow duration of 3s): remains YELLOW
        t_1_5 = self.t0 + timedelta(seconds=1.5)
        res1 = SignalTimingService.tick_junction("A", t_1_5)
        self.assertFalse(res1.state_changed)
        self.assertEqual(res1.new_stage, TransitionStage.YELLOW)

        # At t=3.0s (yellow duration elapsed): advances to ALL_RED
        t_3 = self.t0 + timedelta(seconds=3.0)
        res2 = SignalTimingService.tick_junction("A", t_3)
        self.assertTrue(res2.state_changed)
        self.assertEqual(res2.new_stage, TransitionStage.ALL_RED)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.desired_north, SignalColor.RED)
        self.assertEqual(self.junction.desired_south, SignalColor.RED)
        self.assertEqual(self.junction.desired_east, SignalColor.RED)
        self.assertEqual(self.junction.desired_west, SignalColor.RED)

    # 4. Advance from ALL_RED to Target GREEN
    def test_all_red_duration_to_target_green(self):
        # Set junction to ALL_RED at t0 heading toward EAST_WEST
        self.junction.transition_stage = TransitionStage.ALL_RED
        self.junction.target_phase = TrafficPhase.EAST_WEST
        self.junction.last_phase_change_at = self.t0
        self.junction.save()

        # At t=1.0s (before all-red duration of 2s): remains ALL_RED
        t_1 = self.t0 + timedelta(seconds=1.0)
        res1 = SignalTimingService.tick_junction("A", t_1)
        self.assertFalse(res1.state_changed)

        # At t=2.0s (all-red duration elapsed): advances to EAST_WEST GREEN
        t_2 = self.t0 + timedelta(seconds=2.0)
        res2 = SignalTimingService.tick_junction("A", t_2)
        self.assertTrue(res2.state_changed)
        self.assertEqual(res2.new_stage, TransitionStage.NONE)
        self.assertEqual(res2.new_phase, TrafficPhase.EAST_WEST)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.desired_east, SignalColor.GREEN)
        self.assertEqual(self.junction.desired_west, SignalColor.GREEN)
        self.assertEqual(self.junction.desired_north, SignalColor.RED)
        self.assertEqual(self.junction.desired_south, SignalColor.RED)

    # 5. Multi-Worker Concurrency Safety (No Duplicate Transitions)
    def test_multi_worker_concurrency_no_duplicate_transitions(self):
        """
        Multiple worker threads tick the same junction at the exact same timestamp.
        Row-locking ensures exactly ONE worker executes the state transition,
        while all others observe the updated timestamp and safely no-op.
        """
        # Set junction to YELLOW at t0
        self.junction.transition_stage = TransitionStage.YELLOW
        self.junction.target_phase = TrafficPhase.EAST_WEST
        self.junction.last_phase_change_at = self.t0
        self.junction.save()

        target_time = self.t0 + timedelta(seconds=3.0)
        results = []

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(_run_worker_tick, "A", target_time) for _ in range(6)]
            for f in as_completed(futures):
                results.append(f.result())

        # Exactly 1 worker changes state to ALL_RED; other 5 return state_changed=False
        state_changed_count = sum(1 for r in results if r.state_changed)
        self.assertEqual(state_changed_count, 1)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.transition_stage, TransitionStage.ALL_RED)

        # Audit log has exactly 1 entry for this transition
        change_audits = AuditLog.objects.filter(
            junction=self.junction,
            event_type=AuditEventType.SIGNAL_CHANGED,
            details__contains="ALL_RED",
        ).count()
        self.assertEqual(change_audits, 1)

    # 6. Restart Recovery of In-Flight Transitions
    def test_restart_recovery_mid_transition(self):
        """
        Simulate server crash while junction was in YELLOW.
        Startup recovery must enforce an ALL_RED clearance buffer and mark status UNKNOWN.
        """
        self.junction.transition_stage = TransitionStage.YELLOW
        self.junction.target_phase = TrafficPhase.EAST_WEST
        self.junction.save()

        report = SignalTimingService.recover_timing_on_startup()
        self.assertGreaterEqual(report.recovered_junctions_count, 1)

        self.junction.refresh_from_db()
        # Enforced ALL_RED clearance buffer
        self.assertEqual(self.junction.transition_stage, TransitionStage.ALL_RED)
        self.assertEqual(self.junction.desired_north, SignalColor.RED)
        self.assertEqual(self.junction.desired_east, SignalColor.RED)
        self.assertEqual(self.junction.controller_status, ControllerStatus.UNKNOWN)
        self.assertEqual(self.junction.mode, JunctionMode.DEGRADED)

    # 7. Emergency Preemption Immediate Yellow Trigger
    def test_emergency_preemption_timing_override(self):
        # Set active emergency on EAST
        self.junction.emergency_direction = Direction.EAST.value
        self.junction.mode = JunctionMode.EMERGENCY
        self.junction.save()

        # Tick at t=1s (even though min_green 10s has not elapsed)
        t_1 = self.t0 + timedelta(seconds=1.0)
        res = SignalTimingService.tick_junction("A", t_1)

        # Emergency forces immediate yellow transition
        self.assertTrue(res.state_changed)
        self.assertEqual(res.new_stage, TransitionStage.YELLOW)
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.target_phase, TrafficPhase.EAST_WEST.value)

    # 8. Non-blocking /api/junctions/{id}/tick API Endpoint
    def test_non_blocking_api_tick_endpoint(self):
        res = self.client.post("/api/junctions/A/tick")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["junction_id"], "A")
        self.assertIn("state_changed", res.data)
        self.assertIn("new_stage", res.data)
