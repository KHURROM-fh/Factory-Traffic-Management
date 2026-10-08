'use client';

import React from 'react';
import { Direction, QueuedVehicle, VehicleType } from '@/types/traffic';

interface QueueDetailPanelProps {
  queues: Record<Direction, number>;
  queueDetails?: QueuedVehicle[];
}

const getVehicleBadge = (type: VehicleType) => {
  switch (type) {
    case 'EMERGENCY':
      return (
        <span
          style={{
            background: '#fee2e2',
            color: '#b91c1c',
            border: '1px solid #fca5a5',
            padding: '2px 6px',
            borderRadius: '4px',
            fontWeight: 700,
            fontSize: '10px',
          }}
        >
          🚨 EMERGENCY (P1)
        </span>
      );
    case 'TRUCK':
      return (
        <span
          style={{
            background: '#fef3c7',
            color: '#b45309',
            border: '1px solid #fde68a',
            padding: '2px 6px',
            borderRadius: '4px',
            fontWeight: 600,
            fontSize: '10px',
          }}
        >
          🚛 TRUCK (P2)
        </span>
      );
    case 'FORKLIFT':
      return (
        <span
          style={{
            background: '#e0f2fe',
            color: '#0369a1',
            border: '1px solid #bae6fd',
            padding: '2px 6px',
            borderRadius: '4px',
            fontWeight: 600,
            fontSize: '10px',
          }}
        >
          🚜 FORKLIFT (P3)
        </span>
      );
    case 'EMPLOYEE_VEHICLE':
    default:
      return (
        <span
          style={{
            background: '#f1f5f9',
            color: '#475569',
            border: '1px solid #cbd5e1',
            padding: '2px 6px',
            borderRadius: '4px',
            fontWeight: 500,
            fontSize: '10px',
          }}
        >
          🚗 EMPLOYEE (P4)
        </span>
      );
  }
};

export const QueueDetailPanel: React.FC<QueueDetailPanelProps> = ({ queues, queueDetails = [] }) => {
  const directions: Direction[] = ['NORTH', 'SOUTH', 'EAST', 'WEST'];

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <span>📋 Vehicle Queue & Priority Scheduling</span>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Priority: <strong>EMERGENCY &gt; TRUCK &gt; FORKLIFT &gt; EMPLOYEE</strong> (Starvation-Protected)
        </div>
      </div>

      <div className="card-body">
        {/* Direction Queues Summary Cards */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '8px',
            marginBottom: '1rem',
          }}
        >
          {directions.map((dir) => {
            const count = queues[dir] || 0;
            const hasVehicles = count > 0;
            return (
              <div
                key={dir}
                style={{
                  background: hasVehicles ? '#f8fafc' : '#ffffff',
                  border: `1px solid ${hasVehicles ? '#cbd5e1' : 'var(--border-color)'}`,
                  borderRadius: '4px',
                  padding: '8px 10px',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-muted)' }}>{dir}</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, color: hasVehicles ? 'var(--primary)' : 'var(--text-muted)' }}>
                  {count}
                </div>
              </div>
            );
          })}
        </div>

        {/* Detailed Waiting Vehicles Table */}
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Vehicle ID</th>
                <th>Type & Priority</th>
                <th>Direction</th>
                <th>Seq #</th>
                <th>Wait Time</th>
                <th>Starvation Risk</th>
              </tr>
            </thead>
            <tbody>
              {queueDetails.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '16px' }}>
                    All queues clear. No vehicles waiting at this junction.
                  </td>
                </tr>
              ) : (
                queueDetails.map((v, i) => {
                  const isStarved = v.waiting_seconds > 90;
                  return (
                    <tr key={`${v.vehicle_id}-${i}`}>
                      <td>
                        <strong>{v.vehicle_id}</strong>
                      </td>
                      <td>{getVehicleBadge(v.vehicle_type)}</td>
                      <td>{v.direction}</td>
                      <td>#{v.sequence_no}</td>
                      <td>{v.waiting_seconds}s</td>
                      <td>
                        {isStarved ? (
                          <span style={{ color: '#dc2626', fontWeight: 700 }}>⚠️ High Priority Boost</span>
                        ) : (
                          <span style={{ color: '#16a34a' }}>Normal</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
