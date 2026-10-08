"""
Domain Constants and TextChoices for Factory Traffic Management System.
Extracted into a standalone module so that the pure Python domain engine
and Django models can share choices without tight coupling.
"""

from django.db import models


class Direction(models.TextChoices):
    NORTH = 'NORTH', 'North'
    SOUTH = 'SOUTH', 'South'
    EAST = 'EAST', 'East'
    WEST = 'WEST', 'West'


class SignalColor(models.TextChoices):
    RED = 'RED', 'Red'
    YELLOW = 'YELLOW', 'Yellow'
    GREEN = 'GREEN', 'Green'


class TrafficPhase(models.TextChoices):
    NORTH_SOUTH = 'NORTH_SOUTH', 'North-South'
    EAST_WEST = 'EAST_WEST', 'East-West'
    ALL_RED = 'ALL_RED', 'All-Red Clearance'


class TransitionStage(models.TextChoices):
    NONE = 'NONE', 'None'
    YELLOW = 'YELLOW', 'Yellow Clearance'
    ALL_RED = 'ALL_RED', 'All-Red Buffer'


class JunctionMode(models.TextChoices):
    AUTOMATIC = 'AUTOMATIC', 'Automatic Scheduling'
    MANUAL = 'MANUAL', 'Manual Override'
    EMERGENCY = 'EMERGENCY', 'Emergency Preemption'
    FAILURE = 'FAILURE', 'Controller Failure'
    DEGRADED = 'DEGRADED', 'Degraded / Device Failure'


class QueueEntryStatus(models.TextChoices):
    WAITING = 'WAITING', 'Waiting in Queue'
    CLEARED = 'CLEARED', 'Cleared / Departed'


class ControllerStatus(models.TextChoices):
    ONLINE = 'ONLINE', 'Online'
    OFFLINE = 'OFFLINE', 'Offline'
    DEGRADED = 'DEGRADED', 'Degraded'
    WARNING = 'WARNING', 'Warning'
    UNKNOWN = 'UNKNOWN', 'Unknown'


class VehicleType(models.TextChoices):
    EMERGENCY = 'EMERGENCY', 'Emergency Vehicle (Priority 1)'
    TRUCK = 'TRUCK', 'Delivery Truck (Priority 2)'
    FORKLIFT = 'FORKLIFT', 'Forklift (Priority 3)'
    EMPLOYEE_VEHICLE = 'EMPLOYEE_VEHICLE', 'Employee Vehicle (Priority 4)'


class SensorEventType(models.TextChoices):
    VEHICLE_ARRIVED = 'VEHICLE_ARRIVED', 'Vehicle Arrived'
    VEHICLE_CLEARED = 'VEHICLE_CLEARED', 'Vehicle Cleared'


class CommandStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Controller ACK'
    ACK = 'ACK', 'Acknowledged'
    ACKNOWLEDGED = 'ACKNOWLEDGED', 'Acknowledged'
    TIMEOUT = 'TIMEOUT', 'Timed Out'
    FAILED = 'FAILED', 'Failed / Rejected'


class DeviceType(models.TextChoices):
    SIGNAL_CONTROLLER = 'SIGNAL_CONTROLLER', 'Signal Controller'
    VEHICLE_SENSOR = 'VEHICLE_SENSOR', 'Vehicle Sensor'


class AuditEventType(models.TextChoices):
    VEHICLE_DETECTED = 'VEHICLE_DETECTED', 'Vehicle Detected'
    VEHICLE_ARRIVED = 'VEHICLE_ARRIVED', 'Vehicle Arrived'
    VEHICLE_CLEARED = 'VEHICLE_CLEARED', 'Vehicle Cleared'
    DUPLICATE_EVENT = 'DUPLICATE_EVENT', 'Duplicate Event Ignored'
    DUPLICATE_REJECTED = 'DUPLICATE_REJECTED', 'Duplicate Sensor Event Rejected'
    REJECTED_EVENT = 'REJECTED_EVENT', 'Invalid or Rejected Event'
    PHASE_SELECTED = 'PHASE_SELECTED', 'Phase Selected by Scheduler'
    SIGNAL_TRANSITION_STARTED = 'SIGNAL_TRANSITION_STARTED', 'Signal Transition Started'
    SIGNAL_CHANGED = 'SIGNAL_CHANGED', 'Signal Changed'
    SIGNAL_CONFIRMED = 'SIGNAL_CONFIRMED', 'Signal Confirmed by Controller'
    EMERGENCY_DETECTED = 'EMERGENCY_DETECTED', 'Emergency Vehicle Detected'
    EMERGENCY_CLEARED = 'EMERGENCY_CLEARED', 'Emergency Vehicle Cleared'
    MANUAL_OVERRIDE = 'MANUAL_OVERRIDE', 'Manual Override Requested'
    RETURN_TO_AUTOMATIC = 'RETURN_TO_AUTOMATIC', 'Returned to Automatic'
    CONTROLLER_ACK = 'CONTROLLER_ACK', 'Controller Acknowledged Command'
    CONTROLLER_TIMEOUT = 'CONTROLLER_TIMEOUT', 'Controller Timed Out'
    DEVICE_FAILURE = 'DEVICE_FAILURE', 'Device / Controller Failure'
    MODE_CHANGED = 'MODE_CHANGED', 'Operating Mode Changed'
    MODE_CHANGE = 'MODE_CHANGE', 'Operating Mode Changed'
