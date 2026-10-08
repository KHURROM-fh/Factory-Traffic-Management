"""
Django Admin configuration for Factory Traffic Management System.
Provides clean administrative inspection for Junctions, Events, Queues,
Commands, Telemetry, and Audit History.
"""

from django.contrib import admin
from traffic.models import (
    AuditLog,
    ControllerCommand,
    DeviceStatusLog,
    Junction,
    ProcessedEvent,
    QueueEntry,
)


@admin.register(Junction)
class JunctionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "mode",
        "current_phase",
        "transition_stage",
        "controller_status",
        "is_synchronized_display",
        "queue_summary",
        "updated_at",
    )
    list_filter = ("mode", "current_phase", "controller_status")
    search_fields = ("id", "name", "description")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Identification", {
            "fields": ("id", "name", "description")
        }),
        ("Operating State", {
            "fields": (
                "mode",
                "current_phase",
                "transition_stage",
                "last_phase_change_at",
                "emergency_direction",
                "emergency_vehicle_id",
                "manual_override_direction",
                "manual_override_by",
                "manual_override_at",
            )
        }),
        ("Desired Signals (Commanded)", {
            "fields": ("desired_north", "desired_south", "desired_east", "desired_west")
        }),
        ("Actual Signals (Confirmed)", {
            "fields": ("actual_north", "actual_south", "actual_east", "actual_west")
        }),
        ("Directional Queues", {
            "fields": ("queue_count_north", "queue_count_south", "queue_count_east", "queue_count_west")
        }),
        ("Timing & Safety Configurations", {
            "fields": (
                "yellow_duration_sec",
                "all_red_duration_sec",
                "min_green_sec",
                "max_green_sec",
                "controller_timeout_sec",
            )
        }),
        ("Controller Telemetry", {
            "fields": ("controller_status", "last_controller_heartbeat_at", "created_at", "updated_at")
        }),
    )

    @admin.display(description="Synchronized", boolean=True)
    def is_synchronized_display(self, obj):
        return obj.is_synchronized

    @admin.display(description="Queues (N/S/E/W)")
    def queue_summary(self, obj):
        return f"N:{obj.queue_count_north} S:{obj.queue_count_south} E:{obj.queue_count_east} W:{obj.queue_count_west}"


@admin.register(ProcessedEvent)
class ProcessedEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_id",
        "junction",
        "direction",
        "event_type",
        "vehicle_type",
        "vehicle_id",
        "sequence_no",
        "timestamp",
        "received_at",
    )
    list_filter = ("event_type", "direction", "vehicle_type", "junction")
    search_fields = ("event_id", "vehicle_id")
    readonly_fields = ("event_id", "received_at", "timestamp", "raw_payload")


@admin.register(QueueEntry)
class QueueEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "vehicle_id",
        "vehicle_type",
        "junction",
        "direction",
        "status",
        "sequence_no",
        "arrived_at",
        "cleared_at",
    )
    list_filter = ("status", "direction", "vehicle_type", "junction")
    search_fields = ("vehicle_id",)
    readonly_fields = ("arrived_at",)


@admin.register(ControllerCommand)
class ControllerCommandAdmin(admin.ModelAdmin):
    list_display = (
        "command_id",
        "junction",
        "direction",
        "requested_state",
        "actual_state",
        "status",
        "retry_count",
        "sent_at",
        "acknowledged_at",
    )
    list_filter = ("status", "requested_state", "direction", "junction")
    search_fields = ("command_id",)
    readonly_fields = ("sent_at", "acknowledged_at")


@admin.register(DeviceStatusLog)
class DeviceStatusLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "junction",
        "device_type",
        "device_identifier",
        "status",
        "is_healthy",
        "recorded_at",
    )
    list_filter = ("device_type", "status", "is_healthy", "junction")
    search_fields = ("device_identifier", "details")
    readonly_fields = ("recorded_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "timestamp",
        "junction",
        "event_type",
        "direction",
        "command_id",
        "vehicle_id",
        "details_snippet",
    )
    list_filter = ("event_type", "direction", "junction")
    search_fields = ("command_id", "vehicle_id", "details")
    readonly_fields = ("timestamp",)

    @admin.display(description="Details")
    def details_snippet(self, obj):
        return obj.details[:60] + "..." if len(obj.details) > 60 else obj.details
