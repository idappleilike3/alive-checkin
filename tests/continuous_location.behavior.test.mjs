import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");

function controllerSource() {
  const start = page.indexOf("const CONTINUOUS_LOCATION_MIN_INTERVAL_MS");
  const end = page.indexOf("function formatGuardianNotifyMessage", start);
  assert.notEqual(start, -1, "continuous location controller is missing");
  assert.notEqual(end, -1, "continuous location controller end marker is missing");
  return page.slice(start, end);
}

function createController(overrides = {}) {
  const geo = {
    nextId: 1,
    watches: new Map(),
    cleared: [],
    watchPosition(success, failure, options) {
      const id = this.nextId++;
      this.watches.set(id, {success, failure, options});
      return id;
    },
    clearWatch(id) {
      this.cleared.push(id);
      this.watches.delete(id);
    },
  };
  const updates = [];
  const feedback = [];
  const sandbox = vm.createContext({
    console,
    Date,
    Math,
    Promise,
    setInterval: () => 91,
    clearInterval() {},
    navigator: {geolocation: geo},
    apiUpdateLocation: async (position, city, options) => {
      updates.push({position, city, options});
      return {safety_guard: {active: true, city, updated_at: new Date().toISOString()}};
    },
    inferTaiwanCounty: () => "台北市",
    renderSafetyGuardUi() {},
    setSafetyGuardFeedback: (message, tone) => feedback.push({message, tone}),
    currentStatusData: {safety_guard: {active: true}},
    ...overrides,
  });
  new vm.Script(
    `${controllerSource()}
     this.startTracking = startContinuousLocationTracking;
     this.stopTracking = stopContinuousLocationTracking;
     this.shouldUpload = shouldUploadContinuousLocation;
     this.freshness = friendLocationFreshness;
     this.readState = () => continuousLocationState;`,
  ).runInContext(sandbox);
  return {sandbox, geo, updates, feedback};
}

function position(latitude, longitude, timestamp = Date.now()) {
  return {coords: {latitude, longitude}, timestamp};
}

test("continuous tracker starts watchPosition and stop clears it", () => {
  const {sandbox, geo} = createController();
  sandbox.startTracking(position(25.033, 121.5654));
  assert.equal(geo.watches.size, 1);
  assert.equal(geo.watches.values().next().value.options.enableHighAccuracy, true);

  sandbox.stopTracking();
  assert.deepEqual(geo.cleared, [1]);
  assert.equal(sandbox.readState().watchId, null);
});

test("location upload is throttled by movement and time with heartbeat fallback", () => {
  const {sandbox} = createController();
  const initial = position(25.033, 121.5654);
  sandbox.startTracking(initial, 1_000_000);

  assert.equal(
    sandbox.shouldUpload(position(25.03301, 121.56541), 1_010_000),
    false,
    "small movement before 20 seconds must not upload",
  );
  assert.equal(
    sandbox.shouldUpload(position(25.0333, 121.5654), 1_025_000),
    true,
    "movement of about 20 metres after 20 seconds should upload",
  );
  assert.equal(
    sandbox.shouldUpload(position(25.03301, 121.56541), 1_061_000),
    true,
    "60 second heartbeat should upload even without movement",
  );
});

test("stale callback after stop never uploads", async () => {
  const {sandbox, geo, updates} = createController();
  sandbox.startTracking(position(25.033, 121.5654), 1_000_000);
  const callback = geo.watches.get(1).success;
  sandbox.stopTracking();

  await callback(position(25.034, 121.5654), 1_030_000);
  assert.equal(updates.length, 0);
});

test("friend freshness changes to interrupted after two minutes", () => {
  const {sandbox} = createController();
  const updatedAt = "2026-07-27T12:00:00+08:00";
  const fresh = sandbox.freshness(updatedAt, Date.parse("2026-07-27T12:01:59+08:00"));
  const stale = sandbox.freshness(updatedAt, Date.parse("2026-07-27T12:02:01+08:00"));
  assert.equal(fresh.stale, false);
  assert.match(fresh.label, /持續定位中/);
  assert.equal(stale.stale, true);
  assert.match(stale.label, /定位可能中斷/);
});

