"""
Tests for Factory Traffic Management System REST API.
Verifies all 8 required endpoints, HTTP status codes, validation errors,
idempotency responses, error handling, and audit history.
"""

from rest_framework import status
from rest_framework.test import APITestCase
from django.utils import timezone

from traffic.constants import (
    AuditEventType,
    CommandStatus,
    Direction,
    JunctionMode,
    SignalColor,
    TrafficPhase,
    VehicleType,
)
from traffic.models import AuditLog, ControllerCommand, Junction, QueueEntry


class TrafficAPITests(APITestCase):
    def setUp(self):
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

    # 1. GET /api/junctions
    def test_list_junctions(self):
        res = self.client.get("/api/junctions")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data, list)
        self.assertGreaterEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], "A")

    # 2. POST /api/junctions (Create Junction)
    def test_create_junction_success(self):
        payload = {
            "id": "C",
            "name": "Junction C - South Gate",
            "yellow_duration_sec": 4,
            "all_red_duration_sec": 2,
            "min_green_sec": 12,
            "max_green_sec": 50,
        }
        res = self.client.post("/api/junctions", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["id"], "C")
        self.assertTrue(Junction.objects.filter(id="C").exists())

    def test_create_duplicate_junction_conflict(self):
        payload = {
            "id": "A",  # Already exists
            "name": "Duplicate Junction A",
        }
        res = self.client.post("/api/junctions", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    # 3. GET /api/junctions/{id}
    def test_get_junction_detail(self):
        res = self.client.get("/api/junctions/A")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], "A")
        self.assertEqual(res.data["name"], "Junction A - Main Plant")

    def test_get_junction_not_found(self):
        res = self.client.get("/api/junctions/Z_UNKNOWN")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # 4. POST /api/sensor-events
    def test_submit_sensor_arrival_event(self):
        payload = {
            "event_id": "EVT_API_001",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "TRUCK",
            "vehicle_id": "TRK-101",
            "sequence_no": 1,
            "timestamp": timezone.now().isoformat(),
        }
        res = self.client.post("/api/sensor-events", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(res.data["success"])
        self.assertEqual(res.data["queue_counts"]["NORTH"], 1)

    def test_submit_duplicate_sensor_event(self):
        payload = {
            "event_id": "EVT_DUP_001",
            "junction_id": "A",
            "direction": "EAST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_type": "EMPLOYEE_VEHICLE",
            "vehicle_id": "EMP-99",
            "sequence_no": 1,
            "timestamp": timezone.now().isoformat(),
        }
        # First submission
        res1 = self.client.post("/api/sensor-events", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_202_ACCEPTED)

        # Duplicate submission -> 200 OK with duplicate flag
        res2 = self.client.post("/api/sensor-events", payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertTrue(res2.data["is_duplicate"])
        self.assertIn("already", res2.data["message"].lower())

    def test_submit_invalid_sensor_event(self):
        # Missing vehicle_type on arrival
        payload = {
            "event_id": "EVT_INVALID_API",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
        }
        res = self.client.post("/api/sensor-events", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # 5. GET /api/junctions/{id}/status
    def test_get_junction_status(self):
        res = self.client.get("/api/junctions/A/status")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        self.assertEqual(data["junction_id"], "A")
        self.assertIn("mode", data)
        self.assertIn("phase", data)
        self.assertIn("controller_status", data)
        self.assertIn("desired_signals", data)
        self.assertIn("actual_signals", data)
        self.assertIn("queues", data)
        self.assertIn("emergency", data)
        self.assertIn("manual_override", data)
        self.assertIn("alerts", data)

    # 6. POST /api/junctions/{id}/commands (Manual Override)
    def test_manual_green_command(self):
        payload = {
            "command": "MANUAL_GREEN_REQUEST",
            "direction": "EAST",
            "admin_id": "lead_supervisor",
        }
        res = self.client.post("/api/junctions/A/commands", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.mode, JunctionMode.MANUAL)
        self.assertEqual(self.junction.manual_override_direction, Direction.EAST.value)

    def test_return_to_automatic_command(self):
        # First set manual
        self.junction.mode = JunctionMode.MANUAL
        self.junction.manual_override_direction = Direction.EAST.value
        self.junction.save()

        payload = {
            "command": "RETURN_TO_AUTOMATIC",
            "admin_id": "lead_supervisor",
        }
        res = self.client.post("/api/junctions/A/commands", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.mode, JunctionMode.AUTOMATIC)
        self.assertIsNone(self.junction.manual_override_direction)

    # 7. POST /api/controller-events
    def test_controller_ack_event(self):
        # Create a pending command
        cmd = ControllerCommand.objects.create(
            command_id="CMD-API-ACK-01",
            junction=self.junction,
            direction=Direction.NORTH.value,
            requested_state=SignalColor.GREEN.value,
            status=CommandStatus.PENDING,
        )

        payload = {
            "junction_id": "A",
            "command_id": "CMD-API-ACK-01",
            "status": "ACK",
            "actual_state": "GREEN",
        }
        res = self.client.post("/api/controller-events", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["success"])

        cmd.refresh_from_db()
        self.assertEqual(cmd.status, CommandStatus.ACKNOWLEDGED)

    def test_controller_offline_event(self):
        payload = {
            "junction_id": "A",
            "status": "OFFLINE",
        }
        res = self.client.post("/api/controller-events", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.junction.refresh_from_db()
        self.assertEqual(self.junction.controller_status, "OFFLINE")
        self.assertEqual(self.junction.mode, JunctionMode.DEGRADED)

    # 8. GET /api/junctions/{id}/history
    def test_get_junction_history(self):
        # Insert audit log entries
        AuditLog.objects.create(
            junction=self.junction,
            event_type=AuditEventType.VEHICLE_ARRIVED,
            direction="NORTH",
            details="Test arrival audit entry.",
        )
        AuditLog.objects.create(
            junction=self.junction,
            event_type=AuditEventType.SIGNAL_CONFIRMED,
            direction="NORTH",
            details="Test signal confirmed audit entry.",
        )

        res = self.client.get("/api/junctions/A/history?limit=10")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data, list)
        self.assertGreaterEqual(len(res.data), 2)
        self.assertEqual(res.data[0]["junction_id"], "A")
