"""
Core Domain Models for Factory Traffic Management System.

Architectural Guarantees:
1. No traffic scheduling logic inside model save() methods.
2. No hidden side effects or business logic in signals.py.
3. Separation of Desired (Commanded) and Actual (Confirmed) signal states.
4. Non-negative queue enforcement via PostgreSQL CheckConstraints and FIFO tracking.
5. Strict idempotency on sensor events via primary key constraints.
6. Full multi-junction support (Junction A, B, C...) without hardcoded identifiers.
"""

from django.db import models
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
    TransitionStage,
    VehicleType,
)


class Junction(models.Model):
    """
    Represents an intersection / traffic control node within the factory.
    Configurable for Junction A, B, C, D... Supports all 4 approaches (NORTH, SOUTH, EAST, WEST).
    
    Persists:
    - Junction configuration (timings, safety bounds)
    - Current operating mode & phase
    - Desired signal states (what the algorithm has commanded)
    - Actual signal states (what the hardware has acknowledged/confirmed)
    - Active emergency & manual override state
    - Directional non-negative queue counters
    - Controller health status
    """
    id = models.CharField(
        max_length=32,
        primary_key=True,
        help_text="Unique junction identifier, e.g., 'A', 'B', 'MAIN_GATE'"
    )
    name = models.CharField(
        max_length=100,
        help_text="Human-readable name, e.g., 'Junction A - Main Plant'"
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Location details or description within the facility"
    )

    # ---------------------------------------------------------
    # Safety & Timing Configuration (Tunable per junction)
    # ---------------------------------------------------------
    yellow_duration_sec = models.PositiveIntegerField(
        default=3,
        help_text="Duration in seconds for yellow clearance phase"
    )
    all_red_duration_sec = models.PositiveIntegerField(
        default=2,
        help_text="Duration in seconds for all-red clearance interval before conflicting green"
    )
    min_green_sec = models.PositiveIntegerField(
        default=10,
        help_text="Minimum green duration before phase switch allowed"
    )
    max_green_sec = models.PositiveIntegerField(
        default=60,
        help_text="Maximum green duration before forced phase switch (starvation limit)"
    )
    controller_timeout_sec = models.PositiveIntegerField(
        default=5,
        help_text="Seconds to wait for controller ACK before flagging timeout/failure"
    )

    # ---------------------------------------------------------
    # Current Operating State
    # ---------------------------------------------------------
    mode = models.CharField(
        max_length=20,
        choices=JunctionMode.choices,
        default=JunctionMode.AUTOMATIC,
        help_text="Current operating mode (AUTOMATIC, MANUAL, EMERGENCY, FAILURE, DEGRADED)"
    )
    current_phase = models.CharField(
        max_length=20,
        choices=TrafficPhase.choices,
        default=TrafficPhase.NORTH_SOUTH,
        help_text="Active traffic phase (NORTH_SOUTH, EAST_WEST, ALL_RED)"
    )
    target_phase = models.CharField(
        max_length=20,
        choices=TrafficPhase.choices,
        default=TrafficPhase.NORTH_SOUTH,
        help_text="Target green phase for in-flight transitions"
    )
    transition_stage = models.CharField(
        max_length=20,
        choices=TransitionStage.choices,
        default=TransitionStage.NONE,
        help_text="Intermediate transition stage (NONE, YELLOW, ALL_RED)"
    )
    last_phase_change_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp when the phase or transition stage last changed"
    )

    # ---------------------------------------------------------
    # Emergency Preemption State
    # ---------------------------------------------------------
    emergency_direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        null=True,
        blank=True,
        help_text="Direction demanding emergency green preemption"
    )
    emergency_vehicle_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="ID of the emergency vehicle causing preemption"
    )

    # ---------------------------------------------------------
    # Manual Override State
    # ---------------------------------------------------------
    manual_override_direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        null=True,
        blank=True,
        help_text="Direction granted manual override green"
    )
    manual_override_by = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Admin or operator ID who triggered manual override"
    )
    manual_override_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when manual override was activated"
    )

    # ---------------------------------------------------------
    # Desired Signal States (Commanded by Traffic Brain)
    # ---------------------------------------------------------
    desired_north = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.GREEN
    )
    desired_south = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.GREEN
    )
    desired_east = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.RED
    )
    desired_west = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.RED
    )

    # ---------------------------------------------------------
    # Actual Confirmed Signal States (Reported by Hardware Controller)
    # ---------------------------------------------------------
    actual_north = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.GREEN
    )
    actual_south = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.GREEN
    )
    actual_east = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.RED
    )
    actual_west = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        default=SignalColor.RED
    )

    # ---------------------------------------------------------
    # Directional Queue Counters (Non-negative Enforced by DB Constraints)
    # ---------------------------------------------------------
    queue_count_north = models.PositiveIntegerField(
        default=0,
        help_text="Number of waiting vehicles in North queue (>= 0)"
    )
    queue_count_south = models.PositiveIntegerField(
        default=0,
        help_text="Number of waiting vehicles in South queue (>= 0)"
    )
    queue_count_east = models.PositiveIntegerField(
        default=0,
        help_text="Number of waiting vehicles in East queue (>= 0)"
    )
    queue_count_west = models.PositiveIntegerField(
        default=0,
        help_text="Number of waiting vehicles in West queue (>= 0)"
    )

    # ---------------------------------------------------------
    # Controller Connectivity & Health
    # ---------------------------------------------------------
    controller_status = models.CharField(
        max_length=20,
        choices=ControllerStatus.choices,
        default=ControllerStatus.ONLINE,
        help_text="Communication health with local junction hardware"
    )
    last_controller_heartbeat_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last successful ping or telemetry received from controller"
    )

    # ---------------------------------------------------------
    # Audit Timestamps
    # ---------------------------------------------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "traffic_junction"
        verbose_name = "Junction"
        verbose_name_plural = "Junctions"
        indexes = [
            models.Index(fields=["mode", "controller_status"], name="idx_junc_mode_ctrl"),
            models.Index(fields=["current_phase"], name="idx_junc_phase"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(queue_count_north__gte=0),
                name="chk_junc_queue_north_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(queue_count_south__gte=0),
                name="chk_junc_queue_south_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(queue_count_east__gte=0),
                name="chk_junc_queue_east_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(queue_count_west__gte=0),
                name="chk_junc_queue_west_non_negative"
            ),
        ]

    def __str__(self):
        return f"Junction {self.id} ({self.name}) - {self.mode}/{self.current_phase}"

    @property
    def desired_signals(self) -> dict:
        return {
            Direction.NORTH: self.desired_north,
            Direction.SOUTH: self.desired_south,
            Direction.EAST: self.desired_east,
            Direction.WEST: self.desired_west,
        }

    @property
    def actual_signals(self) -> dict:
        return {
            Direction.NORTH: self.actual_north,
            Direction.SOUTH: self.actual_south,
            Direction.EAST: self.actual_east,
            Direction.WEST: self.actual_west,
        }

    @property
    def queues(self) -> dict:
        return {
            Direction.NORTH: self.queue_count_north,
            Direction.SOUTH: self.queue_count_south,
            Direction.EAST: self.queue_count_east,
            Direction.WEST: self.queue_count_west,
        }

    @property
    def is_synchronized(self) -> bool:
        """True if all actual signals match desired signals."""
        return (
            self.desired_north == self.actual_north
            and self.desired_south == self.actual_south
            and self.desired_east == self.actual_east
            and self.desired_west == self.actual_west
        )


class ProcessedEvent(models.Model):
    """
    Stores incoming sensor detection events.
    Enforces strict idempotency on event_id. If an event_id is re-submitted,
    the database rejects duplicate insertion.
    
    Persists:
    - Sensor event ID (unique PK)
    - Junction & Direction
    - Event type (VEHICLE_ARRIVED, VEHICLE_CLEARED)
    - Vehicle type (EMERGENCY, TRUCK, FORKLIFT, EMPLOYEE_VEHICLE)
    - Sequence number
    - Sensor timestamp & System received timestamp
    - Raw payload JSON
    """
    event_id = models.CharField(
        max_length=64,
        primary_key=True,
        help_text="Idempotent unique sensor event identifier"
    )
    junction = models.ForeignKey(
        Junction,
        on_delete=models.CASCADE,
        related_name="traffic_events",
        help_text="Junction where sensor detected this event"
    )
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        help_text="Approach direction (NORTH, SOUTH, EAST, WEST)"
    )
    event_type = models.CharField(
        max_length=30,
        choices=SensorEventType.choices,
        help_text="Sensor event type (VEHICLE_ARRIVED, VEHICLE_CLEARED)"
    )
    vehicle_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Vehicle identifier if known (e.g., 'TRK-01', 'AMB-99')"
    )
    vehicle_type = models.CharField(
        max_length=30,
        choices=VehicleType.choices,
        blank=True,
        default="",
        help_text="Validated vehicle classification"
    )
    sequence_no = models.PositiveIntegerField(
        default=0,
        help_text="Sensor sequence number for ordering / packet loss tracking"
    )
    timestamp = models.DateTimeField(
        help_text="Timestamp reported by sensor hardware"
    )
    received_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when backend received and recorded the event"
    )
    raw_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Original raw payload for auditability and diagnostic replay"
    )

    class Meta:
        db_table = "traffic_processed_event"
        verbose_name = "Processed Event"
        verbose_name_plural = "Processed Events"
        indexes = [
            models.Index(fields=["junction", "-timestamp"], name="idx_evt_junc_time"),
            models.Index(fields=["junction", "direction", "event_type"], name="idx_evt_junc_dir_type"),
        ]

    def __str__(self):
        return f"{self.event_id}: {self.event_type} at {self.junction_id}/{self.direction}"


class QueueEntry(models.Model):
    """
    Represents an individual vehicle currently or previously waiting in an approach queue.
    Provides fine-grained FIFO tracking, priority queue sorting, and starvation metrics.
    
    Persists:
    - Junction & Direction
    - Vehicle ID & validated VehicleType
    - Queue position sequence
    - Arrival timestamp & Clearance timestamp
    - Status (WAITING, CLEARED)
    """
    id = models.BigAutoField(primary_key=True)
    junction = models.ForeignKey(
        Junction,
        on_delete=models.CASCADE,
        related_name="queue_entries",
        help_text="Junction where vehicle is queued"
    )
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        help_text="Queue direction (NORTH, SOUTH, EAST, WEST)"
    )
    vehicle_id = models.CharField(
        max_length=64,
        help_text="Vehicle identifier (e.g., 'TRK-01', 'FL-03')"
    )
    vehicle_type = models.CharField(
        max_length=30,
        choices=VehicleType.choices,
        help_text="Validated vehicle priority category"
    )
    sequence_no = models.PositiveIntegerField(
        default=0,
        help_text="Arrival sequence order"
    )
    status = models.CharField(
        max_length=20,
        choices=QueueEntryStatus.choices,
        default=QueueEntryStatus.WAITING,
        help_text="WAITING in queue or CLEARED through intersection"
    )
    arrived_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp of vehicle arrival"
    )
    cleared_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when vehicle departed / cleared the queue"
    )

    class Meta:
        db_table = "traffic_queue_entry"
        verbose_name = "Queue Entry"
        verbose_name_plural = "Queue Entries"
        indexes = [
            models.Index(fields=["junction", "direction", "status", "arrived_at"], name="idx_q_junc_dir_stat_arr"),
            models.Index(fields=["junction", "status"], name="idx_q_junc_stat"),
            models.Index(fields=["vehicle_id"], name="idx_q_vehicle_id"),
        ]

    def __str__(self):
        return f"{self.vehicle_id} ({self.vehicle_type}) at {self.junction_id}/{self.direction} [{self.status}]"


class ControllerCommand(models.Model):
    """
    Tracks commands dispatched to the physical or simulated signal controller.
    Ensures commands are idempotent, auditable, and tracked until acknowledged or timed out.
    
    Persists:
    - Unique command_id
    - Target junction & direction
    - Desired/requested signal state
    - Confirmed/actual signal state upon ACK
    - Command lifecycle status (PENDING, ACK, TIMEOUT, FAILED)
    - Timestamps: sent_at, acknowledged_at
    - Retry count & diagnostic error message
    """
    command_id = models.CharField(
        max_length=64,
        primary_key=True,
        help_text="Unique idempotent command identifier (e.g., 'CMD-A-101')"
    )
    junction = models.ForeignKey(
        Junction,
        on_delete=models.CASCADE,
        related_name="commands",
        help_text="Target junction for this command"
    )
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        help_text="Approach direction receiving signal command"
    )
    requested_state = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        help_text="Desired signal state commanded by traffic controller"
    )
    actual_state = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        null=True,
        blank=True,
        help_text="Actual signal state reported by controller in acknowledgement"
    )
    status = models.CharField(
        max_length=20,
        choices=CommandStatus.choices,
        default=CommandStatus.PENDING,
        help_text="Command lifecycle status (PENDING, ACK, TIMEOUT, FAILED)"
    )
    retry_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of retry attempts sent"
    )
    sent_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp when command was transmitted to controller"
    )
    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when controller confirmed execution"
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Diagnostic reason if command timed out or failed"
    )

    class Meta:
        db_table = "traffic_controller_command"
        verbose_name = "Controller Command"
        verbose_name_plural = "Controller Commands"
        indexes = [
            models.Index(fields=["junction", "status", "-sent_at"], name="idx_cmd_junc_stat_sent"),
            models.Index(fields=["command_id"], name="idx_cmd_id"),
        ]

    def __str__(self):
        return f"{self.command_id} -> {self.junction_id}/{self.direction}={self.requested_state} [{self.status}]"


class DeviceStatusLog(models.Model):
    """
    Logs hardware telemetry, heartbeat, and health transitions for IoT devices
    (signal controllers and vehicle presence sensors).
    
    Persists:
    - Junction FK
    - Device type (SIGNAL_CONTROLLER, VEHICLE_SENSOR)
    - Device identifier (e.g., 'CTRL-JUNCTION-A', 'SENS-NORTH')
    - Status (ONLINE, OFFLINE, DEGRADED, WARNING, UNKNOWN)
    - Health boolean
    - Diagnostic details
    - Recorded timestamp
    """
    junction = models.ForeignKey(
        Junction,
        on_delete=models.CASCADE,
        related_name="device_status_logs",
        help_text="Junction associated with the hardware device"
    )
    device_type = models.CharField(
        max_length=30,
        choices=DeviceType.choices,
        help_text="Hardware device category"
    )
    device_identifier = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Hardware MAC, serial number, or device tag"
    )
    status = models.CharField(
        max_length=20,
        choices=ControllerStatus.choices,
        help_text="Reported hardware status"
    )
    is_healthy = models.BooleanField(
        default=True,
        help_text="Boolean flag for quick health aggregation"
    )
    details = models.TextField(
        blank=True,
        default="",
        help_text="Diagnostic message, error code, or telemetry metadata"
    )
    recorded_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp when device status was logged"
    )

    class Meta:
        db_table = "traffic_device_status_log"
        verbose_name = "Device Status Log"
        verbose_name_plural = "Device Status Logs"
        indexes = [
            models.Index(fields=["junction", "device_type", "-recorded_at"], name="idx_dev_junc_type_rec"),
        ]

    def __str__(self):
        return f"{self.device_type} ({self.device_identifier}) @ {self.junction_id}: {self.status}"


class AuditLog(models.Model):
    """
    Append-only historical audit trail of all significant traffic management events.
    Captures state transitions, arrivals, clearances, emergency preemption,
    manual overrides, controller acknowledgements, and failure fail-safes.
    
    Persists:
    - Junction FK
    - Event type (AuditEventType choices)
    - Direction (if directional)
    - Previous and new signal state (if signal change)
    - Related command_id, vehicle_id, vehicle_type
    - Contextual explanation details
    - Timestamp
    """
    junction = models.ForeignKey(
        Junction,
        on_delete=models.CASCADE,
        related_name="audit_logs",
        help_text="Junction where the audited event occurred"
    )
    event_type = models.CharField(
        max_length=40,
        choices=AuditEventType.choices,
        help_text="Classified audit event type"
    )
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        null=True,
        blank=True,
        help_text="Direction related to the event, if applicable"
    )
    previous_state = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        null=True,
        blank=True,
        help_text="Previous signal state if an aspect changed"
    )
    new_state = models.CharField(
        max_length=10,
        choices=SignalColor.choices,
        null=True,
        blank=True,
        help_text="New signal state if an aspect changed"
    )
    command_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Associated controller command ID if applicable"
    )
    vehicle_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Associated vehicle ID if applicable"
    )
    vehicle_type = models.CharField(
        max_length=30,
        choices=VehicleType.choices,
        blank=True,
        default="",
        help_text="Associated vehicle type if applicable"
    )
    details = models.TextField(
        blank=True,
        default="",
        help_text="Human-readable description or diagnostic context"
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp when the event occurred"
    )

    class Meta:
        db_table = "traffic_audit_log"
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["junction", "-timestamp"], name="idx_audit_junc_time"),
            models.Index(fields=["event_type", "-timestamp"], name="idx_audit_type_time"),
            models.Index(fields=["command_id"], name="idx_audit_cmd_id"),
        ]

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {self.junction_id}: {self.event_type} - {self.details[:50]}"
