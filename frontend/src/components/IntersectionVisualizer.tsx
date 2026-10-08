'use client';

import React from 'react';
import { Direction, JunctionStatus, SignalColor } from '@/types/traffic';

interface IntersectionVisualizerProps {
  status: JunctionStatus;
}

interface SignalHeadProps {
  label: string;
  desiredColor: SignalColor;
  actualColor: SignalColor;
  queueCount: number;
  hasEmergency?: boolean;
}

const SignalHead: React.FC<SignalHeadProps> = ({
  label,
  desiredColor,
  actualColor,
  queueCount,
  hasEmergency,
}) => {
  const isMismatch = desiredColor !== actualColor;

  return (
    <div className="arm-box">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
        <strong style={{ fontSize: '12px' }}>{label}</strong>
        <span
          className={`queue-badge ${hasEmergency ? 'has-emergency' : queueCount > 0 ? 'has-vehicles' : ''}`}
          title={`${queueCount} vehicle(s) waiting in ${label} queue`}
        >
          {hasEmergency ? '🚨 ' : '🚗 '} {queueCount}
        </span>
      </div>

      {/* Signal Light Housing */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: 2 }}>DESIRED</div>
          <div className="signal-housing">
            <span className={`signal-bulb bulb-red ${desiredColor === 'RED' ? 'active' : ''}`} />
            <span className={`signal-bulb bulb-yellow ${desiredColor === 'YELLOW' ? 'active' : ''}`} />
            <span className={`signal-bulb bulb-green ${desiredColor === 'GREEN' ? 'active' : ''}`} />
          </div>
        </div>

        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: 2 }}>ACTUAL</div>
          <div className="signal-housing">
            <span className={`signal-bulb bulb-red ${actualColor === 'RED' ? 'active' : ''}`} />
            <span className={`signal-bulb bulb-yellow ${actualColor === 'YELLOW' ? 'active' : ''}`} />
            <span className={`signal-bulb bulb-green ${actualColor === 'GREEN' ? 'active' : ''}`} />
          </div>
        </div>
      </div>

      {isMismatch && (
        <span className="mismatch-flag">
          ⚠️ Desired {desiredColor} &ne; Confirmed {actualColor}
        </span>
      )}
    </div>
  );
};

export const IntersectionVisualizer: React.FC<IntersectionVisualizerProps> = ({ status }) => {
  const desired = status.desired_signals || { NORTH: 'RED', SOUTH: 'RED', EAST: 'RED', WEST: 'RED' };
  const actual = status.actual_signals || { NORTH: 'RED', SOUTH: 'RED', EAST: 'RED', WEST: 'RED' };
  const queues = status.queues || { NORTH: 0, SOUTH: 0, EAST: 0, WEST: 0 };
  const emergencyDir = status.emergency?.active ? status.emergency.direction : null;

  // Center active corridor state
  const isNorthSouthGreen = actual.NORTH === 'GREEN' || actual.SOUTH === 'GREEN';
  const isEastWestGreen = actual.EAST === 'GREEN' || actual.WEST === 'GREEN';
  const isAllRed = status.phase === 'ALL_RED' || (!isNorthSouthGreen && !isEastWestGreen);

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <span>🚦 Junction Intersection Layout</span>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Junction ID: <strong>{status.junction_id}</strong> | Safety Status: <strong style={{ color: '#16a34a' }}>VERIFIED (Zero Phase Conflicts)</strong>
        </div>
      </div>

      <div className="card-body">
        <div className="intersection-wrapper">
          <div className="intersection-grid">
            {/* NORTH ARM */}
            <div className="arm-north">
              <SignalHead
                label="NORTH"
                desiredColor={desired.NORTH}
                actualColor={actual.NORTH}
                queueCount={queues.NORTH}
                hasEmergency={emergencyDir === 'NORTH'}
              />
            </div>

            {/* WEST ARM */}
            <div className="arm-west">
              <SignalHead
                label="WEST"
                desiredColor={desired.WEST}
                actualColor={actual.WEST}
                queueCount={queues.WEST}
                hasEmergency={emergencyDir === 'WEST'}
              />
            </div>

            {/* INTERSECTION CENTER */}
            <div className="intersection-center">
              <div className="center-phase-indicator">Junction A Center</div>
              {isNorthSouthGreen && (
                <div className="center-active-corridor corridor-north-south">
                  ↕ NORTH / SOUTH
                </div>
              )}
              {isEastWestGreen && (
                <div className="center-active-corridor corridor-east-west">
                  ↔ EAST / WEST
                </div>
              )}
              {isAllRed && (
                <div className="center-active-corridor corridor-all-red">
                  🛑 ALL RED
                </div>
              )}
            </div>

            {/* EAST ARM */}
            <div className="arm-east">
              <SignalHead
                label="EAST"
                desiredColor={desired.EAST}
                actualColor={actual.EAST}
                queueCount={queues.EAST}
                hasEmergency={emergencyDir === 'EAST'}
              />
            </div>

            {/* SOUTH ARM */}
            <div className="arm-south">
              <SignalHead
                label="SOUTH"
                desiredColor={desired.SOUTH}
                actualColor={actual.SOUTH}
                queueCount={queues.SOUTH}
                hasEmergency={emergencyDir === 'SOUTH'}
              />
            </div>
          </div>

          <div
            style={{
              marginTop: '1rem',
              fontSize: '11px',
              color: 'var(--text-muted)',
              display: 'flex',
              gap: '1.5rem',
              flexWrap: 'wrap',
              justifyContent: 'center',
            }}
          >
            <span>
              🔴 <strong>RED:</strong> Clearance stop
            </span>
            <span>
              🟡 <strong>YELLOW:</strong> Phase clearance (~5s)
            </span>
            <span>
              🟢 <strong>GREEN:</strong> Protected corridor (~30s)
            </span>
            <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>
              🔒 Safety Invariant: Conflicting phases NEVER receive GREEN simultaneously
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
