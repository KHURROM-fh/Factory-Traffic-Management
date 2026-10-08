"""
Tests for Controller Communication Layer, Ports, Simulator, and Recovery:
1. Command creation
2. Command ID uniqueness
3. ACK processing and actual signal update
4. Duplicate ACK safety (idempotent, no repeated state changes)
5. Unknown command rejection
6. Command timeout handling (DEGRADED fallback, no physical assumption)
7. Controller offline handling
8. Desired vs actual signal mismatch detection
9. Backend restart / pending command recovery
"""

from datetime import timedelta
from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from traffic.constants import (
    AuditEventType,
    CommandStatus,
    ControllerStatus,
    Direction,
    JunctionMode,
    SignalColor,
    TrafficPhase,
)
from traffic.controllers.rest_simulator import (
    RestControllerSimulator,
    SimulatorBehaviorMode,
)
from traffic.models import AuditLog, ControllerCommand, Junction
from traffic.services.controller_service import ControllerService


class ControllerCommunicationTests(TransactionTestCase):
    def setUp(self):
        self.simulator = RestControllerSimulator()
        self.junction = Junction.objects.create(
            id="A",
            name="Junction A - Main Plant",
            yellow_duration_sec=3,
            all_red_duration_sec=2,
            min_green_sec=10,
            max_green_sec=60,
            controller_timeout_sec=5,
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
            controller_status=ControllerStatus.ONLINE,
        )

    def tearDown(self):
        connections.close_all()

    # 1. Command Creation
    def test_command_creation(self):
        # Configure simulator to buffer command without immediate ACK
        self.simulator.set_behavior_mode("A", SimulatorBehaviorMode.DELAYED_ACK)

        cmd = ControllerService.dispatch_signal_command(
            junction=self.junction,
            direction=Direction.EAST,
            requested_state=SignalColor.YELLOW,
            port=self.simulator,
            custom_command_id="CMD-TEST-101",
        )

        self.assertEqual(cmd.command_id, "CMD-TEST-101")
        self.assertEqual(cmd.status, CommandStatus.PENDING)
        self.assertEqual(cmd.requested_state, SignalColor.YELLOW.value)

        # Crucial check: Desired is YELLOW, but ACTUAL is STILL RED!
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.desired_east, SignalColor.YELLOW.value)
        self.assertEqual(self.junction.actual_east, SignalColor.RED.value)

    # 2. Command ID Uniqueness
    def test_command_id_uniqueness(self):
        now = timezone.now()
        ControllerCommand.objects.create(
            command_id="CMD-UNIQUE-1",
            junction=self.junction,
            direction=Direction.NORTH.value,
            requested_state=SignalColor.GREEN.value,
            sent_at=now,
        )

        # Duplicate command_id must violate DB uniqueness
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ControllerCommand.objects.create(
                    command_id="CMD-UNIQUE-1",
                    junction=self.junction,
                    direction=Direction.SOUTH.value,
                    requested_state=SignalColor.RED.value,
                    sent_at=now,
                )

    # 3. ACK Processing
    def test_ack(self):
        # Dispatch command
        self.simulator.set_behavior_mode("A", SimulatorBehaviorMode.DELAYED_ACK)
        cmd = ControllerService.dispatch_signal_command(
            junction=self.junction,
            direction=Direction.NORTH,
            requested_state=SignalColor.YELLOW,
            port=self.simulator,
            custom_command_id="CMD-ACK-01",
        )
        self.assertEqual(cmd.status, CommandStatus.PENDING)

        # Deliver controller ACK
        ack_res = ControllerService.handle_controller_ack(
            command_id="CMD-ACK-01",
            reported_actual_state=SignalColor.YELLOW,
        )

        self.assertTrue(ack_res.success)
        self.assertEqual(ack_res.status, "ACK_PROCESSED")
        self.assertFalse(ack_res.is_duplicate)
        self.assertFalse(ack_res.is_mismatch)

        # Verify command record updated
        cmd.refresh_from_db()
        self.assertEqual(cmd.status, CommandStatus.ACKNOWLEDGED)
        self.assertEqual(cmd.actual_state, SignalColor.YELLOW.value)
        self.assertIsNotNone(cmd.acknowledged_at)

        # Verify actual state on junction updated to confirmed value
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.actual_north, SignalColor.YELLOW.value)

        # Verify audit log created
        audit = AuditLog.objects.filter(command_id="CMD-ACK-01").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.event_type, AuditEventType.SIGNAL_CONFIRMED)

    # 4. Duplicate ACK
    def test_duplicate_ack(self):
        self.simulator.set_behavior_mode("A", SimulatorBehaviorMode.DELAYED_ACK)
        cmd = ControllerService.dispatch_signal_command(
            junction=self.junction,
            direction=Direction.NORTH,
            requested_state=SignalColor.YELLOW,
            port=self.simulator,
            custom_command_id="CMD-DUP-ACK",
        )

        # First ACK: processes normally
        res1 = ControllerService.handle_controller_ack(
            command_id="CMD-DUP-ACK",
            reported_actual_state=SignalColor.YELLOW,
        )
        self.assertEqual(res1.status, "ACK_PROCESSED")
        audit_count_before = AuditLog.objects.filter(command_id="CMD-DUP-ACK").count()

        # Second ACK: detected as duplicate, safe no-op
        res2 = ControllerService.handle_controller_ack(
            command_id="CMD-DUP-ACK",
            reported_actual_state=SignalColor.YELLOW,
        )
        self.assertTrue(res2.success)
        self.assertEqual(res2.status, "DUPLICATE_ACK")
        self.assertTrue(res2.is_duplicate)

        # Crucial check: Duplicate ACK did NOT generate duplicate audit events or state transitions
        audit_count_after = AuditLog.objects.filter(command_id="CMD-DUP-ACK").count()
        self.assertEqual(audit_count_before, audit_count_after)

    # 5. Unknown Command
    def test_unknown_command(self):
        res = ControllerService.handle_controller_ack(
            command_id="CMD-GHOST-999",
            reported_actual_state=SignalColor.GREEN,
        )
        self.assertFalse(res.success)
        self.assertEqual(res.status, "UNKNOWN_COMMAND")
        self.assertIn("unknown", res.message.lower())

    # 6. Timeout
    def test_timeout(self):
        # Create a command sent 10 seconds ago (configured timeout is 5 seconds)
        ten_seconds_ago = timezone.now() - timedelta(seconds=10)
        cmd = ControllerCommand.objects.create(
            command_id="CMD-TIMEOUT-01",
            junction=self.junction,
            direction=Direction.EAST.value,
            requested_state=SignalColor.GREEN.value,
            status=CommandStatus.PENDING,
            sent_at=ten_seconds_ago,
        )

        timed_out = ControllerService.check_command_timeouts()
        self.assertEqual(len(timed_out), 1)

        cmd.refresh_from_db()
        self.assertEqual(cmd.status, CommandStatus.TIMEOUT)

        # Crucial safety invariant: System did NOT assume EAST became GREEN!
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.actual_east, SignalColor.RED.value)

        # Junction enters DEGRADED state
        self.assertEqual(self.junction.controller_status, ControllerStatus.DEGRADED)
        self.assertEqual(self.junction.mode, JunctionMode.DEGRADED)

        # Audit log created
        audit = AuditLog.objects.filter(
            command_id="CMD-TIMEOUT-01",
            event_type=AuditEventType.CONTROLLER_TIMEOUT,
        ).first()
        self.assertIsNotNone(audit)

    # 7. Controller Offline
    def test_controller_offline(self):
        # Simulator reports OFFLINE
        self.simulator.set_behavior_mode("A", SimulatorBehaviorMode.OFFLINE)

        cmd = ControllerService.dispatch_signal_command(
            junction=self.junction,
            direction=Direction.WEST,
            requested_state=SignalColor.GREEN,
            port=self.simulator,
            custom_command_id="CMD-OFFLINE-01",
        )

        self.assertEqual(cmd.status, CommandStatus.FAILED)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.controller_status, ControllerStatus.OFFLINE)
        self.assertEqual(self.junction.mode, JunctionMode.DEGRADED)

        # Physical state NOT treated as confirmed
        self.assertEqual(self.junction.actual_west, SignalColor.RED.value)

    # 8. Desired vs Actual Mismatch
    def test_desired_actual_mismatch(self):
        # Simulator injects mismatch (reports RED when GREEN requested)
        self.simulator.set_behavior_mode("A", SimulatorBehaviorMode.MISMATCH)

        # Dispatch command requesting GREEN
        self.simulator.set_behavior_mode("A", SimulatorBehaviorMode.DELAYED_ACK)
        cmd = ControllerService.dispatch_signal_command(
            junction=self.junction,
            direction=Direction.NORTH,
            requested_state=SignalColor.GREEN,
            port=self.simulator,
            custom_command_id="CMD-MISMATCH-01",
        )

        # Controller acknowledges with unexpected RED
        ack_res = ControllerService.handle_controller_ack(
            command_id="CMD-MISMATCH-01",
            reported_actual_state=SignalColor.RED,  # Mismatch!
        )

        self.assertTrue(ack_res.success)
        self.assertEqual(ack_res.status, "MISMATCH")
        self.assertTrue(ack_res.is_mismatch)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.desired_north, SignalColor.GREEN.value)
        self.assertEqual(self.junction.actual_north, SignalColor.RED.value)
        self.assertEqual(self.junction.controller_status, ControllerStatus.WARNING)
        self.assertFalse(self.junction.is_synchronized)

    # 9. Restart Recovery
    def test_restart_pending_command_recovery(self):
        # Simulate server crash: A command was left in PENDING status
        crash_time = timezone.now() - timedelta(seconds=20)
        ControllerCommand.objects.create(
            command_id="CMD-CRASH-STRANDED",
            junction=self.junction,
            direction=Direction.EAST.value,
            requested_state=SignalColor.GREEN.value,
            status=CommandStatus.PENDING,
            sent_at=crash_time,
        )

        # Server boots up and runs startup recovery
        report = ControllerService.recover_pending_commands_on_startup()

        self.assertEqual(report.recovered_commands_count, 1)
        self.assertIn("A", report.affected_junction_ids)

        cmd = ControllerCommand.objects.get(command_id="CMD-CRASH-STRANDED")
        self.assertEqual(cmd.status, CommandStatus.TIMEOUT)
        self.assertIn("restarted", cmd.error_message)

        # Affected junction status set to UNKNOWN and DEGRADED
        self.junction.refresh_from_db()
        self.assertEqual(self.junction.controller_status, ControllerStatus.UNKNOWN)
        self.assertEqual(self.junction.mode, JunctionMode.DEGRADED)

        # Physical signals NOT assumed green
        self.assertEqual(self.junction.actual_east, SignalColor.RED.value)
