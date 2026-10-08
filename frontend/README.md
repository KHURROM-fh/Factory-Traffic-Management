# Factory Traffic Management System - Frontend Dashboard
**CSI Smart Tech | Technical Assessment V2 - Frontend Implementation**

A clean, responsive Next.js web application for supervising and controlling vehicle traffic across internal junctions in a garment manufacturing plant.

---

## 1. Overview & Key Capabilities

The dashboard implements all functional requirements outlined in Section 14 and Section 15 of the specification:

- **14.1 Dashboard Overview**: Real-time traffic signal states, queue lengths by direction, controller operating mode, active phase corridor, emergency indicators, and physical degradation warnings.
- **14.2 Junction Detail View**: Supports multi-junction supervision (`Junction A`, `Junction B`, `Junction C`), separating Desired vs Confirmed Actual states, queue tables, and pending hardware commands.
- **14.3 Visual Intersection**: 2D layout depicting the NORTH, SOUTH, EAST, and WEST signal heads, stop lines, queue counters, and center conflict clearance corridor.
- **14.4 Manual Traffic Control**: Administrator command panel allowing manual green phase requests (`NORTH`, `SOUTH`, `EAST`, `WEST`) and return-to-automatic control, routed safely through transition logic.
- **14.5 Emergency Preemption**: Real-time alert banner showing incoming emergency vehicle direction, vehicle ID, and active preemption stage.
- **14.6 Failure & Degradation Display**: Prominent alert banners for controller offline status, sensor faults, command timeouts, and state mismatches (Desired &ne; Actual).
- **14.7 Recent Activity & Audit Trail**: Chronological event history table (`/api/junctions/:id/history`) with filtering by event type, text search, and modal JSON record inspection.
- **14.8 Evaluator Traffic & Hardware Simulator**: Interactive simulation forms for vehicle arrivals/clearances, controller ACK/NACK responses, plus 1-click execution for all 9 assessment scenarios.
- **14.9 Polling & Auto-Refresh**: Configurable telemetry polling (1s real-time, 2s, 5s, or Paused) with manual refresh trigger.
- **14.10 Comprehensive Error Handling**: Graceful degradation when backend is unreachable, automatic fallback to client-side deterministic simulator, input validation, and connection testing.

---

## 2. Quick Setup & Run Instructions

### Prerequisites
- Node.js (v18+ or v20+ recommended, tested on Node v24)
- npm (v9+ / v11+)

### Installation
```bash
cd frontend
npm install
```

### Running Locally

**Production Server (Recommended, Port 3005):**
```bash
npm run build
npm run start -- -p 3005
```
Open **[http://localhost:3005](http://localhost:3005)** in your browser.

**Development Server:**
```bash
npm run dev -- -p 3005
```

### Running Tests
```bash
npm test
```
Executes automated tests validating phase conflict invariants, sensor deduplication, queue safety, vehicle priority weights, and state transition sequencing.

---

## 3. Traffic-Control Algorithm Explanation

### Phase Structure
The junction manages two conflicting basic phases:
1. `NORTH_SOUTH` (North & South green simultaneously)
2. `EAST_WEST` (East & West green simultaneously)

### Safety Transition Sequence (Deterministic State Machine)
Direct transitions between conflicting GREEN phases are strictly prohibited:
```
CURRENT GREEN (~30s)
       │
       ▼
CLEARANCE YELLOW (~5s)
       │
       ▼
ALL-RED CLEARANCE (~3s)
       │
       ▼
TARGET GREEN (~30s)
```

### Queue Scheduling & Vehicle Priority
Traffic priorities follow the operational requirements of the manufacturing facility:
$$\text{Priority Weight: } \text{EMERGENCY (100)} > \text{TRUCK (40)} > \text{FORKLIFT (30)} > \text{EMPLOYEE\_VEHICLE (10)}$$

Dynamic scheduling score for each phase:
$$\text{Phase Score} = \sum_{\text{direction}} \left( \text{Queue Size} \times 1.5 + \text{Highest Priority} \times 2.0 + \frac{\text{Max Waiting Seconds}}{10} \right)$$

- **Starvation Protection**: Low-priority vehicles waiting longer than 90 seconds receive an escalating priority booster to ensure factory workers are never starved behind heavy forklift freight.

---

## 4. Instructions for Demonstrating the Main Scenarios (Section 15)

In the dashboard, navigate to the **"Evaluator Traffic & Hardware Simulator"** panel:

1. **Scenario 1 - Normal Traffic**: Click **"Run"** under Scenario 1. Vehicles arrive from North, East, and South. The system registers arrivals, increments queue counts, and logs events.
2. **Scenario 2 - Priority Traffic**: Click **"Run"** under Scenario 2. Heavy TRUCK and FORKLIFT arrive at West/East, boosting phase priority.
3. **Scenario 3 - Emergency Preemption**: Click **"Run"** under Scenario 3. Ambulance `AMB-FACTORY-01` arrives from East while North/South is green. An emergency banner activates immediately and the junction transitions safely (`Yellow` &rarr; `All-Red` &rarr; `East-West Green`).
4. **Scenario 4 - Manual Override**: Click **"Run"** under Scenario 4 (or use the Manual Control panel). Supervisor takes manual control of West; normal auto-timer pauses. Click "Return to Automatic" to resume normal scheduling.
5. **Scenario 5 - Duplicate Event (Idempotency)**: Click **"Run"** under Scenario 5. The exact same event (`evt-dup-fixed`) is sent twice. The system processes the first and rejects the second without double-counting.
6. **Scenario 6 - Vehicle Clearance**: Click **"Run"** under Scenario 6. Vehicle arrives and departs via `VEHICLE_CLEARED`. The queue count decrements without dropping below zero.
7. **Scenario 7 - Controller Failure**: Click **"Run"** under Scenario 7. Controller reports `OFFLINE`. The dashboard activates the degradation alert banner and halts automatic phase changes.
8. **Scenario 8 - Restart Simulation**: Click **"Run"** under Scenario 8. Validates that current phase and queue states reload from persistence without assuming unconfirmed physical signal states.
9. **Scenario 9 - Concurrent Events**: Click **"Run"** under Scenario 9. A rapid burst of 5 events (Truck arrival, Emergency arrival, Manual command, Duplicate arrival, and Controller ACK) arrives within milliseconds. The system processes them sequentially, preserving zero-conflict safety invariants.

---

## 5. Major Architectural Decisions

1. **Clean Separation of Desired vs Actual State**:
   - The backend and UI strictly distinguish between *desired state* (what the algorithm wants) and *confirmed physical state* (what the signal controller acknowledged).
   - Any divergence triggers a visual `Desired != Actual` warning pill.

2. **Dual-Mode Connectivity (Backend-Live + Standalone Simulator)**:
   - When a REST backend is running on `http://localhost:8000`, the frontend seamlessly issues HTTP requests.
   - If the backend is offline or during standalone frontend grading, the application automatically falls back to an in-memory deterministic simulation engine (`mockTrafficEngine.ts`). Evaluators can test without standing up external databases.

3. **SCADA Industrial White Theme**:
   - Engineered for factory supervisor visibility: crisp white containers, high-contrast typography, neutral borders, and high-visibility status indicators.
   - Avoids flashy dark-mode or AI-generated aesthetics in favor of a clean, functional operational console.

4. **Command-Oriented Administrator Interface**:
   - Rather than allowing an operator to force arbitrary raw signal lights, clients issue high-level intents (`MANUAL_GREEN_REQUEST`), ensuring the backend state machine enforces safety transitions.

---

## 6. Assumptions / Questions / Requirement Issues

### Unclear / Ambiguous Items
- **Conflicting Phase Definition**: Assumed orthogonal phases strictly conflict. NORTH+SOUTH run together, and EAST+WEST run together. Turning movements across oncoming traffic inside the plant were assumed restricted by road markings.
- **Authoritative Timestamp vs Sequence Number**: Sensor timestamps may experience clock drift across distributed IoT sensors. Therefore, the server-received timestamp is treated as authoritative for duration and scheduling, while `sequence_no` is used to detect out-of-order packets.
- **Duplicate Event Authority**: `event_id` is considered strictly authoritative for deduplication. A unique `event_id` processed once is saved in the processed set/table and any subsequent submissions are treated as idempotent no-ops.

### Contradictory / Unsafe Items
- **Instant Emergency Green**: The idea that an emergency vehicle should immediately get green is physically dangerous in a real plant (vehicles already in the intersection would collide). We enforced that emergencies trigger immediate *preemption transitions* (Yellow 5s &rarr; All-Red 3s &rarr; Green), never skipping clearance.
- **Arbitrary Signal Overrides**: Allowing frontend clients to write arbitrary signals could cause dual-green disasters. The system strictly prohibits client signal writing; only intent commands (`MANUAL_GREEN_REQUEST`) are accepted.

### Missing / Problematic Items
- **Negative Queue Prevention**: A sensor miscount could dispatch `VEHICLE_CLEARED` for an empty lane. The system clamps queue counts at `Math.max(0, queue - 1)` to prevent `-1` anomalies.
- **Manual Override Expiration**: An administrator could forget to release manual control. The system sets an override metadata timestamp and alerts if manual mode remains active beyond reasonable operating intervals.

---

## 7. AI / Tool Usage

- **Development Assistant**: AI-assisted development tools were utilized during this assessment for scaffolding standard Next.js directory structures, creating TypeScript domain interfaces, generating unit test assertions, and structuring documentation.
- **Domain Verification**: All core domain logic (state transition sequence, queue scoring formula, duplicate idempotency filtering, and safety invariant verification) was reviewed and validated for architectural soundness and correctness.
