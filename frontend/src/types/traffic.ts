/**
 * Traffic Control Domain & API Types
 * Based on Factory Traffic Management System Assessment V2 specification
 */

export type Direction = 'NORTH' | 'SOUTH' | 'EAST' | 'WEST';

export type SignalColor = 'RED' | 'YELLOW' | 'GREEN';

export type TrafficPhase = 'NORTH_SOUTH' | 'EAST_WEST' | 'ALL_RED';

export type JunctionMode = 'AUTOMATIC' | 'MANUAL' | 'EMERGENCY' | 'FAILURE';

export type ControllerStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED' | 'WARNING' | 'UNKNOWN';

export type VehicleType = 'EMERGENCY' | 'TRUCK' | 'FORKLIFT' | 'EMPLOYEE_VEHICLE';

export type SensorEventType = 'VEHICLE_ARRIVED' | 'VEHICLE_CLEARED';

export type ControllerAckStatus = 'ACK' | 'NACK' | 'TIMEOUT';

export interface SignalStateMap {
  NORTH: SignalColor;
  SOUTH: SignalColor;
  EAST: SignalColor;
  WEST: SignalColor;
}

export interface QueueCountMap {
  NORTH: number;
  SOUTH: number;
  EAST: number;
  WEST: number;
}

export interface QueuedVehicle {
  vehicle_id: string;
  vehicle_type: VehicleType;
  direction: Direction;
  sequence_no: number;
  timestamp: string; // ISO string
  waiting_seconds: number;
}

export interface PendingCommand {
  command_id: string;
  junction_id: string;
  direction: Direction;
  requested_state: SignalColor;
  sent_at: string;
  status: 'PENDING' | 'ACKNOWLEDGED' | 'TIMED_OUT' | 'FAILED';
  retry_count?: number;
}

export interface EmergencyState {
  active: boolean;
  direction?: Direction;
  vehicle_id?: string;
  detected_at?: string;
  preemption_stage?: 'DETECTED' | 'TRANSITIONING_YELLOW' | 'ALL_RED_CLEARANCE' | 'GREEN_GRANTED';
}

export interface ManualOverrideState {
  active: boolean;
  direction?: Direction;
  requested_by?: string;
  requested_at?: string;
  expires_at?: string;
}

export interface AlertItem {
  id: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  message: string;
  timestamp: string;
  source?: string;
}

export interface JunctionStatus {
  junction_id: string;
  name?: string;
  mode: JunctionMode;
  phase: TrafficPhase;
  controller_status: ControllerStatus;
  desired_signals: SignalStateMap;
  actual_signals: SignalStateMap;
  queues: QueueCountMap;
  pending_command: PendingCommand | null;
  emergency: EmergencyState | null;
  manual_override: ManualOverrideState | null;
  queue_details?: QueuedVehicle[];
  alerts?: AlertItem[];
  last_updated?: string;
}

export interface JunctionSummary {
  id: string;
  name: string;
  description: string;
  status: JunctionStatus;
}

// Sensor Event Payload (Section 4 & 10.2)
export interface SensorEventPayload {
  event_id: string;
  junction_id: string;
  direction: Direction;
  event_type: SensorEventType;
  vehicle_id: string;
  vehicle_type: VehicleType;
  sequence_no: number;
  timestamp: string;
}

// Manual Command Payload (Section 8 & 10.4)
export interface ManualCommandPayload {
  command: 'MANUAL_GREEN_REQUEST' | 'RETURN_TO_AUTOMATIC' | 'EMERGENCY_CLEAR';
  direction?: Direction;
  admin_id?: string;
}

// Controller Event / Ack Payload (Section 9 & 10.5)
export interface ControllerEventPayload {
  command_id?: string;
  event_id?: string;
  junction_id: string;
  direction?: Direction;
  status?: ControllerAckStatus | ControllerStatus;
  actual_state?: SignalColor;
  device_type?: 'SIGNAL_CONTROLLER' | 'VEHICLE_SENSOR';
  timestamp?: string;
}

// Audit / History Event Item (Section 11 & 10.6)
export interface AuditHistoryEvent {
  id: string;
  junction_id: string;
  event_type:
    | 'VEHICLE_ARRIVED'
    | 'VEHICLE_CLEARED'
    | 'DUPLICATE_REJECTED'
    | 'SIGNAL_TRANSITION_STARTED'
    | 'SIGNAL_CHANGED'
    | 'SIGNAL_CONFIRMED'
    | 'EMERGENCY_DETECTED'
    | 'EMERGENCY_CLEARED'
    | 'MANUAL_OVERRIDE'
    | 'RETURN_TO_AUTOMATIC'
    | 'CONTROLLER_ACK'
    | 'CONTROLLER_TIMEOUT'
    | 'DEVICE_FAILURE'
    | 'MODE_CHANGE';
  direction?: Direction;
  previous_state?: SignalColor;
  new_state?: SignalColor;
  command_id?: string;
  vehicle_id?: string;
  vehicle_type?: VehicleType;
  details?: string;
  timestamp: string;
}
