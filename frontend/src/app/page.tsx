'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Direction,
  JunctionStatus,
  SensorEventPayload,
  ControllerEventPayload,
  AuditHistoryEvent,
} from '@/types/traffic';
import {
  fetchJunctions,
  fetchJunctionStatus,
  submitSensorEvent,
  sendManualCommand,
  submitControllerEvent,
  fetchJunctionHistory,
  getIsBackendConnected,
} from '@/services/api';
import { runAssessmentScenario } from '@/services/scenarioRunner';
import { mockTrafficEngine } from '@/services/mockTrafficEngine';

import { Navbar } from '@/components/Navbar';
import { MetricsBar } from '@/components/MetricsBar';
import { EmergencyBanner } from '@/components/EmergencyBanner';
import { FailureBanner } from '@/components/FailureBanner';
import { IntersectionVisualizer } from '@/components/IntersectionVisualizer';
import { SignalComparisonTable } from '@/components/SignalComparisonTable';
import { ManualControlPanel } from '@/components/ManualControlPanel';
import { QueueDetailPanel } from '@/components/QueueDetailPanel';
import { TrafficSimulationPanel } from '@/components/TrafficSimulationPanel';
import { AuditHistoryPanel } from '@/components/AuditHistoryPanel';

export default function TrafficDashboard() {
  // Junction selection state (Section 2: Junction A, B, C)
  const [junctions, setJunctions] = useState<{ id: string; name: string }[]>([
    { id: 'A', name: 'Junction A - Main Plant' },
    { id: 'B', name: 'Junction B - Warehouse Gate' },
    { id: 'C', name: 'Junction C - Loading Dock' },
  ]);
  const [selectedJunctionId, setSelectedJunctionId] = useState<string>('A');

  // Telemetry state - initialized immediately with default simulation state
  const [status, setStatus] = useState<JunctionStatus>(() => mockTrafficEngine.getJunctionStatus('A')!);
  const [history, setHistory] = useState<AuditHistoryEvent[]>(() => mockTrafficEngine.getHistory('A'));
  const [isBackendConnected, setIsBackendConnected] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState<number>(2000); // 2s polling
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Load junction list
  const loadJunctions = useCallback(async () => {
    try {
      const list = await fetchJunctions();
      if (list && list.length > 0) {
        setJunctions(list);
      }
      setIsBackendConnected(getIsBackendConnected());
    } catch {
      setIsBackendConnected(false);
    }
  }, []);

  // Fetch current junction status & history
  const loadJunctionData = useCallback(async (junctionId: string) => {
    try {
      const [statusData, historyData] = await Promise.all([
        fetchJunctionStatus(junctionId),
        fetchJunctionHistory(junctionId, 50),
      ]);
      setStatus(statusData);
      setHistory(historyData);
      setIsBackendConnected(getIsBackendConnected());
    } catch {
      setIsBackendConnected(false);
      // Fallback to local simulation data
      const fallback = mockTrafficEngine.getJunctionStatus(junctionId);
      if (fallback) setStatus(fallback);
      setHistory(mockTrafficEngine.getHistory(junctionId, 50));
    }
  }, []);

  // Auto-refresh polling loop (Section 14.9)
  useEffect(() => {
    loadJunctions();
    loadJunctionData(selectedJunctionId);

    if (refreshInterval > 0) {
      pollTimerRef.current = setInterval(() => {
        loadJunctionData(selectedJunctionId);
      }, refreshInterval);
    }

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [selectedJunctionId, refreshInterval, loadJunctionData, loadJunctions]);

  // Handle manual green command (Section 14.4 & 8)
  const handleRequestManualGreen = async (direction: Direction, adminId: string) => {
    const res = await sendManualCommand(selectedJunctionId, {
      command: 'MANUAL_GREEN_REQUEST',
      direction,
      admin_id: adminId,
    });
    if (!res.success) {
      throw new Error(res.message);
    }
    await loadJunctionData(selectedJunctionId);
  };

  // Handle return to automatic command
  const handleReturnToAutomatic = async () => {
    const res = await sendManualCommand(selectedJunctionId, {
      command: 'RETURN_TO_AUTOMATIC',
    });
    if (!res.success) {
      throw new Error(res.message);
    }
    await loadJunctionData(selectedJunctionId);
  };

  // Handle clearing emergency
  const handleClearEmergency = async () => {
    await sendManualCommand(selectedJunctionId, {
      command: 'EMERGENCY_CLEAR',
    });
    await loadJunctionData(selectedJunctionId);
  };

  // Handle sensor event submission (Section 14.8 & 4)
  const handleSubmitSensorEvent = async (payload: SensorEventPayload) => {
    const res = await submitSensorEvent(payload);
    await loadJunctionData(selectedJunctionId);
    return res;
  };

  // Handle controller event submission (Section 14.8 & 9)
  const handleSubmitControllerEvent = async (payload: ControllerEventPayload) => {
    const res = await submitControllerEvent(payload);
    await loadJunctionData(selectedJunctionId);
    return res;
  };

  // Handle running an official scenario (Section 15)
  const handleExecuteScenario = async (scenarioNumber: number) => {
    const result = await runAssessmentScenario(scenarioNumber, selectedJunctionId);
    await loadJunctionData(selectedJunctionId);
    return result;
  };

  return (
    <div className="app-container">
      {/* 1. Header Navigation & Controls */}
      <Navbar
        junctions={junctions}
        selectedJunctionId={selectedJunctionId}
        onSelectJunction={(id) => setSelectedJunctionId(id)}
        isBackendConnected={isBackendConnected}
        refreshInterval={refreshInterval}
        onChangeRefreshInterval={(interval) => setRefreshInterval(interval)}
        onManualRefresh={() => loadJunctionData(selectedJunctionId)}
      />

      <main className="main-content">
        {/* 2. Emergency Vehicle Alert Banner (Section 14.5) */}
        {status.emergency?.active && (
          <EmergencyBanner
            emergency={status.emergency}
            onClearEmergency={handleClearEmergency}
          />
        )}

        {/* 3. Hardware & Signal Failure Alert Banner (Section 14.6) */}
        <FailureBanner
          controllerStatus={status.controller_status}
          desiredSignals={status.desired_signals}
          actualSignals={status.actual_signals}
          alerts={status.alerts}
        />

        {/* 4. Real-Time Telemetry Metrics Strip (Section 14.1) */}
        <MetricsBar status={status} />

        {/* 5. Main Operational Grid: Intersection Layout & Manual Controls */}
        <div className="dashboard-grid">
          {/* LEFT COLUMN: Visual Intersection & Signal State Verification */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {/* Section 14.3 Visual 2D Intersection Layout */}
            <IntersectionVisualizer status={status} />

            {/* Section 9 & 14.2 Desired vs Confirmed Actual Signal Table */}
            <SignalComparisonTable status={status} />
          </div>

          {/* RIGHT COLUMN: Manual Override & Vehicle Queues */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {/* Section 14.4 Manual Traffic Control Panel */}
            <ManualControlPanel
              status={status}
              onRequestManualGreen={handleRequestManualGreen}
              onReturnToAutomatic={handleReturnToAutomatic}
            />

            {/* Section 5 & 14.2 Queue Breakdown & Priority Table */}
            <QueueDetailPanel
              queues={status.queues}
              queueDetails={status.queue_details}
            />
          </div>
        </div>

        {/* 6. Evaluator Traffic & Hardware Simulator (Section 14.8 & Section 15) */}
        <TrafficSimulationPanel
          junctionId={selectedJunctionId}
          pendingCommandId={status.pending_command?.command_id}
          onSubmitSensorEvent={handleSubmitSensorEvent}
          onSubmitControllerEvent={handleSubmitControllerEvent}
          onExecuteScenario={handleExecuteScenario}
        />

        {/* 7. System Activity & Audit History Trail (Section 11 & Section 14.7) */}
        <AuditHistoryPanel
          history={history}
          onRefreshHistory={() => loadJunctionData(selectedJunctionId)}
        />
      </main>
    </div>
  );
}
