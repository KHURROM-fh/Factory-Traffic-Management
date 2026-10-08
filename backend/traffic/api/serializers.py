"""
Serializers for the Factory Traffic Management REST API.
Handles request validation and response formatting.
Business logic is strictly decoupled and delegated to application services.
"""

from rest_framework import serializers
from traffic.constants import (
    CommandStatus,
    ControllerStatus,
    Direction,
    JunctionMode,
    SensorEventType,
    SignalColor,
    TrafficPhase,
    VehicleType,
)
from traffic.models import AuditLog, ControllerCommand, Junction, QueueEntry


class JunctionSerializer(serializers.ModelSerializer):
    """Serializer for Junction configuration and summary."""
    class Meta:
        model = Junction
        fields = [
            "id",
            "name",
            "description",
            "mode",
            "current_phase",
            "transition_stage",
            "controller_status",
            "yellow_duration_sec",
            "all_red_duration_sec",
            "min_green_sec",
            "max_green_sec",
            "controller_timeout_sec",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_id(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Junction ID cannot be empty.")
        return value.strip().upper()


class SensorEventSerializer(serializers.Serializer):
    """Validates incoming vehicle detection events."""
    event_id = serializers.CharField(max_length=64, required=True)
    junction_id = serializers.CharField(max_length=32, required=True)
    direction = serializers.ChoiceField(choices=Direction.choices, required=True)
    event_type = serializers.ChoiceField(choices=SensorEventType.choices, required=True)
    vehicle_type = serializers.ChoiceField(choices=VehicleType.choices, required=False, allow_null=True)
    vehicle_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    sequence_no = serializers.IntegerField(min_value=0, default=0, required=False)
    timestamp = serializers.DateTimeField(required=False)

    def validate(self, data):
        event_type = data.get("event_type")
        vehicle_type = data.get("vehicle_type")

        # Arrival events must include a vehicle type
        if event_type == SensorEventType.VEHICLE_ARRIVED and not vehicle_type:
            raise serializers.ValidationError({
                "vehicle_type": "vehicle_type is required for VEHICLE_ARRIVED events."
            })

        return data


class ManualCommandSerializer(serializers.Serializer):
    """Validates manual operator commands."""
    command = serializers.ChoiceField(
        choices=["MANUAL_GREEN_REQUEST", "RETURN_TO_AUTOMATIC", "EMERGENCY_CLEAR"],
        required=True,
    )
    direction = serializers.ChoiceField(
        choices=Direction.choices,
        required=False,
        allow_null=True,
    )
    admin_id = serializers.CharField(max_length=64, required=False, default="operator")

    def validate(self, data):
        command = data.get("command")
        direction = data.get("direction")

        if command == "MANUAL_GREEN_REQUEST" and not direction:
            raise serializers.ValidationError({
                "direction": "direction is required when requesting MANUAL_GREEN_REQUEST."
            })

        return data


class ControllerEventSerializer(serializers.Serializer):
    """Validates controller acknowledgement and telemetry events."""
    junction_id = serializers.CharField(max_length=32, required=True)
    command_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    direction = serializers.ChoiceField(choices=Direction.choices, required=False, allow_null=True)
    status = serializers.CharField(max_length=30, required=False, default="ACK")
    actual_state = serializers.ChoiceField(choices=SignalColor.choices, required=False, allow_null=True)
    device_type = serializers.CharField(max_length=40, required=False, default="SIGNAL_CONTROLLER")
    timestamp = serializers.DateTimeField(required=False)


class QueuedVehicleSerializer(serializers.Serializer):
    """Serializer for individual queued vehicle display."""
    vehicle_id = serializers.CharField()
    vehicle_type = serializers.CharField()
    direction = serializers.CharField()
    sequence_no = serializers.IntegerField()
    timestamp = serializers.CharField()
    waiting_seconds = serializers.FloatField()


class AuditLogSerializer(serializers.ModelSerializer):
    """Serializer for immutable audit history logs."""
    timestamp = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%S.%fZ")

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "junction_id",
            "event_type",
            "direction",
            "previous_state",
            "new_state",
            "command_id",
            "vehicle_id",
            "vehicle_type",
            "details",
            "timestamp",
        ]
