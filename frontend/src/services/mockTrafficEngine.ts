/**
 * Standalone Client-Side Traffic Simulation Engine
 * Implements the deterministic state machine, vehicle queuing, priority scoring,
 * emergency preemption, manual override, and controller ACK tracking.
 *
 * This allows the dashboard to function 100% interactively both with a real backend
 * and in standalone evaluation mode when the backend is offline.
 */

import {
  JunctionStatus,
  SensorEventPayload,
  ManualCommandPayload,
  ControllerEventPayload,
  AuditHistoryEvent,
  Direction,
  SignalColor,
  QueuedVehicle,
  AlertItem,
} from '@/types/traffic';

interface JunctionInternalState {
  status: JunctionStatus;
  history: AuditHistoryEvent[];
  processedEventIds: Set<string>;
  lastSequenceByDirection: Record<Direction, number>;
  timerRemaining: number; // in seconds
  transitionTargetPhase: 'NORTH_SOUTH' | 'EAST_WEST' | null;
  transitionStep: 'NONE' | 'YELLOW' | 'ALL_RED';
}

// Initial state for Junction A
function createInitialJunctionState(id: string, name: string): JunctionInternalState {
  return {
    status: {
      junction_id: id,
      name,
      mode: 'AUTOMATIC',
      phase: 'NORTH_SOUTH',
      controller_status: 'ONLINE',
      desired_signals: {
        NORTH: 'GREEN',
        SOUTH: 'GREEN',
        EAST: 'RED',
        WEST: 'RED',
      },
      actual_signals: {
        NORTH: 'GREEN',
        SOUTH: 'GREEN',
        EAST: 'RED',
        WEST: 'RED',
      },
      queues: {
        NORTH: 0,
        SOUTH: 0,
        EAST: 0,
        WEST: 0,
      },
      pending_command: null,
      emergency: null,
      manual_override: null,
      queue_details: [],
      alerts: [],
      last_updated: new Date().toISOString(),
    },
    history: [],
    processedEventIds: new Set([]),
    lastSequenceByDirection: {
      NORTH: 0,
      SOUTH: 0,
      EAST: 0,
      WEST: 0,
    },
    timerRemaining: 30,
    transitionTargetPhase: null,
    transitionStep: 'NONE',
  };
}

class TrafficSimulationStore {
  private junctions: Map<string, JunctionInternalState> = new Map();
  private commandCounter = 9000;
  private timerInterval: NodeJS.Timeout | null = null;

  constructor() {
    this.reset();
    this.startTicker();
  }

  public reset() {
    this.junctions.clear();
    this.junctions.set('A', createInitialJunctionState('A', 'Junction A - Main Plant'));
    this.junctions.set('B', createInitialJunctionState('B', 'Junction B - Warehouse Gate'));
    this.junctions.set('C', createInitialJunctionState('C', 'Junction C - Loading Dock'));
  }

  private startTicker() {
    if (typeof window === 'undefined') return;
    if (this.timerInterval) clearInterval(this.timerInterval);

    this.timerInterval = setInterval(() => {
      this.tick();
    }, 1000);
  }

  // Per-second state machine transition tick
  private tick() {
    for (const [id, j] of this.junctions.entries()) {
      // Update waiting times
      if (j.status.queue_details) {
        j.status.queue_details.forEach((v) => {
          v.waiting_seconds += 1;
        });
      }

      // Check if degraded controller
      if (j.status.controller_status === 'OFFLINE') {
        // Safe mode or pause
        continue;
      }

      // If transition in progress
      if (j.transitionStep === 'YELLOW') {
        j.timerRemaining -= 1;
        if (j.timerRemaining <= 0) {
          // Yellow done -> ALL RED clearance (approx 3s)
          j.transitionStep = 'ALL_RED';
          j.timerRemaining = 3;
          j.status.phase = 'ALL_RED';
          j.status.desired_signals = { NORTH: 'RED', SOUTH: 'RED', EAST: 'RED', WEST: 'RED' };
          j.status.actual_signals = { NORTH: 'RED', SOUTH: 'RED', EAST: 'RED', WEST: 'RED' };

          this.logHistory(id, {
            event_type: 'SIGNAL_CHANGED',
            details: 'Entered ALL_RED clearance interval between conflicting phases',
          });
        }
      } else if (j.transitionStep === 'ALL_RED') {
        j.timerRemaining -= 1;
        if (j.timerRemaining <= 0) {
          // ALL RED done -> Activate target phase GREEN
          const target = j.transitionTargetPhase || (j.status.phase === 'ALL_RED' ? 'EAST_WEST' : 'NORTH_SOUTH');
          j.transitionStep = 'NONE';
          j.transitionTargetPhase = null;
          j.status.phase = target;

          const cmdId = this.nextCommandId();
          if (target === 'NORTH_SOUTH') {
            j.status.desired_signals = { NORTH: 'GREEN', SOUTH: 'GREEN', EAST: 'RED', WEST: 'RED' };
            j.status.actual_signals = { NORTH: 'GREEN', SOUTH: 'GREEN', EAST: 'RED', WEST: 'RED' };
          } else {
            j.status.desired_signals = { NORTH: 'RED', SOUTH: 'RED', EAST: 'GREEN', WEST: 'GREEN' };
            j.status.actual_signals = { NORTH: 'RED', SOUTH: 'RED', EAST: 'GREEN', WEST: 'GREEN' };
          }

          j.timerRemaining = 30; // standard green cycle
          j.status.pending_command = null;

          this.logHistory(id, {
            event_type: 'SIGNAL_CHANGED',
            command_id: cmdId,
            details: `Transition complete. ${target} phase is now GREEN`,
          });

          // Check if emergency vehicle cleared upon getting green
          if (j.status.emergency && j.status.emergency.active) {
            const eDir = j.status.emergency.direction;
            if (
              (target === 'NORTH_SOUTH' && (eDir === 'NORTH' || eDir === 'SOUTH')) ||
              (target === 'EAST_WEST' && (eDir === 'EAST' || eDir === 'WEST'))
            ) {
              j.status.emergency.preemption_stage = 'GREEN_GRANTED';
            }
          }
        }
      } else {
        // Normal green countdown in AUTOMATIC mode
        if (j.status.mode === 'AUTOMATIC') {
          j.timerRemaining -= 1;
          if (j.timerRemaining <= 0) {
            // Check queues to see if switch is needed
            const nextPhase = j.status.phase === 'NORTH_SOUTH' ? 'EAST_WEST' : 'NORTH_SOUTH';
            this.initiateSafeTransition(id, nextPhase, 'Normal 30s cycle expired');
          }
        }
      }

      j.status.last_updated = new Date().toISOString();
    }
  }

  // Safe transition state machine: GREEN -> YELLOW (5s) -> ALL_RED (3s) -> TARGET GREEN (30s)
  public initiateSafeTransition(junctionId: string, targetPhase: 'NORTH_SOUTH' | 'EAST_WEST', reason: string) {
    const j = this.junctions.get(junctionId);
    if (!j) return;

    if (j.status.phase === targetPhase && j.transitionStep === 'NONE') {
      return; // already active
    }

    const currentPhase = j.status.phase;
    j.transitionTargetPhase = targetPhase;
    j.transitionStep = 'YELLOW';
    j.timerRemaining = 5; // 5s yellow

    const cmdId = this.nextCommandId();
    j.status.pending_command = {
      command_id: cmdId,
      junction_id: junctionId,
      direction: currentPhase === 'NORTH_SOUTH' ? 'NORTH' : 'EAST',
      requested_state: 'YELLOW',
      sent_at: new Date().toISOString(),
      status: 'PENDING',
    };

    if (currentPhase === 'NORTH_SOUTH') {
      j.status.desired_signals.NORTH = 'YELLOW';
      j.status.desired_signals.SOUTH = 'YELLOW';
      j.status.actual_signals.NORTH = 'YELLOW';
      j.status.actual_signals.SOUTH = 'YELLOW';
    } else if (currentPhase === 'EAST_WEST') {
      j.status.desired_signals.EAST = 'YELLOW';
      j.status.desired_signals.WEST = 'YELLOW';
      j.status.actual_signals.EAST = 'YELLOW';
      j.status.actual_signals.WEST = 'YELLOW';
    }

    this.logHistory(junctionId, {
      event_type: 'SIGNAL_TRANSITION_STARTED',
      command_id: cmdId,
      details: `Initiating safe phase transition from ${currentPhase} to ${targetPhase}: YELLOW clearance started (${reason})`,
    });
  }

  // GET /api/junctions
  public getJunctions() {
    return Array.from(this.junctions.entries()).map(([id, j]) => ({
      id,
      name: j.status.name || `Junction ${id}`,
      mode: j.status.mode,
      phase: j.status.phase,
      controller_status: j.status.controller_status,
      total_queued: Object.values(j.status.queues).reduce((a, b) => a + b, 0),
    }));
  }

  // GET /api/junctions/:id/status
  public getJunctionStatus(junctionId: string): JunctionStatus | null {
    const j = this.junctions.get(junctionId);
    return j ? { ...j.status } : null;
  }

  // POST /api/sensor-events
  public handleSensorEvent(payload: SensorEventPayload): { success: boolean; message: string; duplicate?: boolean } {
    const j = this.junctions.get(payload.junction_id);
    if (!j) {
      return { success: false, message: `Unknown junction ID: ${payload.junction_id}` };
    }

    // 1. Idempotency Check: Reject duplicate event_id
    if (j.processedEventIds.has(payload.event_id)) {
      this.logHistory(payload.junction_id, {
        event_type: 'DUPLICATE_REJECTED',
        vehicle_id: payload.vehicle_id,
        direction: payload.direction,
        details: `Rejected duplicate sensor event: event_id ${payload.event_id} has already been processed`,
      });
      return {
        success: true,
        message: `Duplicate event ${payload.event_id} ignored idempotently`,
        duplicate: true,
      };
    }
    j.processedEventIds.add(payload.event_id);

    // 2. Out-of-order check
    const lastSeq = j.lastSequenceByDirection[payload.direction] || 0;
    if (payload.sequence_no < lastSeq) {
      this.logHistory(payload.junction_id, {
        event_type: 'DUPLICATE_REJECTED',
        direction: payload.direction,
        details: `Out-of-order sequence detected on ${payload.direction}: got seq ${payload.sequence_no}, expected >= ${lastSeq}`,
      });
    }
    j.lastSequenceByDirection[payload.direction] = Math.max(lastSeq, payload.sequence_no);

    // 3. Handle VEHICLE_ARRIVED vs VEHICLE_CLEARED
    if (payload.event_type === 'VEHICLE_ARRIVED') {
      j.status.queues[payload.direction] += 1;

      // Add to queue details
      if (!j.status.queue_details) j.status.queue_details = [];
      j.status.queue_details.push({
        vehicle_id: payload.vehicle_id,
        vehicle_type: payload.vehicle_type,
        direction: payload.direction,
        sequence_no: payload.sequence_no,
        timestamp: payload.timestamp || new Date().toISOString(),
        waiting_seconds: 0,
      });

      this.logHistory(payload.junction_id, {
        event_type: 'VEHICLE_ARRIVED',
        direction: payload.direction,
        vehicle_id: payload.vehicle_id,
        vehicle_type: payload.vehicle_type,
        details: `${payload.vehicle_type} ${payload.vehicle_id} arrived at ${payload.direction} (Queue: ${j.status.queues[payload.direction]})`,
      });

      // Emergency preemption check
      if (payload.vehicle_type === 'EMERGENCY') {
        j.status.mode = 'EMERGENCY';
        j.status.emergency = {
          active: true,
          direction: payload.direction,
          vehicle_id: payload.vehicle_id,
          detected_at: new Date().toISOString(),
          preemption_stage: 'DETECTED',
        };

        const targetPhase = payload.direction === 'NORTH' || payload.direction === 'SOUTH' ? 'NORTH_SOUTH' : 'EAST_WEST';

        this.logHistory(payload.junction_id, {
          event_type: 'EMERGENCY_DETECTED',
          direction: payload.direction,
          vehicle_id: payload.vehicle_id,
          details: `EMERGENCY PREEMPTION TRIGGERED: ${payload.vehicle_id} approaching from ${payload.direction}. Preempting towards ${targetPhase}`,
        });

        if (j.status.phase !== targetPhase) {
          this.initiateSafeTransition(payload.junction_id, targetPhase, `Emergency preemption for ${payload.vehicle_id}`);
        }
      }
    } else if (payload.event_type === 'VEHICLE_CLEARED') {
      // Decrement queue, preventing negative
      j.status.queues[payload.direction] = Math.max(0, j.status.queues[payload.direction] - 1);

      // Remove from queue_details
      if (j.status.queue_details) {
        const idx = j.status.queue_details.findIndex(
          (v) => v.vehicle_id === payload.vehicle_id || v.direction === payload.direction
        );
        if (idx !== -1) {
          j.status.queue_details.splice(idx, 1);
        }
      }

      this.logHistory(payload.junction_id, {
        event_type: 'VEHICLE_CLEARED',
        direction: payload.direction,
        vehicle_id: payload.vehicle_id,
        details: `Vehicle ${payload.vehicle_id} cleared from ${payload.direction} queue (Remaining: ${j.status.queues[payload.direction]})`,
      });

      // If cleared emergency vehicle
      if (j.status.emergency && j.status.emergency.vehicle_id === payload.vehicle_id) {
        j.status.emergency = null;
        if (j.status.mode === 'EMERGENCY') {
          j.status.mode = 'AUTOMATIC';
        }
        this.logHistory(payload.junction_id, {
          event_type: 'EMERGENCY_CLEARED',
          direction: payload.direction,
          details: `Emergency vehicle ${payload.vehicle_id} cleared. Returned junction to AUTOMATIC mode`,
        });
      }
    }

    j.status.last_updated = new Date().toISOString();
    return { success: true, message: `Sensor event ${payload.event_id} processed` };
  }

  // POST /api/junctions/:id/commands
  public handleManualCommand(junctionId: string, cmd: ManualCommandPayload): { success: boolean; message: string } {
    const j = this.junctions.get(junctionId);
    if (!j) return { success: false, message: `Unknown junction: ${junctionId}` };

    if (cmd.command === 'MANUAL_GREEN_REQUEST') {
      if (!cmd.direction) {
        return { success: false, message: 'Direction is required for MANUAL_GREEN_REQUEST' };
      }

      const targetPhase = cmd.direction === 'NORTH' || cmd.direction === 'SOUTH' ? 'NORTH_SOUTH' : 'EAST_WEST';
      j.status.mode = 'MANUAL';
      j.status.manual_override = {
        active: true,
        direction: cmd.direction,
        requested_by: cmd.admin_id || 'Factory_Supervisor_1',
        requested_at: new Date().toISOString(),
      };

      this.logHistory(junctionId, {
        event_type: 'MANUAL_OVERRIDE',
        direction: cmd.direction,
        details: `Manual green requested for ${cmd.direction} by administrator. Routing via safe transition to ${targetPhase}`,
      });

      if (j.status.phase !== targetPhase) {
        this.initiateSafeTransition(junctionId, targetPhase, `Manual override request for ${cmd.direction}`);
      } else {
        // Extend green
        j.timerRemaining = 45;
      }

      return { success: true, message: `Manual green requested for ${cmd.direction}` };
    } else if (cmd.command === 'RETURN_TO_AUTOMATIC') {
      j.status.mode = 'AUTOMATIC';
      j.status.manual_override = null;

      this.logHistory(junctionId, {
        event_type: 'RETURN_TO_AUTOMATIC',
        details: 'Manual override released by administrator. Junction returned to AUTOMATIC scheduling',
      });

      return { success: true, message: 'Junction returned to AUTOMATIC mode' };
    } else if (cmd.command === 'EMERGENCY_CLEAR') {
      j.status.emergency = null;
      if (j.status.mode === 'EMERGENCY') {
        j.status.mode = 'AUTOMATIC';
      }
      this.logHistory(junctionId, {
        event_type: 'EMERGENCY_CLEARED',
        details: 'Emergency state cleared manually by administrator',
      });
      return { success: true, message: 'Emergency state cleared' };
    }

    return { success: false, message: `Unknown command: ${cmd.command}` };
  }

  // POST /api/controller-events
  public handleControllerEvent(payload: ControllerEventPayload): { success: boolean; message: string } {
    const j = this.junctions.get(payload.junction_id);
    if (!j) return { success: false, message: `Unknown junction: ${payload.junction_id}` };

    if (payload.status === 'OFFLINE' || payload.status === 'ONLINE' || payload.status === 'DEGRADED') {
      j.status.controller_status = payload.status;
      this.logHistory(payload.junction_id, {
        event_type: 'DEVICE_FAILURE',
        details: `Signal controller device reported status: ${payload.status}`,
      });
      if (payload.status === 'OFFLINE') {
        j.status.mode = 'FAILURE';
        this.addAlert(payload.junction_id, 'ERROR', 'Signal controller offline! Traffic safety transition halted.');
      }
      return { success: true, message: `Controller status set to ${payload.status}` };
    }

    if (payload.command_id && payload.status === 'ACK') {
      if (j.status.pending_command && j.status.pending_command.command_id === payload.command_id) {
        j.status.pending_command.status = 'ACKNOWLEDGED';
      }
      if (payload.actual_state && payload.direction) {
        j.status.actual_signals[payload.direction] = payload.actual_state;
      }

      this.logHistory(payload.junction_id, {
        event_type: 'CONTROLLER_ACK',
        command_id: payload.command_id,
        direction: payload.direction,
        details: `Controller ACK received for command ${payload.command_id}. Confirmed actual state: ${payload.actual_state || 'OK'}`,
      });

      return { success: true, message: `ACK processed for command ${payload.command_id}` };
    }

    if (payload.status === 'TIMEOUT') {
      this.logHistory(payload.junction_id, {
        event_type: 'CONTROLLER_TIMEOUT',
        command_id: payload.command_id,
        details: `Command ${payload.command_id} timed out awaiting physical controller acknowledgement`,
      });
      this.addAlert(payload.junction_id, 'WARNING', `Controller command timeout: ${payload.command_id}`);
      return { success: true, message: 'Controller timeout recorded' };
    }

    return { success: true, message: 'Controller event recorded' };
  }

  // GET /api/junctions/:id/history
  public getHistory(junctionId: string, limit = 50): AuditHistoryEvent[] {
    const j = this.junctions.get(junctionId);
    if (!j) return [];
    return [...j.history].reverse().slice(0, limit);
  }

  private addAlert(junctionId: string, level: 'INFO' | 'WARNING' | 'ERROR', message: string) {
    const j = this.junctions.get(junctionId);
    if (!j) return;
    if (!j.status.alerts) j.status.alerts = [];
    j.status.alerts.unshift({
      id: `alt-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      level,
      message,
      timestamp: new Date().toISOString(),
    });
    // keep latest 5
    j.status.alerts = j.status.alerts.slice(0, 5);
  }

  private logHistory(junctionId: string, event: Partial<AuditHistoryEvent>) {
    const j = this.junctions.get(junctionId);
    if (!j) return;
    const historyItem: AuditHistoryEvent = {
      id: `hist-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      junction_id: junctionId,
      event_type: event.event_type || 'SIGNAL_CHANGED',
      direction: event.direction,
      previous_state: event.previous_state,
      new_state: event.new_state,
      command_id: event.command_id,
      vehicle_id: event.vehicle_id,
      vehicle_type: event.vehicle_type,
      details: event.details || 'Event logged',
      timestamp: new Date().toISOString(),
    };
    j.history.push(historyItem);
  }

  private nextCommandId(): string {
    this.commandCounter += 1;
    return `cmd-${this.commandCounter}`;
  }
}

// Singleton simulation instance
export const mockTrafficEngine = new TrafficSimulationStore();
