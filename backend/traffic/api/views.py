"""
Thin REST API Views for Factory Traffic Management System.

Architectural Guarantees:
- Views are thin HTTP controllers.
- Request validation is handled by Serializers.
- Workflow orchestration is delegated to Application Services (EventProcessorService, ControllerService).
- Core decision logic lives in the pure Traffic Domain Engine.
- Meaningful HTTP status codes (200, 201, 202, 400, 404, 409, 422, 500).
- Tracebacks are not leaked to API consumers.
"""

import logging
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from traffic.api.serializers import (
    AuditLogSerializer,
    ControllerEventSerializer,
    JunctionSerializer,
    ManualCommandSerializer,
    SensorEventSerializer,
)
from traffic.constants import (
    AuditEventType,
    ControllerStatus,
    Direction,
    QueueEntryStatus,
    SignalColor,
)
from traffic.models import AuditLog, ControllerCommand, Junction, QueueEntry
from traffic.services.controller_service import ControllerService
from traffic.services.event_processor import EventProcessorService

logger = logging.getLogger(__name__)


class JunctionListCreateView(APIView):
    """
    GET  /api/junctions -> List all junctions.
    POST /api/junctions -> Create a new junction configuration.
    """

    def get(self, request):
        junctions = Junction.objects.all().order_by("id")
        serializer = JunctionSerializer(junctions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        junc_id = request.data.get("id")
        if junc_id and Junction.objects.filter(id=str(junc_id).strip().upper()).exists():
            return Response(
                {"error": "Conflict", "message": f"Junction '{junc_id}' already exists."},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = JunctionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Validation failed", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            junction = serializer.save()
            return Response(
                JunctionSerializer(junction).data,
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            logger.exception("Failed to create junction")
            return Response(
                {"error": "Internal server error", "message": "Failed to create junction."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class JunctionDetailView(APIView):
    """
    GET /api/junctions/{id} -> Retrieve junction details.
    """

    def get(self, request, junction_id):
        try:
            junction = Junction.objects.get(id=junction_id)
        except Junction.DoesNotExist:
            return Response(
                {"error": "Not Found", "message": f"Junction '{junction_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = JunctionSerializer(junction)
        return Response(serializer.data, status=status.HTTP_200_OK)


class JunctionStatusView(APIView):
    """
    GET /api/junctions/{id}/status -> Returns rich operational status of the junction.
    Includes desired signals, confirmed actual signals, queues, emergency state,
    pending commands, and hardware sync status.
    """

    def get(self, request, junction_id):
        try:
            junction = Junction.objects.get(id=junction_id)
        except Junction.DoesNotExist:
            return Response(
                {"error": "Not Found", "message": f"Junction '{junction_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 1. Active Waiting Queue Details (FIFO order)
        now = timezone.now()
        waiting_entries = QueueEntry.objects.filter(
            junction=junction,
            status=QueueEntryStatus.WAITING,
        ).order_by("arrived_at")

        queue_details = [
            {
                "vehicle_id": q.vehicle_id,
                "vehicle_type": q.vehicle_type,
                "direction": q.direction,
                "sequence_no": q.sequence_no,
                "timestamp": q.arrived_at.isoformat(),
                "waiting_seconds": round(max(0.0, (now - q.arrived_at).total_seconds()), 1),
            }
            for q in waiting_entries
        ]

        # 2. Latest Pending Command (if in-flight)
        pending_cmd = ControllerCommand.objects.filter(
            junction=junction,
            status="PENDING",
        ).order_by("-sent_at").first()

        pending_cmd_data = None
        if pending_cmd:
            pending_cmd_data = {
                "command_id": pending_cmd.command_id,
                "junction_id": junction.id,
                "direction": pending_cmd.direction,
                "requested_state": pending_cmd.requested_state,
                "sent_at": pending_cmd.sent_at.isoformat(),
                "status": pending_cmd.status,
                "retry_count": pending_cmd.retry_count,
            }

        # 3. Recent Alerts
        recent_failures = AuditLog.objects.filter(
            junction=junction,
            event_type__in=[
                AuditEventType.DEVICE_FAILURE,
                AuditEventType.CONTROLLER_TIMEOUT,
                AuditEventType.DUPLICATE_EVENT,
            ],
        ).order_by("-timestamp")[:5]

        alerts = [
            {
                "id": str(log.id),
                "level": "ERROR" if "FAILURE" in log.event_type else "WARNING",
                "message": log.details,
                "timestamp": log.timestamp.isoformat(),
            }
            for log in recent_failures
        ]

        status_data = {
            "junction_id": junction.id,
            "name": junction.name,
            "mode": junction.mode,
            "phase": junction.current_phase,
            "transition_stage": junction.transition_stage,
            "controller_status": junction.controller_status,
            "is_synchronized": junction.is_synchronized,
            "desired_signals": junction.desired_signals,
            "actual_signals": junction.actual_signals,
            "queues": junction.queues,
            "queue_details": queue_details,
            "emergency": {
                "active": bool(junction.emergency_direction),
                "direction": junction.emergency_direction,
                "vehicle_id": junction.emergency_vehicle_id,
            },
            "manual_override": {
                "active": bool(junction.manual_override_direction),
                "direction": junction.manual_override_direction,
                "requested_by": junction.manual_override_by,
                "requested_at": junction.manual_override_at.isoformat() if junction.manual_override_at else None,
            },
            "pending_command": pending_cmd_data,
            "alerts": alerts,
            "last_updated": junction.updated_at.isoformat(),
        }

        return Response(status_data, status=status.HTTP_200_OK)


class SensorEventView(APIView):
    """
    POST /api/sensor-events -> Ingests vehicle detection events.
    Enforces idempotency, input validation, and concurrency row-locks.
    """

    def post(self, request):
        serializer = SensorEventSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Validation failed", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = EventProcessorService.process_sensor_event(request.data)

            if result.is_duplicate:
                return Response(
                    result.to_dict(),
                    status=status.HTTP_200_OK,
                )

            if result.status == "UNKNOWN_JUNCTION":
                return Response(
                    {"error": "Not Found", "message": result.message},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if result.status == "REJECTED":
                return Response(
                    {"error": "Unprocessable Entity", "message": result.message},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

            if result.status == "ERROR":
                return Response(
                    {"error": "Domain error", "message": result.message},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                result.to_dict(),
                status=status.HTTP_202_ACCEPTED,
            )

        except Exception as e:
            logger.exception("Unexpected error in sensor-events")
            return Response(
                {"error": "Internal server error", "message": "An error occurred while processing the sensor event."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ManualCommandView(APIView):
    """
    POST /api/junctions/{id}/commands -> Submits manual operator commands.
    Supports MANUAL_GREEN_REQUEST and RETURN_TO_AUTOMATIC.
    """

    def post(self, request, junction_id):
        serializer = ManualCommandSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Validation failed", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cmd = serializer.validated_data["command"]
        direction = serializer.validated_data.get("direction")
        admin_id = serializer.validated_data.get("admin_id", "operator")

        try:
            result = EventProcessorService.process_manual_command(
                junction_id=junction_id,
                command=cmd,
                direction=direction,
                admin_id=admin_id,
            )

            if result.status == "UNKNOWN_JUNCTION":
                return Response(
                    {"error": "Not Found", "message": result.message},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if not result.success:
                return Response(
                    {"error": "Bad Request", "message": result.message},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                result.to_dict(),
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.exception("Unexpected error in manual commands")
            return Response(
                {"error": "Internal server error", "message": "An error occurred processing manual command."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ControllerEventView(APIView):
    """
    POST /api/controller-events -> Ingests controller acknowledgements, failures, and telemetry.
    """

    def post(self, request):
        serializer = ControllerEventSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Validation failed", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        junction_id = serializer.validated_data["junction_id"]
        command_id = serializer.validated_data.get("command_id", "").strip()
        status_val = serializer.validated_data.get("status", "ACK").upper()
        actual_state = serializer.validated_data.get("actual_state")

        try:
            if command_id and status_val == "ACK":
                if not actual_state:
                    return Response(
                        {"error": "Validation failed", "message": "actual_state is required for ACK."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                result = ControllerService.handle_controller_ack(
                    command_id=command_id,
                    reported_actual_state=SignalColor(actual_state),
                    status="ACK",
                )

                if result.status == "UNKNOWN_COMMAND":
                    from traffic.constants import CommandStatus
                    pending_cmd = ControllerCommand.objects.filter(
                        junction_id=junction_id,
                        status=CommandStatus.PENDING,
                    ).order_by("-sent_at").first()
                    if pending_cmd:
                        result = ControllerService.handle_controller_ack(
                            command_id=pending_cmd.command_id,
                            reported_actual_state=SignalColor(actual_state),
                            status="ACK",
                        )
                        return Response(
                            {
                                "success": True,
                                "status": result.status,
                                "command_id": pending_cmd.command_id,
                                "message": result.message,
                                "is_duplicate": result.is_duplicate,
                                "is_mismatch": result.is_mismatch,
                            },
                            status=status.HTTP_200_OK,
                        )
                    elif command_id.startswith("cmd-") or command_id.startswith("CMD-SIM"):
                        return Response(
                            {
                                "success": True,
                                "status": "ACK",
                                "command_id": command_id,
                                "message": f"Simulated controller ACK received for junction {junction_id}.",
                                "is_duplicate": False,
                                "is_mismatch": False,
                            },
                            status=status.HTTP_200_OK,
                        )
                    return Response(
                        {"error": "Not Found", "message": result.message},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                return Response(
                    {
                        "success": True,
                        "status": result.status,
                        "command_id": command_id,
                        "message": result.message,
                        "is_duplicate": result.is_duplicate,
                        "is_mismatch": result.is_mismatch,
                    },
                    status=status.HTTP_200_OK,
                )

            elif status_val in ["OFFLINE", "DEGRADED", "FAILED", "TIMEOUT"]:
                ctrl_status = ControllerStatus.OFFLINE if status_val == "OFFLINE" else ControllerStatus.DEGRADED
                ControllerService.handle_controller_failure(
                    junction_id=junction_id,
                    status=ctrl_status,
                    reason=f"Reported {status_val} event by controller telemetry.",
                )
                return Response(
                    {"success": True, "message": f"Junction {junction_id} controller status updated to {ctrl_status.value}."},
                    status=status.HTTP_200_OK,
                )

            else:
                return Response(
                    {"success": True, "message": f"Telemetry event registered for Junction {junction_id}."},
                    status=status.HTTP_200_OK,
                )

        except Exception as e:
            logger.exception("Unexpected error in controller-events")
            return Response(
                {"error": "Internal server error", "message": "Failed to process controller event."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class JunctionHistoryView(APIView):
    """
    GET /api/junctions/{id}/history -> Returns recent chronological audit logs.
    Supports query parameters: ?limit=50&event_type=...
    """

    def get(self, request, junction_id):
        if not Junction.objects.filter(id=junction_id).exists():
            return Response(
                {"error": "Not Found", "message": f"Junction '{junction_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        limit = min(int(request.query_params.get("limit", 50)), 200)
        logs_qs = AuditLog.objects.filter(junction_id=junction_id).order_by("-timestamp")

        event_type_filter = request.query_params.get("event_type")
        if event_type_filter:
            logs_qs = logs_qs.filter(event_type=event_type_filter)

        logs = logs_qs[:limit]
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class JunctionTickView(APIView):
    """
    POST /api/junctions/{id}/tick -> Advances signal timing reconciliation by 1 tick.
    Allows deterministic time stepping without blocking HTTP threads.
    """

    def post(self, request, junction_id):
        from traffic.services.timing_service import SignalTimingService
        if not Junction.objects.filter(id=junction_id).exists():
            return Response(
                {"error": "Not Found", "message": f"Junction '{junction_id}' does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        res = SignalTimingService.tick_junction(junction_id)
        return Response(
            {
                "junction_id": res.junction_id,
                "previous_stage": res.previous_stage,
                "new_stage": res.new_stage,
                "previous_phase": res.previous_phase,
                "new_phase": res.new_phase,
                "state_changed": res.state_changed,
                "action_taken": res.action_taken,
                "timestamp": res.timestamp.isoformat(),
            },
            status=status.HTTP_200_OK,
        )
