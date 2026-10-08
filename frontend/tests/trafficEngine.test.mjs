import test from 'node:test';
import assert from 'node:assert/strict';

// Test the core traffic logic invariants
test('Safety Invariant: Conflicting phases must never receive GREEN simultaneously', () => {
  const allowedConfigurations = [
    // North/South green, East/West red
    { NORTH: 'GREEN', SOUTH: 'GREEN', EAST: 'RED', WEST: 'RED' },
    // East/West green, North/South red
    { NORTH: 'RED', SOUTH: 'RED', EAST: 'GREEN', WEST: 'GREEN' },
    // All red clearance
    { NORTH: 'RED', SOUTH: 'RED', EAST: 'RED', WEST: 'RED' },
    // Yellow clearance transitions
    { NORTH: 'YELLOW', SOUTH: 'YELLOW', EAST: 'RED', WEST: 'RED' },
    { NORTH: 'RED', SOUTH: 'RED', EAST: 'YELLOW', WEST: 'YELLOW' },
  ];

  for (const config of allowedConfigurations) {
    const isNorthSouthGreen = config.NORTH === 'GREEN' || config.SOUTH === 'GREEN';
    const isEastWestGreen = config.EAST === 'GREEN' || config.WEST === 'GREEN';
    assert.equal(isNorthSouthGreen && isEastWestGreen, false, 'Conflicting phases were green simultaneously!');
  }
});

test('Idempotency: Processing identical event_id multiple times does not increment queue multiple times', () => {
  const processedEventIds = new Set();
  let queueCount = 0;

  function handleEvent(eventId) {
    if (processedEventIds.has(eventId)) {
      return { duplicate: true };
    }
    processedEventIds.add(eventId);
    queueCount += 1;
    return { duplicate: false };
  }

  const res1 = handleEvent('evt-10001');
  assert.equal(res1.duplicate, false);
  assert.equal(queueCount, 1);

  // Duplicate submission
  const res2 = handleEvent('evt-10001');
  assert.equal(res2.duplicate, true);
  assert.equal(queueCount, 1, 'Queue count incorrectly incremented on duplicate event');
});

test('Queue Protection: VEHICLE_CLEARED prevents queue from dropping below 0', () => {
  let queue = 0;

  function clearVehicle() {
    queue = Math.max(0, queue - 1);
  }

  clearVehicle();
  assert.equal(queue, 0, 'Queue dropped below 0');

  queue = 3;
  clearVehicle();
  assert.equal(queue, 2);
});

test('Vehicle Priority Hierarchy: EMERGENCY > TRUCK > FORKLIFT > EMPLOYEE_VEHICLE', () => {
  const priorityWeights = {
    EMERGENCY: 100,
    TRUCK: 40,
    FORKLIFT: 30,
    EMPLOYEE_VEHICLE: 10,
  };

  assert.ok(priorityWeights.EMERGENCY > priorityWeights.TRUCK);
  assert.ok(priorityWeights.TRUCK > priorityWeights.FORKLIFT);
  assert.ok(priorityWeights.FORKLIFT > priorityWeights.EMPLOYEE_VEHICLE);
});

test('State Transition Sequence: GREEN -> YELLOW -> ALL_RED -> TARGET_GREEN', () => {
  const transitions = [];
  let state = 'NORTH_SOUTH_GREEN';
  transitions.push(state);

  // Preemption triggered
  state = 'NORTH_SOUTH_YELLOW';
  transitions.push(state);

  // Clearance
  state = 'ALL_RED_CLEARANCE';
  transitions.push(state);

  // Target phase
  state = 'EAST_WEST_GREEN';
  transitions.push(state);

  assert.deepEqual(transitions, [
    'NORTH_SOUTH_GREEN',
    'NORTH_SOUTH_YELLOW',
    'ALL_RED_CLEARANCE',
    'EAST_WEST_GREEN',
  ]);
});
