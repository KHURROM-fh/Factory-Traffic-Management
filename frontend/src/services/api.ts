/**
 * Traffic System API Client
 * Clean, lightweight communication layer for Factory Traffic Management.
 * Communicates with live backend REST API (default http://localhost:8000),
 * with instant graceful fallback to the in-memory simulator when backend is offline.
 */

import {
  JunctionStatus,
  SensorEventPayload,
  ManualCommandPayload,
  ControllerEventPayload,
  AuditHistoryEvent,
} from '@/types/traffic';
import { mockTrafficEngine } from './mockTrafficEngine';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

let lastBackendConnected = false;

export function getIsBackendConnected(): boolean {
  return lastBackendConnected;
}

export type DataSourceMode = 'LIVE_BACKEND' | 'LOCAL_SIMULATOR' | 'AUTO';

export function getStoredApiUrl(): string {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('traffic_api_url') || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  }
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
}

export function setStoredApiUrl(url: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem('traffic_api_url', url);
  }
}

export function getStoredDataMode(): DataSourceMode {
  if (typeof window !== 'undefined') {
    return (localStorage.getItem('traffic_data_mode') as DataSourceMode) || 'AUTO';
  }
  return 'AUTO';
}

export function setStoredDataMode(mode: DataSourceMode): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem('traffic_data_mode', mode);
  }
}

export async function pingBackend(url?: string): Promise<{ ok: boolean; status?: number; error?: string }> {
  const target = (url || getStoredApiUrl()).replace(/\/+$/, '');
  try {
    const res = await fetch(`${target}/api/junctions`, { method: 'GET', cache: 'no-store' });
    lastBackendConnected = res.ok;
    return { ok: res.ok, status: res.status };
  } catch (err: any) {
    lastBackendConnected = false;
    return { ok: false, error: err?.message || 'Connection failed' };
  }
}

/**
 * Fetch with a configurable timeout so offline backends
 * never freeze or block the user interface.
 */
async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 3500): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (res.ok) {
      lastBackendConnected = true;
    }
    return res;
  } catch (err) {
    clearTimeout(timer);
    lastBackendConnected = false;
    throw err;
  }
}

// Quick health check
export async function checkBackendConnection(): Promise<boolean> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/junctions`, { cache: 'no-store' }, 2000);
    lastBackendConnected = res.ok;
    return res.ok;
  } catch {
    lastBackendConnected = false;
    return false;
  }
}

// 1. GET /api/junctions
export async function fetchJunctions(): Promise<{ id: string; name: string }[]> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/junctions`, { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) {
        lastBackendConnected = true;
        return data.map((item) => {
          if (typeof item === 'string') return { id: item, name: `Junction ${item}` };
          return { id: item.id || item.junction_id, name: item.name || `Junction ${item.id || item.junction_id}` };
        });
      }
    }
  } catch {
    lastBackendConnected = false;
  }
  return mockTrafficEngine.getJunctions().map((j) => ({ id: j.id, name: j.name }));
}

// 2. GET /api/junctions/:id/status
export async function fetchJunctionStatus(junctionId: string): Promise<JunctionStatus> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/junctions/${encodeURIComponent(junctionId)}/status`,
      { cache: 'no-store' }
    );
    if (res.ok) {
      const data = await res.json();
      return data as JunctionStatus;
    }
  } catch {
    // Fallback to local simulator
  }

  const simStatus = mockTrafficEngine.getJunctionStatus(junctionId);
  return simStatus || mockTrafficEngine.getJunctionStatus('A')!;
}

// 3. POST /api/sensor-events
export async function submitSensorEvent(
  payload: SensorEventPayload
): Promise<{ success: boolean; message: string; duplicate?: boolean }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/sensor-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      return {
        success: true,
        message: data.message || 'Sensor event processed',
        duplicate: data.duplicate ?? data.is_duplicate,
      };
    }
  } catch {
    // Fallback to local simulator
  }

  return mockTrafficEngine.handleSensorEvent(payload);
}

// 4. POST /api/junctions/:id/commands
export async function sendManualCommand(
  junctionId: string,
  command: ManualCommandPayload
): Promise<{ success: boolean; message: string }> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/junctions/${encodeURIComponent(junctionId)}/commands`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(command),
      }
    );

    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      return { success: true, message: data.message || 'Command executed' };
    }
  } catch {
    // Fallback to local simulator
  }

  return mockTrafficEngine.handleManualCommand(junctionId, command);
}

// 5. POST /api/controller-events
export async function submitControllerEvent(
  payload: ControllerEventPayload
): Promise<{ success: boolean; message: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/controller-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      return { success: true, message: data.message || 'Controller event registered' };
    }
  } catch {
    // Fallback to local simulator
  }

  return mockTrafficEngine.handleControllerEvent(payload);
}

// 6. GET /api/junctions/:id/history
export async function fetchJunctionHistory(junctionId: string, limit = 50): Promise<AuditHistoryEvent[]> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/junctions/${encodeURIComponent(junctionId)}/history?limit=${limit}`,
      { cache: 'no-store' }
    );
    if (res.ok) {
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data && Array.isArray(data.events) ? data.events : []);
      if (Array.isArray(data) || list.length > 0) {
        return list.map((item: any) => ({
          ...item,
          id: String(item.id),
        }));
      }
    }
  } catch {
    // Fallback to local simulator
  }

  return mockTrafficEngine.getHistory(junctionId, limit);
}

// 7. POST /api/junctions/:id/tick
export async function tickJunction(junctionId: string): Promise<any> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/junctions/${encodeURIComponent(junctionId)}/tick`,
      { method: 'POST' }
    );
    if (res.ok) {
      return await res.json().catch(() => ({}));
    }
  } catch {
    // Fallback
  }
}
