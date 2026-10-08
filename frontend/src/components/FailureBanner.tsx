'use client';

import React from 'react';
import { ControllerStatus, SignalStateMap, AlertItem } from '@/types/traffic';

interface FailureBannerProps {
  controllerStatus: ControllerStatus;
  desiredSignals: SignalStateMap;
  actualSignals: SignalStateMap;
  alerts?: AlertItem[];
  onDismissAlert?: (id: string) => void;
}

export const FailureBanner: React.FC<FailureBannerProps> = ({
  controllerStatus,
  desiredSignals,
  actualSignals,
  alerts = [],
}) => {
  // Check for desired vs actual signal mismatch
  const directions: (keyof SignalStateMap)[] = ['NORTH', 'SOUTH', 'EAST', 'WEST'];
  const mismatches = directions.filter(
    (dir) => desiredSignals && actualSignals && desiredSignals[dir] !== actualSignals[dir]
  );

  const isOffline = controllerStatus === 'OFFLINE';
  const isDegraded = controllerStatus === 'DEGRADED' || controllerStatus === 'WARNING';
  const hasMismatches = mismatches.length > 0;
  const hasAlerts = alerts.length > 0;

  if (!isOffline && !isDegraded && !hasMismatches && !hasAlerts) {
    return null;
  }

  return (
    <div className="alert-banner alert-failure" style={{ flexDirection: 'column', alignItems: 'stretch', gap: '8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="alert-content">
          <span className="alert-icon">SYSTEM WARNING</span>
          <div>
            {isOffline && (
              <span>
                <strong>Physical Controller OFFLINE:</strong> The junction controller is not responding. Signals
                must fall back to fail-safe state.
              </span>
            )}
            {!isOffline && isDegraded && (
              <span>
                <strong>Controller Warning/Degraded:</strong> Controller status is reported as {controllerStatus}.
              </span>
            )}
            {!isOffline && !isDegraded && hasMismatches && (
              <span>
                <strong>State Mismatch Detected:</strong> Desired backend state does not match actual controller-confirmed state on{' '}
                {mismatches.map((m) => `${m} (Desired: ${desiredSignals[m]}, Actual: ${actualSignals[m]})`).join(', ')}.
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Render active alerts if any */}
      {alerts.length > 0 && (
        <div style={{ marginTop: '4px', fontSize: '12px', borderTop: '1px solid rgba(234, 88, 12, 0.2)', paddingTop: '6px' }}>
          <strong>Active System Warnings:</strong>
          <ul style={{ paddingLeft: '20px', marginTop: '4px' }}>
            {alerts.map((alt) => (
              <li key={alt.id}>
                [{new Date(alt.timestamp).toLocaleTimeString()}] {alt.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
