'use client';

import React from 'react';
import { EmergencyState } from '@/types/traffic';

interface EmergencyBannerProps {
  emergency: EmergencyState | null;
  onClearEmergency?: () => void;
}

export const EmergencyBanner: React.FC<EmergencyBannerProps> = ({ emergency, onClearEmergency }) => {
  if (!emergency || !emergency.active) return null;

  return (
    <div className="alert-banner alert-emergency">
      <div className="alert-content">
        <span className="alert-icon">EMERGENCY</span>
        <div>
          <strong>Emergency Vehicle Preemption Active:</strong> Vehicle{' '}
          <code>{emergency.vehicle_id || 'UNKNOWN'}</code> detected approaching from{' '}
          <strong>{emergency.direction}</strong>.
          <span style={{ marginLeft: 8, opacity: 0.9 }}>
            Stage: {emergency.preemption_stage || 'IN_PROGRESS'} (Preempting conflicting traffic safely)
          </span>
        </div>
      </div>
      {onClearEmergency && (
        <button className="btn btn-secondary btn-sm" onClick={onClearEmergency} style={{ background: '#ffffff' }}>
          Clear Emergency
        </button>
      )}
    </div>
  );
};
