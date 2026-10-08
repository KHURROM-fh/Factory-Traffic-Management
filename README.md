# Factory Traffic Management System
**Industrial IoT Traffic Orchestration Engine & Automated Signal Controller**

A production-grade, fail-safe traffic management system engineered for internal factory roadways and multi-way intersections in a high-throughput garment manufacturing facility. Built using **Clean Architecture** and **Domain-Driven Design (DDD)** principles with **Django 5**, **Django REST Framework**, **PostgreSQL**, and **Next.js 16 (TypeScript)**.

---

## Overview

Modern manufacturing facilities face complex logistics challenges where heavy delivery trucks, rapid in-plant forklifts, emergency vehicles, and employee commuter cars share congested internal road junctions. A poorly orchestrated junction creates logistics bottlenecks, increases collision risks, delays critical raw fabric deliveries, and threatens worker safety.

The **Factory Traffic Management System** provides:
* **Mathematical Safety Invariants**: Strict guarantees that conflicting green phases never occur simultaneously and that transitions always pass through safety clearance phases (`YELLOW` and `ALL_RED`).
* **Deterministic, Fair Priority Scheduling**: Heavy delivery trucks with tight loading deadlines and forklifts receive priority scoring over employee commuter cars, with mathematical starvation protection to prevent low-priority deadlock.
* **Non-Preemptible Emergency Safety**: Fire and ambulance vehicles are granted preemption, but transitions strictly observe physical vehicle clearance bounds.
* **Separation of Desired vs. Actual Signal States**: Commanded signal states remain distinct from hardware-confirmed states until verified by controller acknowledgements (ACK).
* **High-Concurrency Fault Tolerance**: Database-level pessimistic locking (`SELECT FOR UPDATE`), strict idempotency on sensor events, and out-of-order sequence detection prevent race conditions across distributed edge sensors.
* **Non-Blocking Asynchronous Timing**: Zero blocking sleeps (`time.sleep()`) in HTTP threads; phase durations are driven by persistent timestamps and an asynchronous background worker.

---

## Architecture

The system follows a strict **Hexagonal Architecture (Ports and Adapters)** and **Clean Architecture** pattern. Business logic is completely decoupled from database frameworks, serialization formats, and network protocols.

```
                               ┌─────────────────────────────────────────────────────────┐
                               │               Next.js 16 SCADA Dashboard                │
                               │        (Live Junction Visualizer, Simulators, Audits)   │
                               └────────────────────────────┬────────────────────────────┘
                                                            │ HTTP / JSON
                                                            ▼
                               ┌─────────────────────────────────────────────────────────┐
                               │                  REST API Layer (DRF)                   │
                               │        - Thin Views (Request routing & status codes)    │
                               │        - Serializers (Pure schema & input validation)   │
                               └────────────────────────────┬────────────────────────────┘
                                                            │
                                                            ▼
                               ┌─────────────────────────────────────────────────────────┐
                               │               Application Service Layer                 │
                               │  - EventProcessorService (Pessimistic DB Locks & Deduplication)
                               │  - SignalTimingService (Non-blocking Timestamp Manager) │
                               │  - ControllerService (Command Tracking, Timeouts, ACKs) │
                               └──────────────┬───────────────────────────┬──────────────┘
                                              │                           │
                   Hydrates Domain State &    │                           │ Dispatches
                   Enforces Safe Persistence  │                           │ Commands
                                              ▼                           ▼
┌─────────────────────────────────────────────────────────────────┐   ┌───────────────────────────────┐
│                    Pure Domain Traffic Engine                   │   │    Controller Interface Port  │
│  - TrafficStateMachine (Strict State Whitelist & Invariants)    │   │      (Abstract Base Class)    │
│  - TrafficScheduler (Multi-Attribute Scoring & Starvation Rules)│   └───────────────┬───────────────┘
│  - QueueManager (Directional FIFO & Non-Negative Queue Bounds)  │                   │
│  - TrafficEngine (Supervisor & Emergency/Manual Coordinator)    │       ┌───────────┴───────────┐
└─────────────────────────────────────────────────────────────────┘       │                       │
                                                                          ▼                       ▼
                                                              ┌──────────────────────┐ ┌──────────────────────┐
                                                              │ REST Controller Sim  │ │    MQTT Adapter      │
                                                              │  (Included Default)  │ │ (Extensible Adapter) │
                                                              └──────────────────────┘ └──────────────────────┘
```

### Architectural Guarantees
1. **Domain Isolation**: `traffic/domain/` has zero dependencies on Django, Django REST Framework, database ORM, or network libraries. It can be instantiated, simulated, and tested purely in standard Python.
2. **Thin Controllers**: API views contain zero traffic control or scheduling logic; they delegate entirely to application services.
3. **Pessimistic Concurrency**: Any mutation to a junction requires acquiring a PostgreSQL row-level lock (`select_for_update()`), serializing concurrent sensor events and timing ticks.
4. **Audit Trail**: Every significant state transition, vehicle detection, manual override, hardware ACK, and communication failure is written to an append-only `AuditLog` table.

---

## Technology Stack

* **Backend Framework**: Python 3.12+, Django 5.x
* **API Engine**: Django REST Framework (DRF)
* **Database**: PostgreSQL 14+ (leveraging native CheckConstraints, JSONB raw payloads, and row-level locks)
* **Background Worker**: Python daemon thread with persistent timestamp evaluation
* **Frontend / SCADA UI**: Next.js 16 (React 19), TypeScript, Tailwind CSS, Lucide Icons
* **Testing**: Python `unittest` / Django `TestCase` (69 comprehensive automated tests)

---

## Project Structure

```
backend/
├── config/
│   ├── settings/
│   │   ├── base.py            # Common configuration, logging, database settings
│   │   ├── development.py     # Local development configuration
│   │   └── production.py      # Production hardened settings
│   ├── env.py                 # Environment variable loader
│   ├── urls.py                # Root URL dispatcher
│   └── wsgi.py / asgi.py
├── traffic/
│   ├── api/
│   │   ├── serializers.py     # Schema validation (zero business logic)
│   │   ├── urls.py            # API routing table
│   │   └── views.py           # Thin HTTP controllers
│   ├── constants.py           # Domain enums (Directions, SignalColors, VehicleTypes, Modes)
│   ├── controllers/
│   │   └── rest_simulator.py  # Pluggable REST Controller Simulator (Fault modes)
│   ├── domain/
│   │   ├── engine.py          # Central pure domain coordinator
│   │   ├── exceptions.py      # Domain-specific safety exception classes
│   │   ├── queue_manager.py   # FIFO queue tracker with non-negative bounds
│   │   ├── scheduler.py       # Deterministic priority scoring algorithm
│   │   └── state_machine.py   # Finite state machine enforcing transition whitelists
│   ├── interfaces/
│   │   └── controller_port.py # Hexagonal Controller Port abstraction
│   ├── management/commands/
│   │   ├── run_traffic_worker.py  # Asynchronous background timing daemon
│   │   └── seed_junctions.py      # Database initialization seeder
│   ├── migrations/            # Django database migrations
│   ├── models.py              # PostgreSQL models with check constraints
│   ├── services/
│   │   ├── background_worker.py   # Non-blocking timing loop runner
│   │   ├── controller_service.py  # Command dispatch, ACK matching, timeouts
│   │   ├── event_processor.py     # Event ingestion, deduplication, row-locking
│   │   └── timing_service.py      # Timestamp-driven phase advancement & recovery
│   └── tests/
│       ├── test_api.py            # REST API endpoint tests
│       ├── test_controller_communication.py  # Port & simulator tests
│       ├── test_domain_engine.py  # Pure Python domain logic & safety invariants
│       ├── test_models.py         # DB constraints, schema idempotency
│       ├── test_services.py       # Application layer concurrency & transactions
│       └── test_timing.py         # Non-blocking timing & restart recovery
├── manage.py
├── requirements.txt
└── .env
```

---

## Setup

### Prerequisites
* Python 3.12 or newer
* PostgreSQL 14 or newer running locally or in Docker
* Node.js 18+ (for running the frontend SCADA dashboard)

### 1. Clone & Environment Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file in `backend/` (or update existing):

```env
SECRET_KEY=django-insecure-factory-traffic-mgmt-key-production-ready
DEBUG=True
ALLOWED_HOSTS=*
DATABASE_URL=postgres://postgres:12345@localhost:5432/factory_db
CORS_ALLOW_ALL_ORIGINS=True
```

---

## Database Setup

### 1. Create PostgreSQL Database
Ensure a PostgreSQL database exists named `factory_db`:
```bash
# Using psql:
psql -U postgres -c "CREATE DATABASE factory_db;"
```

### 2. Apply Migrations & Seed Default Junctions
```bash
python manage.py migrate
python manage.py seed_junctions
```
*Creates initial records for `Junction A` (Main Plant) and `Junction B` (Raw Materials Warehouse).*

---

## Running the Backend

### Start the REST API Server
```bash
python manage.py runserver 0.0.0.0:8000
```
API will be live at `http://localhost:8000/api/`.

### Run the Background Signal Timing Worker (Optional Daemon)
To run the background timing worker in a separate terminal:
```bash
python manage.py run_traffic_worker --interval 1.0
```
*Note: In test and demonstration environments, the system also supports deterministic time advancement via `POST /api/junctions/{id}/tick` without requiring an active daemon.*

---

## Running Tests

The test suite covers unit, integration, concurrency, timing, and failure recovery scenarios.

```bash
# Run all 69 automated tests
python manage.py test traffic --keepdb
```

### Test Coverage Highlights
* **Pure Domain Engine**: State transitions, non-negative queue arithmetic, truck priority, forklift priority, employee car scoring, starvation protection, emergency preemption, and manual overrides.
* **Concurrency & Safety**: Pessimistic row locking, duplicate event race conditions, conflicting green prevention.
* **Hardware Port & Controller**: Command creation, ACK confirmation, duplicate ACK handling, command timeout, offline detection, and state mismatch handling.
* **Non-Blocking Timing**: Timestamp expiration, clearance phase progression, crash restart recovery.

---

## API Endpoints

| HTTP Method | Path | Description | Typical Status Codes |
|---|---|---|---|
| `GET` | `/api/junctions` | List all configured junctions | `200 OK` |
| `POST` | `/api/junctions` | Register a new junction configuration | `201 Created`, `409 Conflict` |
| `GET` | `/api/junctions/{id}` | Retrieve junction details & configuration | `200 OK`, `404 Not Found` |
| `GET` | `/api/junctions/{id}/status` | Retrieve live operational status (queues, desired vs actual signals, emergency/manual state) | `200 OK`, `404 Not Found` |
| `POST` | `/api/sensor-events` | Ingest vehicle detection event (`VEHICLE_ARRIVED`, `VEHICLE_CLEARED`) | `202 Accepted`, `200 OK` (Duplicate), `422 Unprocessable` |
| `POST` | `/api/junctions/{id}/commands` | Issue manual operator command (`MANUAL_GREEN_REQUEST`, `RETURN_TO_AUTOMATIC`) | `200 OK`, `400 Bad Request` |
| `POST` | `/api/controller-events` | Ingest hardware controller event (ACK, OFFLINE, DEGRADED, TELEMETRY) | `200 OK`, `400 Bad Request` |
| `GET` | `/api/junctions/{id}/history` | Chronological audit trail with filtering (`?limit=50&event_type=...`) | `200 OK` |
| `POST` | `/api/junctions/{id}/tick` | Trigger non-blocking timing reconciliation tick | `200 OK` |

---

## Traffic Control Algorithm

The scheduling engine uses a transparent, deterministic multi-attribute scoring function evaluated every time a green phase is eligible for review.

$$\text{Phase Score} = \sum_{v \in \text{Queue}} \Big( W_{\text{priority}}(v) + W_{\text{wait}} \cdot t_{\text{wait}}(v) + B_{\text{starvation}}(v) \Big) + \Big( W_{\text{queue}} \cdot N_{\text{queue}} \Big)$$

### 1. Vehicle Priority Weights ($W_{\text{priority}}$)
* **EMERGENCY**: $1000.0\text{ pts}$ (Guarantees immediate preemption)
* **TRUCK**: $25.0\text{ pts}$ (Garment raw material deliveries & export shipping deadlines)
* **FORKLIFT**: $15.0\text{ pts}$ (Internal factory transit carrying semi-finished assemblies)
* **EMPLOYEE_VEHICLE**: $5.0\text{ pts}$ (Personal commuter transport)

### 2. Queue Density Weight ($W_{\text{queue}}$)
* $10.0\text{ pts}$ per queued vehicle on the approach.

### 3. Waiting Time Weight ($W_{\text{wait}}$)
* $1.0\text{ pt}$ per second waited per vehicle.

### 4. Mathematical Starvation Protection ($B_{\text{starvation}}$)
To prevent employee vehicles from being trapped indefinitely during peak shipping hours:
* When a vehicle has waited $\ge 20.0\text{ seconds}$:
  $$B_{\text{starvation}} = 50.0 + (t_{\text{wait}} - 20.0) \times 3.0\text{ pts}$$
* This exponential bonus ensures that an aging employee queue will eventually outscore newly arrived delivery trucks.

### 5. Hysteresis & Inertia (Anti-Flapping)
* Switching phases incurs clearance overhead ($\sim 5\text{ seconds}$ of yellow + all-red dead time).
* The competing phase must exceed the active phase's score by at least **$20.0\text{ points}$ (Switching Penalty)** before a transition is authorized.
* Phase duration is bound by configurable parameters:
  * $\text{min\_green} = 10\text{ seconds}$ (cannot switch prior to minimum green unless emergency occurs)
  * $\text{max\_green} = 60\text{ seconds}$ (forced phase change to prevent starvation)

---

## Signal State Machine

The signal lifecycle is governed by a finite state machine (`TrafficStateMachine`) with an explicit whitelist of allowed transitions:

```
┌─────────────────────────────────┐
│     NORTH_SOUTH_GREEN           │
│  (N=GREEN, S=GREEN, E=R, W=R)   │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     NORTH_SOUTH_YELLOW          │
│  (N=YELLOW, S=YELLOW, E=R, W=R) │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│          ALL_RED                │
│   (N=RED, S=RED, E=RED, W=RED)  │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│       EAST_WEST_GREEN           │
│  (E=GREEN, W=GREEN, N=R, S=R)   │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│       EAST_WEST_YELLOW          │
│  (E=YELLOW, W=YELLOW, N=R, S=R) │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│          ALL_RED                │
│   (N=RED, S=RED, E=RED, W=RED)  │
└────────────────┬────────────────┘
                 │
                 └───────────────► (Returns to NORTH_SOUTH_GREEN)
```

### Safety Invariants
1. **No Conflicting Greens**: Conflicting approaches (`NORTH/SOUTH` vs `EAST/WEST`) can **never** be green simultaneously.
2. **No Direct Green-to-Green**: A transition from `NORTH_SOUTH_GREEN` directly to `EAST_WEST_GREEN` raises `InvalidStateTransitionError`.
3. **Mandatory Clearance Intervals**: Every phase change must proceed sequentially:
   $$\text{GREEN} \longrightarrow \text{YELLOW} (3\text{s}) \longrightarrow \text{ALL\_RED} (2\text{s}) \longrightarrow \text{CONFIRMED TARGET GREEN}$$

---

## Emergency Handling

When an emergency vehicle (`AMB-911`, `FIRE-01`) is detected:
1. The engine immediately switches to `EMERGENCY` mode.
2. **Safety clearance is never bypassed**: If the conflicting phase is currently active, the engine initiates a clearance sequence through `YELLOW` and `ALL_RED`. Heavy industrial vehicles cannot stop instantaneously.
3. Once all-red clearance completes, green is granted to the emergency direction.
4. **Competing Emergencies**: If two emergencies arrive from conflicting directions (e.g. `NORTH` and `EAST`), the system serves them strictly in FIFO order based on verified sensor arrival timestamps.
5. **Clearance**: Upon receiving `VEHICLE_CLEARED` for the emergency vehicle, the engine checks for remaining emergency vehicles. If none remain, it gracefully restores the previous mode (`AUTOMATIC` or queued `MANUAL`).
6. **Failsafe Timeout**: If an exit sensor fails and no clearance event is received within 45 seconds, the engine automatically terminates emergency preemption and resumes scheduling.

---

## Manual Control

1. **Operator Command**: A plant supervisor can request manual green for an approach via `POST /api/junctions/{id}/commands` with `{"command": "MANUAL_GREEN_REQUEST", "direction": "EAST"}`.
2. **Safety Enforcement**: Manual requests cannot bypass yellow or all-red clearance intervals.
3. **Hierarchy of Authority**: Emergency mode strictly overrides manual mode ($\text{EMERGENCY} > \text{MANUAL} > \text{AUTOMATIC}$). If a manual override is active and an emergency vehicle arrives, manual control is suspended until the emergency departs.
4. **Return to Automatic**: The operator issues `RETURN_TO_AUTOMATIC` to release the junction back to the autonomous scheduling engine.

---

## Controller Communication

### Desired vs. Actual Signal States
To prevent catastrophic split-brain scenarios where the backend assumes physical lights have changed:
* **Desired State**: What the backend algorithm has decided and commanded. Stored in `desired_north`, `desired_south`, etc.
* **Actual State**: What the physical intersection controller has confirmed via verified ACK. Stored in `actual_north`, `actual_south`, etc.
* Updating desired signals **never** modifies actual signals. Actual signals are updated **only** when a valid controller acknowledgement is processed.

### Pluggable Hexagonal Port
Controller interaction is governed by `ControllerPort` (`traffic/interfaces/controller_port.py`). The domain engine dispatches commands through this port without knowing whether the underlying hardware communicates via REST, MQTT, Modbus, or CAN bus.

---

## Failure Handling

1. **Controller Timeout**: If a controller fails to acknowledge a command within `controller_timeout_sec` (default 5s), the command is marked `TIMEOUT`, an alert is recorded, and the junction transitions to `DEGRADED` mode.
2. **Controller Offline**: When an `OFFLINE` heartbeat or telemetry event is received, the junction is placed in fail-safe all-red hold or degraded safety mode.
3. **Desired / Actual Mismatch**: If a controller acknowledges with a signal state different from what was commanded, a `MISMATCH` alert is raised in the audit log and the controller health is flagged.
4. **Out-of-Order Sensor Events**: If a sensor event arrives with an older sequence number than the latest recorded event for that approach, it is flagged as `OUT_OF_ORDER` in the audit log and processed with verified timestamps.

---

## Persistence and Recovery

1. **Crash Survivability**: When the backend server restarts, in-flight state is not lost:
   * Current operating mode (`mode`), phase (`current_phase`), transition stage (`transition_stage`), and `target_phase` are persisted in PostgreSQL.
   * `last_phase_change_at` timestamp is preserved.
2. **Startup Reconciliation**: On startup, `SignalTimingService.recover_transitions_on_startup()` inspects junctions caught mid-transition:
   * If a junction was mid-yellow or mid-all-red when the server crashed, the service verifies elapsed time against physical reality.
   * Actual signals are **never** assumed confirmed; if pending commands were in flight, the hardware is queried for state confirmation.

---

## Concurrency Strategy

1. **Pessimistic Row-Level Locking**: Every transaction that alters junction state begins with:
   ```python
   junction = Junction.objects.select_for_update().get(id=junction_id)
   ```
   This serializes concurrent requests on the database level, preventing race conditions between simultaneous vehicle arrivals, operator commands, and timer ticks.
2. **Event Idempotency**:
   * Sensor events require a unique `event_id` as primary key on `ProcessedEvent`.
   * Re-submitting an existing `event_id` is detected immediately, returning HTTP 200 with `is_duplicate: true` without mutating queues or state.
3. **Non-Negative Queue Bounds**:
   * Mathematical floor `count = max(0, count - 1)` in `QueueManager`.
   * Database check constraints (`CheckConstraint(condition=Q(queue_count_north__gte=0))`) prevent negative queue corruption at the SQL engine level.

---

## Demo Scenarios

The following 10 scenarios demonstrate the system under standard, edge-case, and failure conditions using `curl`.

### Scenario 1: Normal Traffic Flow
**Goal**: Demonstrate vehicle arrival, scheduled transition, and signal state advancement.
```bash
# 1. Inspect current status of Junction A (starts at NORTH_SOUTH_GREEN)
curl -s http://localhost:8000/api/junctions/A/status

# 2. Ingest vehicle arrival on EAST approach (Employee vehicle)
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-NORM-01",
    "junction_id": "A",
    "direction": "EAST",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_type": "EMPLOYEE_VEHICLE",
    "vehicle_id": "EMP-101",
    "sequence_no": 1
  }'

# 3. Advance timing tick (triggers evaluation and initiates yellow clearance)
curl -s -X POST http://localhost:8000/api/junctions/A/tick

# 4. Check status to observe transition_stage: YELLOW
curl -s http://localhost:8000/api/junctions/A/status
```

---

### Scenario 2: Truck Priority
**Goal**: Demonstrate delivery truck priority outscoring multiple employee cars.
```bash
# 1. Add employee car at NORTH
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-TRK-01",
    "junction_id": "A",
    "direction": "NORTH",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_type": "EMPLOYEE_VEHICLE",
    "vehicle_id": "EMP-201"
  }'

# 2. Add delivery truck at EAST (weight 25.0 vs 5.0)
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-TRK-02",
    "junction_id": "A",
    "direction": "EAST",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_type": "TRUCK",
    "vehicle_id": "TRK-900"
  }'

# 3. Trigger tick -> Scheduler prioritizes EAST_WEST phase due to truck weight
curl -s -X POST http://localhost:8000/api/junctions/A/tick
```

---

### Scenario 3: Emergency Preemption
**Goal**: Demonstrate immediate preemption for an emergency vehicle while observing clearance bounds.
```bash
# 1. Dispatch emergency vehicle arriving on WEST approach
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-EMERG-01",
    "junction_id": "A",
    "direction": "WEST",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_type": "EMERGENCY",
    "vehicle_id": "AMB-911"
  }'

# 2. Check status -> mode is immediately EMERGENCY
curl -s http://localhost:8000/api/junctions/A/status | grep '"mode":"EMERGENCY"'

# 3. Step ticks through Yellow -> All-Red -> East-West Green
curl -s -X POST http://localhost:8000/api/junctions/A/tick
```

---

### Scenario 4: Manual Override
**Goal**: Demonstrate operator manual green override and safe return to automatic.
```bash
# 1. Request manual green on EAST approach
curl -s -X POST http://localhost:8000/api/junctions/A/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command": "MANUAL_GREEN_REQUEST",
    "direction": "EAST",
    "admin_id": "operator_jane"
  }'

# 2. Verify mode is MANUAL
curl -s http://localhost:8000/api/junctions/A/status

# 3. Return junction to automatic control
curl -s -X POST http://localhost:8000/api/junctions/A/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command": "RETURN_TO_AUTOMATIC",
    "admin_id": "operator_jane"
  }'
```

---

### Scenario 5: Duplicate Sensor Event
**Goal**: Verify idempotency when network glitches re-transmit the same sensor event.
```bash
# 1. Send first sensor event
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-DUP-TEST",
    "junction_id": "A",
    "direction": "SOUTH",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_type": "FORKLIFT",
    "vehicle_id": "FL-01"
  }'

# 2. Re-send identical event -> Returns HTTP 200 with is_duplicate: true
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-DUP-TEST",
    "junction_id": "A",
    "direction": "SOUTH",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_type": "FORKLIFT",
    "vehicle_id": "FL-01"
  }'
```

---

### Scenario 6: Vehicle Clearance
**Goal**: Demonstrate vehicle departure and non-negative queue bounds.
```bash
# 1. Clear vehicle from SOUTH approach
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-CLR-01",
    "junction_id": "A",
    "direction": "SOUTH",
    "event_type": "VEHICLE_CLEARED",
    "vehicle_id": "FL-01"
  }'

# 2. Clear an empty queue -> Queue remains strictly 0, does not error or go negative
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "EVT-CLR-02",
    "junction_id": "A",
    "direction": "SOUTH",
    "event_type": "VEHICLE_CLEARED"
  }'
```

---

### Scenario 7: Controller Timeout
**Goal**: Verify detection of unacknowledged hardware commands.
```bash
# Simulate controller event with TIMEOUT status
curl -s -X POST http://localhost:8000/api/controller-events \
  -H "Content-Type: application/json" \
  -d '{
    "junction_id": "A",
    "status": "TIMEOUT"
  }'

# Junction controller_status is updated to DEGRADED
curl -s http://localhost:8000/api/junctions/A/status
```

---

### Scenario 8: Controller Offline
**Goal**: Verify fail-safe mode when hardware disconnects.
```bash
# Send controller telemetry indicating OFFLINE
curl -s -X POST http://localhost:8000/api/controller-events \
  -H "Content-Type: application/json" \
  -d '{
    "junction_id": "A",
    "status": "OFFLINE"
  }'

# Inspect junction status to verify OFFLINE detection
curl -s http://localhost:8000/api/junctions/A/status | grep '"controller_status":"OFFLINE"'
```

---

### Scenario 9: Backend Restart
**Goal**: Verify persistence of in-flight transitions across system restart.
```bash
# Inspect junction status to observe preserved timestamps and phases
curl -s http://localhost:8000/api/junctions/A/status

# Historical transitions are preserved in the immutable audit log
curl -s "http://localhost:8000/api/junctions/A/history?limit=10"
```

---

### Scenario 10: Concurrent Events
**Goal**: Demonstrate safe serialization under high-volume simultaneous requests.
```bash
# Dispatch concurrent requests via background subshells
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{"event_id":"CONCUR-1","junction_id":"A","direction":"NORTH","event_type":"VEHICLE_ARRIVED","vehicle_type":"TRUCK","vehicle_id":"T1"}' & \
curl -s -X POST http://localhost:8000/api/sensor-events \
  -H "Content-Type: application/json" \
  -d '{"event_id":"CONCUR-2","junction_id":"A","direction":"EAST","event_type":"VEHICLE_ARRIVED","vehicle_type":"FORKLIFT","vehicle_id":"F1"}' & \
wait

# Verify queues accurately reflect both events without lost updates
curl -s http://localhost:8000/api/junctions/A/status
```

---

## Assumptions / Questions / Requirement Issues

During the design and implementation of this system, several ambiguous, incomplete, or physically hazardous real-world edge cases were identified. The following documented engineering decisions were made:

### 1. Direct Green Switching vs. Heavy Industrial Physics
* **Requirement Issue**: Naive specifications often state: *"When an emergency vehicle arrives, switch light to green immediately."*
* **Safety Reality**: In a garment factory, heavy delivery trucks carry multi-ton rolls of raw denim or cotton bales. Forcing an instantaneous transition from Green to Red without a yellow/all-red clearance interval would cause catastrophic rollover accidents or emergency brake failures in the intersection.
* **Engineering Decision**: Emergency preemption and manual override **never** bypass the physical state machine whitelist. When an emergency arrives on a conflicting approach, the system initiates an immediate clearance transition: $\text{GREEN} \rightarrow \text{YELLOW} (3\text{s}) \rightarrow \text{ALL\_RED} (2\text{s}) \rightarrow \text{GREEN}$. Safety invariants are mathematically inviolable.

### 2. Missing Departure / Clearance Sensor Failure
* **Requirement Issue**: The problem statement assumes every vehicle arrival is followed by a `VEHICLE_CLEARED` event.
* **Failure Reality**: In industrial environments, magnetic induction loops and optical sensors frequently fail, or vehicles take alternative access routes without crossing the exit sensor. Without safeguards, a single dropped clearance event would permanently leave phantom vehicles in the queue or trap the intersection in emergency mode indefinitely.
* **Engineering Decision**:
  1. Implemented a configurable **Emergency Failsafe Timeout** (default 45s) that automatically clears emergency preemption if no clearance event is detected.
  2. Implemented a **Maximum Green Bound** (`max_green_sec = 60s`) and **Starvation Bonus Curve** so that opposite approaches are guaranteed service even if an active phase has lingering phantom demand.

### 3. Competing Emergency Vehicles
* **Requirement Issue**: Unspecified behavior when two emergency vehicles (e.g. factory fire response vehicle at `NORTH` and city ambulance at `EAST`) arrive simultaneously.
* **Engineering Decision**: Implemented a deterministic FIFO policy based on verified sensor arrival timestamps (`arrived_at`). The earliest emergency is granted green first; the second emergency is queued as active target phase and served immediately upon the first vehicle's clearance.

### 4. Directional Approaches vs. Paired Intersection Phases
* **Requirement Issue**: Junctions have 4 physical directions (`NORTH`, `SOUTH`, `EAST`, `WEST`), but standard 4-way intersections group non-conflicting approaches into phases (`NORTH_SOUTH` and `EAST_WEST`).
* **Engineering Decision**: Maintained granular per-approach queues (`queue_count_north`, `queue_count_south`, etc.) to track individual vehicle locations and waiting times accurately, while aggregating scores across complimentary directions for phase-level scheduling decisions.

### 5. Controller Latency & Non-Blocking HTTP Invariant
* **Requirement Issue**: Signal timings require intervals of 10s, 30s, and 60s. A naive implementation might hold an open HTTP request with `time.sleep(30)`.
* **Engineering Decision**: Zero blocking sleeps are permitted in any API handler. Timing is completely asynchronous and driven by persistent timestamps (`last_phase_change_at`) in PostgreSQL. The system reconciles elapsed time via an independent background worker daemon and provides a deterministic `/tick` API for testing and simulation.

### 6. Sensor Network Idempotency & Re-transmissions
* **Requirement Issue**: Wireless sensor networks (Zigbee, LoRa, Wi-Fi) on factory floors frequently experience packet loss, leading to automatic retries and duplicate HTTP requests.
* **Engineering Decision**: Primary key constraints on `ProcessedEvent.event_id` enforce idempotency at the database engine level. Re-transmitted events are detected, audited, and return HTTP 200 with `is_duplicate: true` without corrupting queue counts or triggering state machine transitions.

---

## Incomplete Features / Future Improvements

The following features were intentionally not implemented due to the 4–5 hour assessment scope, and represent high-value additions for enterprise deployment:

1. **Production MQTT Broker Integration**: The hexagonal `ControllerPort` interface is fully implemented and active with `RestControllerSimulator`. A production `MqttControllerAdapter` using Paho MQTT or HiveMQ can be plugged in without modifying any domain or service code.
2. **Multi-Junction Green-Wave Corridor Coordination**: Currently, junctions operate independently (with multi-junction DB support for Junction A, B, C...). Future work could coordinate adjacent junctions along the main delivery artery to synchronize green phases.
3. **Computer Vision Vehicle Re-Identification**: Sensor events currently accept pre-classified payloads. Direct integration with camera-based YOLO/R-CNN streams for automated vehicle classification is a natural extension.
4. **Role-Based Access Control (RBAC) & OAuth2**: Manual override currently validates operator identity via parameter. An enterprise deployment would integrate OAuth2/JWT tokens with granular role permissions (e.g., Plant Operator vs. Security Officer).

---

## AI / Tool Usage

In the spirit of complete transparency and modern software engineering practices:

* **Tools Used**: AI-assisted programming tools (Claude 3.7 Sonnet / Google DeepMind Agentic IDE) were utilized during the development of this project.
* **What AI Was Used For**:
  * Accelerating boilerplate configuration and project skeleton generation.
  * Rapid creation of comprehensive unit and integration test fixtures (`test_api.py`, `test_domain_engine.py`, `test_services.py`).
  * Scaffolding Django model field definitions and typing annotations.
  * Formatting Markdown documentation and generating Postman/cURL test collections.
* **Human Engineering & Architecture**:
  * The hexagonal architecture, pure domain separation, and transaction boundary models were designed and guided by human software architecture decisions.
  * The mathematical priority scoring formula, starvation curve, and hysteresis bounds were engineered specifically to balance garment logistics against safety.
  * All safety invariants, state machine whitelists, database check constraints, and concurrency locking strategies were verified and validated through automated testing.
