"""
Comprehensive integration tests for EventProcessorService.
Tests concurrency, idempotency, ordering, locking, and safety invariants against PostgreSQL:
1. Duplicate event handling
2. Duplicate event under concurrent requests (multi-threaded race condition)
3. Invalid event rejection
4. Unknown junction handling
5. Vehicle clearance (including empty queue clearance)
6. Out-of-order sequence events
7. Simultaneous vehicle arrivals (concurrent thread pool)
8. Simultaneous emergency and manual override requests
9. Safety Invariant: Conflicting GREEN states are strictly impossible
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from traffic.constants import (
    AuditEventType,
    Direction,
    JunctionMode,
    SignalColor,
    TrafficPhase,
    VehicleType,
)
from traffic.domain.state_machine import assert_signal_safety
from traffic.models import AuditLog, Junction, ProcessedEvent, QueueEntry
from traffic.services.event_processor import EventProcessorService


def _run_worker_sensor_event(payload):
    try:
        return EventProcessorService.process_sensor_event(payload)
    finally:
        connection.close()


def _run_worker_manual_command(junction_id, command, direction, admin_id):
    try:
        return EventProcessorService.process_manual_command(junction_id, command, direction, admin_id)
    finally:
        connection.close()


class EventProcessorServiceTests(TransactionTestCase):
    """
    Uses TransactionTestCase so that real multi-threaded database transactions
    and row-level locks (select_for_update) can execute against PostgreSQL.
    """

    def setUp(self):
        # Create test junction
        self.junction = Junction.objects.create(
            id="A",
            name="Junction A - Main Plant",
            yellow_duration_sec=3,
            all_red_duration_sec=2,
            min_green_sec=10,
            max_green_sec=60,
            mode=JunctionMode.AUTOMATIC,
            current_phase=TrafficPhase.NORTH_SOUTH,
            desired_north=SignalColor.GREEN,
            desired_south=SignalColor.GREEN,
            desired_east=SignalColor.RED,
            desired_west=SignalColor.RED,
            actual_north=SignalColor.GREEN,
            actual_south=SignalColor.GREEN,
            actual_east=SignalColor.RED,
            actual_west=SignalColor.RED,
            queue_count_north=0,
            queue_count_south=0,
            queue_count_east=0,
            queue_count_west=0,
        )

    def tearDown(self):
        connections.close_all()

    # 1. Duplicate Event
    def test_duplicate_event(self):
        payload = {
            "event_id": "EVT_TEST_101",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "TRUCK",
            "vehicle_id": "TRK-01",
            "sequence_no": 1,
            "timestamp": timezone.now().isoformat(),
        }

        # First attempt: successfully processed
        res1 = EventProcessorService.process_sensor_event(payload)
        self.assertTrue(res1.success)
        self.assertEqual(res1.status, "PROCESSED")
        self.assertFalse(res1.is_duplicate)
        self.assertEqual(res1.queue_counts["NORTH"], 1)

        # Second attempt: detected as duplicate
        res2 = EventProcessorService.process_sensor_event(payload)
        self.assertTrue(res2.success)
        self.assertEqual(res2.status, "DUPLICATE")
        self.assertTrue(res2.is_duplicate)

        # Queue count did NOT increment again
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.queue_count_north, 1)
        self.assertEqual(QueueEntry.objects.filter(junction=self.junction).count(), 1)

    # 2. Duplicate Event Under Concurrent Requests
    def test_duplicate_event_under_concurrent_requests(self):
        """
        Simulate 8 concurrent worker threads posting the exact same event_id.
        Exactly 1 must succeed with PROCESSED; all other 7 must return DUPLICATE.
        Queue count must increment by exactly 1.
        """
        payload = {
            "event_id": "CONCURRENT_DUP_999",
            "junction_id": "A",
            "direction": "SOUTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "FORKLIFT",
            "vehicle_id": "FL-01",
            "sequence_no": 1,
            "timestamp": timezone.now().isoformat(),
        }

        results = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_run_worker_sensor_event, payload) for _ in range(8)]
            for f in as_completed(futures):
                results.append(f.result())

        processed_count = sum(1 for r in results if r.status == "PROCESSED")
        duplicate_count = sum(1 for r in results if r.status == "DUPLICATE")

        self.assertEqual(processed_count, 1)
        self.assertEqual(duplicate_count, 7)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.queue_count_south, 1)
        self.assertEqual(
            QueueEntry.objects.filter(junction=self.junction, vehicle_id="FL-01").count(),
            1,
        )

    # 3. Invalid Event
    def test_invalid_event(self):
        # Missing vehicle_type for arrival
        payload = {
            "event_id": "EVT_INVALID_01",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            # missing vehicle_type
        }
        res = EventProcessorService.process_sensor_event(payload)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "REJECTED")

        # Invalid direction
        payload2 = {
            "event_id": "EVT_INVALID_02",
            "junction_id": "A",
            "direction": "NORTH_WEST",  # invalid direction
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "TRUCK",
        }
        res2 = EventProcessorService.process_sensor_event(payload2)
        self.assertFalse(res2.success)
        self.assertEqual(res2.status, "REJECTED")

    # 4. Unknown Junction
    def test_unknown_junction(self):
        payload = {
            "event_id": "EVT_UNKNOWN_JUNC",
            "junction_id": "NON_EXISTENT_Z",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "TRUCK",
            "vehicle_id": "TRK-99",
        }
        res = EventProcessorService.process_sensor_event(payload)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "UNKNOWN_JUNCTION")
        self.assertIn("does not exist", res.message)

    # 5. Vehicle Clearance
    def test_vehicle_clearance(self):
        # 1. Arrive
        EventProcessorService.process_sensor_event({
            "event_id": "ARRIVE_01",
            "junction_id": "A",
            "direction": "EAST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "EMPLOYEE_VEHICLE",
            "vehicle_id": "EMP-101",
        })
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.queue_count_east, 1)

        # 2. Clear
        clear_res = EventProcessorService.process_sensor_event({
            "event_id": "CLEAR_01",
            "junction_id": "A",
            "direction": "EAST",
            "event_type": "VEHICLE_CLEARED",
            "vehicle_id": "EMP-101",
        })
        self.assertTrue(clear_res.success)
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.queue_count_east, 0)

        # 3. Clear on empty queue: must remain strictly 0, never negative
        clear_res2 = EventProcessorService.process_sensor_event({
            "event_id": "CLEAR_EMPTY",
            "junction_id": "A",
            "direction": "EAST",
            "event_type": "VEHICLE_CLEARED",
        })
        self.assertTrue(clear_res2.success)
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.queue_count_east, 0)

    # 6. Out-of-order Event
    def test_out_of_order_event(self):
        # Event with sequence 5
        res1 = EventProcessorService.process_sensor_event({
            "event_id": "SEQ_5",
            "junction_id": "A",
            "direction": "WEST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "TRUCK",
            "sequence_no": 5,
        })
        self.assertFalse(res1.is_out_of_order)

        # Event with sequence 3 arrives later (out of order)
        res2 = EventProcessorService.process_sensor_event({
            "event_id": "SEQ_3",
            "junction_id": "A",
            "direction": "WEST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "FORKLIFT",
            "sequence_no": 3,
        })
        self.assertTrue(res2.is_out_of_order)
        self.assertIn("OUT_OF_ORDER", res2.message)

    # 7. Simultaneous Vehicle Events
    def test_simultaneous_vehicle_events(self):
        """
        Send 12 simultaneous unique arrival events across different directions.
        Row-locking must serialize each update without deadlocks or corrupted queue sums.
        """
        payloads = [
            {
                "event_id": f"PARALLEL_EVT_{i}",
                "junction_id": "A",
                "direction": dir_name,
                "event_type": "VEHICLE_ARRIVED",
                "vehicle_type": "TRUCK",
                "vehicle_id": f"TRK-{i}",
                "sequence_no": i,
                "timestamp": timezone.now().isoformat(),
            }
            for i, dir_name in enumerate(["NORTH", "SOUTH", "EAST", "WEST"] * 3)
        ]

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(_run_worker_sensor_event, p) for p in payloads]
            results = [f.result() for f in as_completed(futures)]

        self.assertTrue(all(r.success for r in results))

        self.junction.refresh_from_db()
        total_queue = (
            self.junction.queue_count_north
            + self.junction.queue_count_south
            + self.junction.queue_count_east
            + self.junction.queue_count_west
        )
        self.assertEqual(total_queue, 12)

        # Verify safety invariant
        assert_signal_safety(self.junction.desired_signals)

    # 8. Simultaneous Emergency / Manual Request
    def test_simultaneous_emergency_manual_request(self):
        """
        Concurrent execution of an Emergency Vehicle Arrival and a Manual Override request.
        Row-locking ensures the emergency preemption dominates (EMERGENCY > MANUAL).
        """
        def send_emergency():
            return _run_worker_sensor_event({
                "event_id": "AMB_CRITICAL_911",
                "junction_id": "A",
                "direction": "EAST",
                "event_type": "VEHICLE_ARRIVED",
                "vehicle_type": "EMERGENCY",
                "vehicle_id": "AMB-911",
            })

        def send_manual():
            return _run_worker_manual_command(
                junction_id="A",
                command="MANUAL_GREEN_REQUEST",
                direction="NORTH",
                admin_id="chief_operator",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(send_emergency)
            f2 = executor.submit(send_manual)
            r1 = f1.result()
            r2 = f2.result()

        self.assertTrue(r1.success)
        self.assertTrue(r2.success)

        self.junction.refresh_from_db()
        # Emergency preemption must be active
        self.assertEqual(self.junction.mode, JunctionMode.EMERGENCY)
        self.assertEqual(self.junction.emergency_direction, Direction.EAST.value)

        # Signal safety holds
        assert_signal_safety(self.junction.desired_signals)

    # 9. No Conflicting GREEN States Invariant
    def test_no_conflicting_green_states(self):
        self.junction.refresh_from_db()
        # Test helper verifying that North/South and East/West are NEVER green simultaneously
        assert_signal_safety(self.junction.desired_signals)
        assert_signal_safety(self.junction.actual_signals)
