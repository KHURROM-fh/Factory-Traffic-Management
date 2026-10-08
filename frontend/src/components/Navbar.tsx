'use client';

import React from 'react';

interface NavbarProps {
  junctions: { id: string; name: string }[];
  selectedJunctionId: string;
  onSelectJunction: (id: string) => void;
  isBackendConnected: boolean;
  refreshInterval: number; // in ms, 0 means paused
  onChangeRefreshInterval: (ms: number) => void;
  onManualRefresh: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  junctions,
  selectedJunctionId,
  onSelectJunction,
  isBackendConnected,
  refreshInterval,
  onChangeRefreshInterval,
  onManualRefresh,
}) => {
  return (
    <header className="navbar">
      <div className="brand-section">
        <span className="brand-badge">CSI IoT</span>
        <div>
          <h1 className="brand-title">Factory Traffic Control</h1>
          <p className="brand-subtitle">Garment Manufacturing Plant - Real-time Signal Supervisor</p>
        </div>
      </div>

      <div className="nav-controls">
        {/* Junction Switcher (Section 2 & 14.2) */}
        <div className="junction-selector">
          <label htmlFor="junction-select">Junction:</label>
          <select
            id="junction-select"
            className="select-input"
            value={selectedJunctionId}
            onChange={(e) => onSelectJunction(e.target.value)}
          >
            {junctions.map((j) => (
              <option key={j.id} value={j.id}>
                {j.name || `Junction ${j.id}`}
              </option>
            ))}
          </select>
        </div>

        {/* Auto Refresh Toggle */}
        <div className="junction-selector">
          <label htmlFor="refresh-select">Poll:</label>
          <select
            id="refresh-select"
            className="select-input"
            value={refreshInterval}
            onChange={(e) => onChangeRefreshInterval(Number(e.target.value))}
          >
            <option value={1000}>1s (Real-time)</option>
            <option value={2000}>2s</option>
            <option value={5000}>5s</option>
            <option value={0}>Paused</option>
          </select>
        </div>

        <button
          className="btn btn-secondary btn-sm"
          onClick={onManualRefresh}
          title="Fetch latest junction status"
        >
          ↻ Refresh
        </button>

        {/* Simple Connection Status Pill */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 8px',
            background: 'var(--bg-subtle)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-color)',
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor: isBackendConnected ? '#16a34a' : '#0284c7',
            }}
          />
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-main)' }}>
            {isBackendConnected ? 'Backend Live' : 'Simulation Mode'}
          </span>
        </div>
      </div>
    </header>
  );
};
