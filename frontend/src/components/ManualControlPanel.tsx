'use client';

import React, { useState } from 'react';
import { Direction, JunctionStatus } from '@/types/traffic';

interface ManualControlPanelProps {
  status: JunctionStatus;
  onRequestManualGreen: (direction: Direction, adminId: string) => Promise<void>;
  onReturnToAutomatic: () => Promise<void>;
}

export const ManualControlPanel: React.FC<ManualControlPanelProps> = ({
  status,
  onRequestManualGreen,
  onReturnToAutomatic,
}) => {
  const [adminId, setAdminId] = useState('supervisor-01');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; isError?: boolean } | null>(null);

  const isManualActive = status.mode === 'MANUAL';

  const handleRequest = async (direction: Direction) => {
    setIsSubmitting(true);
    setFeedback(null);
    try {
      await onRequestManualGreen(direction, adminId);
      setFeedback({
        message: `Command sent: MANUAL_GREEN_REQUEST for ${direction}. Backend is initiating safe state machine transition (Yellow -> All Red -> Green).`,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Command failed';
      setFeedback({ message: msg, isError: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReturnAuto = async () => {
    setIsSubmitting(true);
    setFeedback(null);
    try {
      await onReturnToAutomatic();
      setFeedback({ message: 'Command sent: RETURN_TO_AUTOMATIC. Junction returned to automatic queue scheduling.' });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Command failed';
      setFeedback({ message: msg, isError: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <span>🎮 Manual Traffic Control</span>
        </div>
        <div>
          {isManualActive ? (
            <span className="status-badge badge-manual">MANUAL OVERRIDE ACTIVE</span>
          ) : (
            <span className="status-badge badge-auto">AUTOMATIC SCHEDULING</span>
          )}
        </div>
      </div>

      <div className="card-body">
        {/* Administrator Override Notice */}
        <div style={{ marginBottom: '1rem', fontSize: '12px', color: 'var(--text-muted)' }}>
          {isManualActive ? (
            <div
              style={{
                padding: '8px 12px',
                background: '#fef3c7',
                border: '1px solid #fde68a',
                borderRadius: '4px',
                color: '#92400e',
              }}
            >
              <strong>Active Override:</strong> Direction{' '}
              <strong>{status.manual_override?.direction || 'N/A'}</strong> overridden by{' '}
              <strong>{status.manual_override?.requested_by || 'Supervisor'}</strong>.
            </div>
          ) : (
            <p>
              Administrators can request a manual phase change. In accordance with safety rules, requests undergo
              normal clearance transitions (YELLOW 5s &rarr; ALL-RED 3s) before the target direction receives GREEN.
            </p>
          )}
        </div>

        {/* Administrator ID input */}
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', marginBottom: '1rem' }}>
          <div className="form-group" style={{ marginBottom: 0, flex: 1 }}>
            <label className="form-label" htmlFor="admin-id-input">
              Supervisor ID / Badge:
            </label>
            <input
              id="admin-id-input"
              type="text"
              className="form-input"
              value={adminId}
              onChange={(e) => setAdminId(e.target.value)}
              placeholder="e.g. supervisor-01"
              disabled={isSubmitting}
            />
          </div>

          <button
            className="btn btn-secondary"
            onClick={handleReturnAuto}
            disabled={isSubmitting || !isManualActive}
            title="Resume normal automated traffic scheduling"
          >
            Return to Automatic
          </button>
        </div>

        {/* Direction Request Buttons */}
        <div className="form-group">
          <label className="form-label">Request Manual Green Phase:</label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
            {(['NORTH', 'SOUTH', 'EAST', 'WEST'] as Direction[]).map((dir) => (
              <button
                key={dir}
                className="btn btn-primary btn-sm"
                onClick={() => handleRequest(dir)}
                disabled={isSubmitting}
                style={{
                  background:
                    isManualActive && status.manual_override?.direction === dir ? '#16a34a' : 'var(--primary)',
                }}
              >
                Green for {dir}
              </button>
            ))}
          </div>
        </div>

        {/* Feedback message */}
        {feedback && (
          <div
            style={{
              marginTop: '0.75rem',
              padding: '8px 10px',
              borderRadius: '4px',
              fontSize: '12px',
              background: feedback.isError ? '#fee2e2' : '#f0fdf4',
              color: feedback.isError ? '#b91c1c' : '#15803d',
              border: `1px solid ${feedback.isError ? '#fca5a5' : '#bbf7d0'}`,
            }}
          >
            {feedback.message}
          </div>
        )}
      </div>
    </div>
  );
};
