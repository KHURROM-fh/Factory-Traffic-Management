'use client';

import React, { useState, useMemo } from 'react';
import { AuditHistoryEvent } from '@/types/traffic';

interface AuditHistoryPanelProps {
  history: AuditHistoryEvent[];
  onRefreshHistory: () => void;
}

export const AuditHistoryPanel: React.FC<AuditHistoryPanelProps> = ({ history, onRefreshHistory }) => {
  const [filterType, setFilterType] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedEvent, setSelectedEvent] = useState<AuditHistoryEvent | null>(null);

  // Filter events
  const filteredEvents = useMemo(() => {
    return history.filter((ev) => {
      if (filterType !== 'ALL' && ev.event_type !== filterType) return false;
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const str = `${ev.event_type} ${ev.direction || ''} ${ev.vehicle_id || ''} ${ev.details || ''} ${ev.command_id || ''}`.toLowerCase();
        if (!str.includes(query)) return false;
      }
      return true;
    });
  }, [history, filterType, searchQuery]);

  const getEventTypePill = (type: string) => {
    if (type.includes('EMERGENCY')) {
      return (
        <span style={{ background: '#fee2e2', color: '#b91c1c', padding: '2px 6px', borderRadius: '4px', fontWeight: 700, fontSize: '10px' }}>
          🚨 {type}
        </span>
      );
    }
    if (type.includes('DUPLICATE') || type.includes('REJECTED')) {
      return (
        <span style={{ background: '#fef3c7', color: '#b45309', padding: '2px 6px', borderRadius: '4px', fontWeight: 600, fontSize: '10px' }}>
          ⚠️ {type}
        </span>
      );
    }
    if (type.includes('FAILURE') || type.includes('TIMEOUT')) {
      return (
        <span style={{ background: '#ffedd5', color: '#c2410c', padding: '2px 6px', borderRadius: '4px', fontWeight: 700, fontSize: '10px' }}>
          🛑 {type}
        </span>
      );
    }
    if (type.includes('MANUAL')) {
      return (
        <span style={{ background: '#fef3c7', color: '#92400e', padding: '2px 6px', borderRadius: '4px', fontWeight: 600, fontSize: '10px' }}>
          👤 {type}
        </span>
      );
    }
    if (type.includes('ACK') || type.includes('CONFIRMED')) {
      return (
        <span style={{ background: '#dcfce7', color: '#15803d', padding: '2px 6px', borderRadius: '4px', fontWeight: 600, fontSize: '10px' }}>
          ✓ {type}
        </span>
      );
    }
    return (
      <span style={{ background: '#e0f2fe', color: '#0369a1', padding: '2px 6px', borderRadius: '4px', fontWeight: 600, fontSize: '10px' }}>
        {type}
      </span>
    );
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <span>📜 Audit Log & System History (Section 11 & 14.7)</span>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{filteredEvents.length} records</span>
          <button className="btn btn-secondary btn-sm" onClick={onRefreshHistory}>
            Refresh
          </button>
        </div>
      </div>

      <div className="card-body">
        {/* Filters */}
        <div style={{ display: 'flex', gap: '10px', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: '180px' }}>
            <input
              type="text"
              className="form-input"
              placeholder="Search history by vehicle, command ID, or text..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div style={{ width: '220px' }}>
            <select
              className="form-select"
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
            >
              <option value="ALL">All Event Types</option>
              <option value="VEHICLE_ARRIVED">VEHICLE_ARRIVED</option>
              <option value="VEHICLE_CLEARED">VEHICLE_CLEARED</option>
              <option value="SIGNAL_CHANGED">SIGNAL_CHANGED</option>
              <option value="SIGNAL_TRANSITION_STARTED">SIGNAL_TRANSITION_STARTED</option>
              <option value="EMERGENCY_DETECTED">EMERGENCY_DETECTED</option>
              <option value="EMERGENCY_CLEARED">EMERGENCY_CLEARED</option>
              <option value="MANUAL_OVERRIDE">MANUAL_OVERRIDE</option>
              <option value="RETURN_TO_AUTOMATIC">RETURN_TO_AUTOMATIC</option>
              <option value="CONTROLLER_ACK">CONTROLLER_ACK</option>
              <option value="CONTROLLER_TIMEOUT">CONTROLLER_TIMEOUT</option>
              <option value="DUPLICATE_REJECTED">DUPLICATE_REJECTED</option>
              <option value="DEVICE_FAILURE">DEVICE_FAILURE</option>
            </select>
          </div>
        </div>

        {/* Audit Log Table */}
        <div className="data-table-container" style={{ maxHeight: '420px', overflowY: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: '130px' }}>Timestamp</th>
                <th style={{ width: '190px' }}>Event Type</th>
                <th style={{ width: '80px' }}>Direction</th>
                <th style={{ width: '110px' }}>Command ID</th>
                <th>Event Description & Details</th>
                <th style={{ width: '60px' }}>Raw</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
                    No audit records match the selected filters.
                  </td>
                </tr>
              ) : (
                filteredEvents.map((ev) => (
                  <tr key={ev.id}>
                    <td suppressHydrationWarning style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {new Date(ev.timestamp).toLocaleTimeString()}
                    </td>
                    <td>{getEventTypePill(ev.event_type)}</td>
                    <td>
                      <strong>{ev.direction || '-'}</strong>
                    </td>
                    <td>
                      {ev.command_id ? <code>{ev.command_id}</code> : '-'}
                    </td>
                    <td>{ev.details}</td>
                    <td>
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ padding: '2px 6px', fontSize: '10px' }}
                        onClick={() => setSelectedEvent(ev)}
                      >
                        JSON
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Raw Event JSON Inspector Modal */}
      {selectedEvent && (
        <div className="modal-backdrop" onClick={() => setSelectedEvent(null)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Audit Record Inspector</h3>
              <button className="modal-close" onClick={() => setSelectedEvent(null)}>
                &times;
              </button>
            </div>
            <div className="modal-body">
              <pre
                style={{
                  background: '#f8fafc',
                  border: '1px solid var(--border-color)',
                  padding: '12px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  overflowX: 'auto',
                  fontFamily: 'monospace',
                }}
              >
                {JSON.stringify(selectedEvent, null, 2)}
              </pre>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary btn-sm" onClick={() => setSelectedEvent(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
