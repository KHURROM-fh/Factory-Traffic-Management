'use client';

import React from 'react';
import { JunctionStatus } from '@/types/traffic';

interface MetricsBarProps {
  status: JunctionStatus;
}

export const MetricsBar: React.FC<MetricsBarProps> = ({ status }) => {
  const totalQueue = Object.values(status.queues || {}).reduce((a, b) => a + b, 0);

  // Mode badge class
  const getModeBadgeClass = () => {
    switch (status.mode) {
      case 'EMERGENCY':
        return 'status-badge badge-emergency';
      case 'MANUAL':
        return 'status-badge badge-manual';
      case 'FAILURE':
        return 'status-badge badge-failure';
      default:
        return 'status-badge badge-auto';
    }
  };

  // Controller status badge class
  const getControllerBadgeClass = () => {
    switch (status.controller_status) {
      case 'ONLINE':
        return 'status-badge badge-online';
      case 'OFFLINE':
        return 'status-badge badge-offline';
      case 'DEGRADED':
      case 'WARNING':
        return 'status-badge badge-degraded';
      default:
        return 'status-badge';
    }
  };

  return (
    <div className="metrics-row">
      {/* Operating Mode */}
      <div className="metric-box">
        <div className="metric-label">Operating Mode</div>
        <div className="metric-value">
          <span className={getModeBadgeClass()}>{status.mode}</span>
        </div>
      </div>

      {/* Current Active Phase */}
      <div className="metric-box">
        <div className="metric-label">Active Phase</div>
        <div className="metric-value" style={{ fontSize: '1.05rem' }}>
          {status.phase === 'NORTH_SOUTH' && '🟢 NORTH + SOUTH'}
          {status.phase === 'EAST_WEST' && '🟢 EAST + WEST'}
          {status.phase === 'ALL_RED' && '🔴 ALL RED (CLEARANCE)'}
          {!['NORTH_SOUTH', 'EAST_WEST', 'ALL_RED'].includes(status.phase) && status.phase}
        </div>
      </div>

      {/* Controller Physical Status */}
      <div className="metric-box">
        <div className="metric-label">Controller Status</div>
        <div className="metric-value">
          <span className={getControllerBadgeClass()}>{status.controller_status}</span>
        </div>
      </div>

      {/* Total Queued Vehicles */}
      <div className="metric-box">
        <div className="metric-label">Total Vehicles Queued</div>
        <div className="metric-value">
          <span>{totalQueue}</span>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 500 }}>
            (N:{status.queues.NORTH} S:{status.queues.SOUTH} E:{status.queues.EAST} W:{status.queues.WEST})
          </span>
        </div>
      </div>

      {/* Pending Command Status */}
      <div className="metric-box">
        <div className="metric-label">Pending Command</div>
        <div className="metric-value" style={{ fontSize: '0.9rem', fontWeight: 600 }}>
          {status.pending_command ? (
            <span style={{ color: '#d97706' }}>
              {status.pending_command.command_id} ({status.pending_command.direction} &rarr;{' '}
              {status.pending_command.requested_state})
            </span>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>None (Steady State)</span>
          )}
        </div>
      </div>
    </div>
  );
};
