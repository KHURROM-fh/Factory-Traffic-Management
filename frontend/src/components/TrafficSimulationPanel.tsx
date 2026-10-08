'use client';

import React, { useState } from 'react';
import {
  Direction,
  VehicleType,
  SensorEventPayload,
  ControllerEventPayload,
} from '@/types/traffic';

interface TrafficSimulationPanelProps {
  junctionId: string;
  pendingCommandId?: string;
  onSubmitSensorEvent: (payload: SensorEventPayload) => Promise<{ success: boolean; message: string; duplicate?: boolean }>;
  onSubmitControllerEvent: (payload: ControllerEventPayload) => Promise<{ success: boolean; message: string }>;
  onExecuteScenario: (scenarioNumber: number) => Promise<string>;
}

export const TrafficSimulationPanel: React.FC<TrafficSimulationPanelProps> = ({
  junctionId,
  pendingCommandId,
  onSubmitSensorEvent,
  onSubmitControllerEvent,
  onExecuteScenario,
}) => {
  const [direction, setDirection] = useState<Direction>('NORTH');
  const [vehicleType, setVehicleType] = useState<VehicleType>('FORKLIFT');
  const [vehicleId, setVehicleId] = useState('VH-501');
  const [sequenceNo, setSequenceNo] = useState(1501);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  // Send vehicle arrival event
  const handleVehicleArrive = async () => {
    setIsBusy(true);
    setFeedback(null);
    try {
      const payload: SensorEventPayload = {
        event_id: `evt-${Date.now()}`,
        junction_id: junctionId,
        direction,
        event_type: 'VEHICLE_ARRIVED',
        vehicle_id: vehicleId,
        vehicle_type: vehicleType,
        sequence_no: sequenceNo,
        timestamp: new Date().toISOString(),
      };
      const res = await onSubmitSensorEvent(payload);
      setFeedback(`✓ ${vehicleType} (${vehicleId}) arrived at ${direction}. Queue updated.`);
      setSequenceNo((prev) => prev + 1);
      setVehicleId(`VH-${Math.floor(100 + Math.random() * 900)}`);
    } catch {
      setFeedback('Error sending vehicle arrival event');
    } finally {
      setIsBusy(false);
    }
  };

  // Send vehicle clearance event
  const handleVehicleCleared = async () => {
    setIsBusy(true);
    setFeedback(null);
    try {
      const payload: SensorEventPayload = {
        event_id: `evt-${Date.now()}`,
        junction_id: junctionId,
        direction,
        event_type: 'VEHICLE_CLEARED',
        vehicle_id: vehicleId,
        vehicle_type: vehicleType,
        sequence_no: sequenceNo,
        timestamp: new Date().toISOString(),
      };
      await onSubmitSensorEvent(payload);
      setFeedback(`✓ Vehicle cleared from ${direction}. Queue decremented.`);
      setSequenceNo((prev) => prev + 1);
    } catch {
      setFeedback('Error sending vehicle cleared event');
    } finally {
      setIsBusy(false);
    }
  };

  // Run assessment preset scenarios
  const handleRunPreset = async (scenarioNumber: number, label: string) => {
    setIsBusy(true);
    setFeedback(null);
    try {
      const msg = await onExecuteScenario(scenarioNumber);
      setFeedback(`✓ Preset "${label}" executed: ${msg}`);
    } catch {
      setFeedback(`Error running preset: ${label}`);
    } finally {
      setIsBusy(false);
    }
  };

  // Controller ACK
  const handleSendAck = async () => {
    setIsBusy(true);
    setFeedback(null);
    try {
      const cmdId = pendingCommandId || 'cmd-8001';
      await onSubmitControllerEvent({
        command_id: cmdId,
        junction_id: junctionId,
        direction,
        status: 'ACK',
        actual_state: 'GREEN',
        device_type: 'SIGNAL_CONTROLLER',
        timestamp: new Date().toISOString(),
      });
      setFeedback(`✓ Controller confirmed ACK for ${cmdId}. Actual state set to GREEN.`);
    } catch {
      setFeedback('Error sending controller ACK');
    } finally {
      setIsBusy(false);
    }
  };

  // Controller Offline Toggle
  const handleToggleOffline = async () => {
    setIsBusy(true);
    setFeedback(null);
    try {
      await onSubmitControllerEvent({
        event_id: `status-${Date.now()}`,
        junction_id: junctionId,
        device_type: 'SIGNAL_CONTROLLER',
        status: 'OFFLINE',
        timestamp: new Date().toISOString(),
      });
      setFeedback('⚠️ Signal controller set to OFFLINE. Degraded failure alert triggered.');
    } catch {
      setFeedback('Error setting controller offline');
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <span>🧪 Traffic & Sensor Event Simulator</span>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Quick testing tool for evaluators (Section 14.8 & Section 15)
        </div>
      </div>

      <div className="card-body">
        {/* Section 1: Quick 1-Click Scenario Presets */}
        <div style={{ marginBottom: '1.25rem' }}>
          <div className="form-label" style={{ marginBottom: 6 }}>
            Quick Assessment Presets (1-Click Test):
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <button
              className="btn btn-secondary btn-sm"
              disabled={isBusy}
              onClick={() => handleRunPreset(1, 'Normal Traffic')}
            >
              🚗 Normal Traffic
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={isBusy}
              onClick={() => handleRunPreset(2, 'Truck Priority')}
            >
              🚛 Heavy Truck Priority
            </button>
            <button
              className="btn btn-danger btn-sm"
              disabled={isBusy}
              onClick={() => handleRunPreset(3, 'Emergency Preemption')}
            >
              🚨 Emergency
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={isBusy}
              onClick={() => handleRunPreset(5, 'Duplicate Event')}
            >
              🔄 Test Duplicate Idempotency
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={isBusy}
              onClick={() => handleRunPreset(6, 'Vehicle Clearance')}
            >
              🧹 Vehicle Clearance
            </button>
            <button
              className="btn btn-warning btn-sm"
              disabled={isBusy}
              onClick={handleToggleOffline}
            >
              ⚠️ Controller Offline
            </button>
            <button
              className="btn btn-secondary btn-sm"
              disabled={isBusy}
              onClick={handleSendAck}
            >
              🟢 Send Controller ACK
            </button>
          </div>
        </div>

        {/* Section 2: Custom Vehicle Simulation Form */}
        <div
          style={{
            background: 'var(--bg-subtle)',
            padding: '12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-color)',
          }}
        >
          <div className="form-label" style={{ marginBottom: 8 }}>
            Custom Sensor Event Form:
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '8px', alignItems: 'flex-end' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Direction:</label>
              <select
                className="form-select"
                value={direction}
                onChange={(e) => setDirection(e.target.value as Direction)}
              >
                <option value="NORTH">NORTH</option>
                <option value="SOUTH">SOUTH</option>
                <option value="EAST">EAST</option>
                <option value="WEST">WEST</option>
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Vehicle Type:</label>
              <select
                className="form-select"
                value={vehicleType}
                onChange={(e) => setVehicleType(e.target.value as VehicleType)}
              >
                <option value="FORKLIFT">FORKLIFT (P3)</option>
                <option value="TRUCK">TRUCK (P2)</option>
                <option value="EMERGENCY">EMERGENCY (P1)</option>
                <option value="EMPLOYEE_VEHICLE">EMPLOYEE (P4)</option>
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Vehicle ID:</label>
              <input
                type="text"
                className="form-input"
                value={vehicleId}
                onChange={(e) => setVehicleId(e.target.value)}
              />
            </div>

            <div style={{ display: 'flex', gap: '6px' }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                style={{ flex: 1 }}
                disabled={isBusy}
                onClick={handleVehicleArrive}
              >
                + Arrive
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ flex: 1 }}
                disabled={isBusy}
                onClick={handleVehicleCleared}
              >
                &minus; Clear
              </button>
            </div>
          </div>
        </div>

        {/* Feedback message */}
        {feedback && (
          <div
            style={{
              marginTop: '10px',
              padding: '6px 10px',
              borderRadius: '4px',
              fontSize: '12px',
              background: '#f0fdf4',
              color: '#15803d',
              border: '1px solid #bbf7d0',
            }}
          >
            {feedback}
          </div>
        )}
      </div>
    </div>
  );
};
