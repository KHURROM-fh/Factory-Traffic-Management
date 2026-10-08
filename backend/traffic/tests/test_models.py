"""
Unit tests for core traffic domain models.
Tests model integrity, DB constraints, uniqueness, idempotency,
and separation of desired vs actual signal state.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from traffic.constants import (
    AuditEventType,
    CommandStatus,
    ControllerStatus,
    DeviceType,
    Direction,
    JunctionMode,
    QueueEntryStatus,
    SensorEventType,
    SignalColor,
    TrafficPhase,
    VehicleType,
)
from traffic.models import (
    AuditLog,
    ControllerCommand,
    DeviceStatusLog,
    Junction,
    ProcessedEvent,
    QueueEntry,
)


class JunctionModelTests(TestCase):
    def setUp(self):
        self.junction_a = Junction.objects.create(
            id="A",
            name="Junction A - Main Plant",
            description="Central intersection between cutting and sewing mills",
            yellow_duration_sec=3,
            all_red_duration_sec=2,
            min_green_sec=10,
            max_green_sec=60,
        )

    def test_junction_creation_and_defaults(self):
        self.assertEqual(self.junction_a.id, "A")
        self.assertEqual(self.junction_a.mode, JunctionMode.AUTOMATIC)
        self.assertEqual(self.junction_a.current_phase, TrafficPhase.NORTH_SOUTH)
        self.assertEqual(self.junction_a.controller_status, ControllerStatus.ONLINE)
        self.assertTrue(self.junction_a.is_synchronized)

    def test_multi_junction_support(self):
        """Verify models allow multiple dynamic junctions (A, B, C) without hardcoded logic."""
        junction_b = Junction.objects.create(
            id="B",
            name="Junction B - Warehouse Gate",
            min_green_sec=15,
            max_green_sec=45,
        )
        self.assertEqual(Junction.objects.count(), 2)
        self.assertEqual(junction_b.min_green_sec, 15)

    def test_desired_vs_actual_signal_separation(self):
        """Ensure desired commanded state and actual confirmed state are distinct."""
        self.junction_a.desired_north = SignalColor.YELLOW
        self.junction_a.actual_north = SignalColor.GREEN
        self.junction_a.save()

        self.assertFalse(self.junction_a.is_synchronized)
        self.assertEqual(self.junction_a.desired_signals[Direction.NORTH], SignalColor.YELLOW)
        self.assertEqual(self.junction_a.actual_signals[Direction.NORTH], SignalColor.GREEN)

    def test_negative_queue_prevention_at_database_level(self):
        """Ensure database constraint prevents negative queue values in PostgreSQL."""
        # Directly attempting to update queue to -1 should violate CheckConstraint
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Junction.objects.filter(id="A").update(queue_count_north=-1)


class ProcessedEventModelTests(TestCase):
    def setUp(self):
        self.junction = Junction.objects.create(id="A", name="Junction A")

    def test_event_id_idempotency_enforced_by_db(self):
        """Ensure duplicate event_id is rejected by primary key uniqueness."""
        now = timezone.now()
        ProcessedEvent.objects.create(
            event_id="evt_unique_101",
            junction=self.junction,
            direction=Direction.NORTH,
            event_type=SensorEventType.VEHICLE_ARRIVED,
            vehicle_type=VehicleType.TRUCK,
            vehicle_id="TRK-01",
            timestamp=now,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProcessedEvent.objects.create(
                    event_id="evt_unique_101",  # Same event_id
                    junction=self.junction,
                    direction=Direction.NORTH,
                    event_type=SensorEventType.VEHICLE_ARRIVED,
                    vehicle_type=VehicleType.TRUCK,
                    vehicle_id="TRK-01",
                    timestamp=now,
                )


class QueueEntryModelTests(TestCase):
    def setUp(self):
        self.junction = Junction.objects.create(id="A", name="Junction A")

    def test_queue_entry_lifecycle(self):
        """Verify queue item created as WAITING and transitioned to CLEARED."""
        entry = QueueEntry.objects.create(
            junction=self.junction,
            direction=Direction.SOUTH,
            vehicle_id="EMG-911",
            vehicle_type=VehicleType.EMERGENCY,
            sequence_no=1,
            status=QueueEntryStatus.WAITING,
        )
        self.assertEqual(entry.status, QueueEntryStatus.WAITING)
        self.assertIsNone(entry.cleared_at)

        # Mark cleared
        now = timezone.now()
        entry.status = QueueEntryStatus.CLEARED
        entry.cleared_at = now
        entry.save()

        entry.refresh_from_db()
        self.assertEqual(entry.status, QueueEntryStatus.CLEARED)
        self.assertEqual(entry.cleared_at, now)


class ControllerCommandModelTests(TestCase):
    def setUp(self):
        self.junction = Junction.objects.create(id="A", name="Junction A")

    def test_command_id_uniqueness(self):
        """Ensure command_id must be unique."""
        ControllerCommand.objects.create(
            command_id="cmd_201",
            junction=self.junction,
            direction=Direction.NORTH,
            requested_state=SignalColor.GREEN,
            status=CommandStatus.PENDING,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ControllerCommand.objects.create(
                    command_id="cmd_201",  # Duplicate command_id
                    junction=self.junction,
                    direction=Direction.SOUTH,
                    requested_state=SignalColor.RED,
                    status=CommandStatus.PENDING,
                )


class AuditLogAndDeviceStatusTests(TestCase):
    def setUp(self):
        self.junction = Junction.objects.create(id="A", name="Junction A")

    def test_audit_log_creation(self):
        audit = AuditLog.objects.create(
            junction=self.junction,
            event_type=AuditEventType.EMERGENCY_DETECTED,
            direction=Direction.EAST,
            vehicle_id="AMB-01",
            vehicle_type=VehicleType.EMERGENCY,
            details="Emergency vehicle detected on East approach. Initiating preemption sequence.",
        )
        self.assertIn("EMERGENCY_DETECTED", str(audit))

    def test_device_status_log_creation(self):
        log = DeviceStatusLog.objects.create(
            junction=self.junction,
            device_type=DeviceType.SIGNAL_CONTROLLER,
            device_identifier="CTRL-JUNC-A",
            status=ControllerStatus.ONLINE,
            is_healthy=True,
            details="Hardware controller responsive; round-trip 12ms",
        )
        self.assertEqual(log.status, ControllerStatus.ONLINE)
        self.assertTrue(log.is_healthy)
