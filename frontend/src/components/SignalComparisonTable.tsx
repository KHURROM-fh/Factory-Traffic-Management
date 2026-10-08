'use client';

import React from 'react';
import { Direction, JunctionStatus, SignalColor } from '@/types/traffic';

interface SignalComparisonTableProps {
  status: JunctionStatus;
}

const renderPill = (color: SignalColor) => {
  switch (color) {
    case 'GREEN':
      return <span className="signal-pill pill-green">GREEN</span>;
    case 'YELLOW':
      return <span className="signal-pill pill-yellow">YELLOW</span>;
    case 'RED':
      return <span className="signal-pill pill-red">RED</span>;
    default:
      return <span>{color}</span>;
  }
};

export const SignalComparisonTable: React.FC<SignalComparisonTableProps> = ({ status }) => {
  const directions: Direction[] = ['NORTH', 'SOUTH', 'EAST', 'WEST'];
  const desired = status.desired_signals || { NORTH: 'RED', SOUTH: 'RED', EAST: 'RED', WEST: 'RED' };
  const actual = status.actual_signals || { NORTH: 'RED', SOUTH: 'RED', EAST: 'RED', WEST: 'RED' };
  const queues = status.queues || { NORTH: 0, SOUTH: 0, EAST: 0, WEST: 0 };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <span>⚙️ Signal State Verification (Desired vs Confirmed)</span>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Controller: <strong style={{ color: status.controller_status === 'ONLINE' ? '#16a34a' : '#ea580c' }}>{status.controller_status}</strong>
        </div>
      </div>

      <div className="card-body" style={{ padding: 0 }}>
        <table className="signal-comparison-table">
          <thead>
            <tr>
              <th>Direction</th>
              <th>Desired State</th>
              <th>Actual (Controller ACK)</th>
              <th>Status Verification</th>
              <th>Queue Count</th>
            </tr>
          </thead>
          <tbody>
            {directions.map((dir) => {
              const dState = desired[dir] || 'RED';
              const aState = actual[dir] || 'RED';
              const isMatch = dState === aState;

              return (
                <tr key={dir}>
                  <td>
                    <strong>{dir}</strong>
                  </td>
                  <td>{renderPill(dState)}</td>
                  <td>{renderPill(aState)}</td>
                  <td>
                    {isMatch ? (
                      <span style={{ color: '#16a34a', fontWeight: 600 }}>✓ Synchronized</span>
                    ) : (
                      <span className="mismatch-flag">⚠️ Desired != Actual</span>
                    )}
                  </td>
                  <td>
                    <span style={{ fontWeight: 600 }}>{queues[dir] || 0}</span> vehicle(s)
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {/* Pending Command Note */}
        {status.pending_command && (
          <div
            style={{
              padding: '10px 14px',
              background: '#fef3c7',
              borderTop: '1px solid #fde68a',
              fontSize: '12px',
              color: '#92400e',
            }}
          >
            <strong>Pending Command:</strong> <code>{status.pending_command.command_id}</code> &mdash; Direction:{' '}
            <strong>{status.pending_command.direction}</strong> &rarr; Requested State:{' '}
            <strong>{status.pending_command.requested_state}</strong> (Status: {status.pending_command.status})
          </div>
        )}
      </div>
    </div>
  );
};
