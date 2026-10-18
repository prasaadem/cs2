import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import worker from "../src/index.js";

const origin = "https://prasaadem.github.io";
const env = {
  ALLOWED_ORIGINS: origin,
  CONTROL_PASSPHRASE: "test passphrase for server controls",
  SESSION_SECRET: "test signing key",
  DATHOST_EMAIL: "test@example.com",
  DATHOST_PASSWORD: "not-a-real-password",
  DATHOST_SERVER_ID: "test-server",
};
const originalFetch = globalThis.fetch;

before(() => {
  globalThis.fetch = async () =>
    Response.json({ status: "running", players: [{}, {}] });
});

after(() => {
  globalThis.fetch = originalFetch;
});

function request(
  path,
  { method = "GET", body, token, requestOrigin = origin } = {},
) {
  const headers = { Origin: requestOrigin };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  return new Request(`https://worker.example${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function login() {
  const response = await worker.fetch(
    request("/api/login", {
      method: "POST",
      body: { passphrase: env.CONTROL_PASSPHRASE },
    }),
    env,
  );
  return (await response.json()).token;
}

test("rejects requests from unapproved site origins", async () => {
  const response = await worker.fetch(
    request("/api/login", { requestOrigin: "https://attacker.example" }),
    env,
  );
  assert.equal(response.status, 403);
});

test("rejects an incorrect passphrase", async () => {
  const response = await worker.fetch(
    request("/api/login", {
      method: "POST",
      body: { passphrase: "wrong" },
    }),
    env,
  );
  assert.equal(response.status, 401);
});

test("handles null JSON bodies without throwing", async () => {
  const loginResponse = await worker.fetch(
    request("/api/login", { method: "POST", body: null }),
    env,
  );
  assert.equal(loginResponse.status, 401);

  const actionResponse = await worker.fetch(
    request("/api/action", {
      method: "POST",
      body: null,
      token: await login(),
    }),
    env,
  );
  assert.equal(actionResponse.status, 400);
});

test("requires a signed session and reports only safe server status fields", async () => {
  const unauthorized = await worker.fetch(request("/api/status"), env);
  assert.equal(unauthorized.status, 401);

  const response = await worker.fetch(
    request("/api/status", { token: await login() }),
    env,
  );
  assert.equal(response.status, 200);
  assert.deepEqual(
    await response.json().then(({ status, players }) => ({ status, players })),
    {
      status: "running",
      players: 2,
    },
  );
});

test("normalizes DatHost on flags and alternate running states", async () => {
  globalThis.fetch = async () =>
    Response.json({ on: true, status: "started", players: 3 });
  const started = await worker.fetch(
    request("/api/status", { token: await login() }),
    env,
  );
  assert.deepEqual(
    await started
      .json()
      .then(({ status, running, known, transitioning, players }) => ({
        status,
        running,
        known,
        transitioning,
        players,
      })),
    {
      status: "started",
      running: true,
      known: true,
      transitioning: false,
      players: 3,
    },
  );

  globalThis.fetch = async () => Response.json({ status: "starting" });
  const starting = await worker.fetch(
    request("/api/status", { token: await login() }),
    env,
  );
  const state = await starting.json();
  assert.equal(state.running, true);
  assert.equal(state.transitioning, true);
});

test("returns the current map from DatHost status key/value entries", async () => {
  globalThis.fetch = async () =>
    Response.json({
      on: true,
      status: [
        { key: "map", value: "de_dust2" },
        { key: "version", value: "1.0" },
      ],
    });
  const response = await worker.fetch(
    request("/api/status", { token: await login() }),
    env,
  );
  const result = await response.json();
  assert.deepEqual(result.map, {
    key: "official:de_dust2",
    label: "Dust 2",
    value: "de_dust2",
  });
});

test("recognizes alternate DatHost map keys and Source map paths", async () => {
  for (const status of [
    [{ key: "Map Name", value: "maps/de_mirage.bsp" }],
    { current_map: "de_mirage" },
    [{ key: "level", value: "de_mirage.vpk" }],
  ]) {
    globalThis.fetch = async () => Response.json({ on: true, status });
    const response = await worker.fetch(
      request("/api/status", { token: await login() }),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal((await response.json()).map?.label, "Mirage");
  }
});

test("returns documented connection details and reported uptime", async () => {
  globalThis.fetch = async () =>
    Response.json({
      on: true,
      ip: "server.example.net",
      ports: { game: 27015 },
      players_online: 4,
      status: [{ key: "server uptime", value: "1d 2h 3m 4s" }],
    });
  const response = await worker.fetch(
    request("/api/status", { token: await login() }),
    env,
  );
  const result = await response.json();
  assert.equal(result.players, 4);
  assert.equal(result.address, "server.example.net:27015");
  assert.equal(result.uptimeSeconds, 93784);
});

test("allows only the three server power actions", async () => {
  let calledUrl;
  let calledMethod;
  globalThis.fetch = async (url, options) => {
    calledUrl = url;
    calledMethod = options.method;
    return new Response(null, { status: 204 });
  };

  const response = await worker.fetch(
    request("/api/action", {
      method: "POST",
      body: { action: "start" },
      token: await login(),
    }),
    env,
  );
  assert.equal(response.status, 200);
  assert.equal(
    calledUrl,
    "https://dathost.com/api/0.1/game-servers/test-server/start",
  );
  assert.equal(calledMethod, "POST");

  const invalid = await worker.fetch(
    request("/api/action", {
      method: "POST",
      body: { action: "delete" },
      token: await login(),
    }),
    env,
  );
  assert.equal(invalid.status, 400);
});

test("sends only fixed game-console presets to DatHost", async () => {
  let calledUrl;
  let calledMethod;
  let calledLine;
  globalThis.fetch = async (url, options) => {
    calledUrl = url;
    calledMethod = options.method;
    calledLine = options.body.get("line");
    return new Response(null, { status: 200 });
  };

  for (const [action, expectedLine] of [
    ["warmup_end", "mp_warmup_end 1"],
    ["match_restart", "mp_restartgame 1"],
    ["forcecamera", "mp_forcecamera 1"],
  ]) {
    const response = await worker.fetch(
      request("/api/action", {
        method: "POST",
        body: { action },
        token: await login(),
      }),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal(
      calledUrl,
      "https://dathost.com/api/0.1/game-servers/test-server/console",
    );
    assert.equal(calledMethod, "POST");
    assert.equal(calledLine, expectedLine);
  }
});

test("runs fixed warmup, competitive, and aim presets", async () => {
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(options.body.get("line"));
    return new Response(null, { status: 200 });
  };
  const presets = [
    ["preset_warmup", ["mp_warmup_start", "mp_warmup_pausetimer 1"]],
    [
      "preset_competitive",
      [
        "mp_warmup_end 1",
        "mp_maxrounds 24",
        "mp_halftime 1",
        "mp_freezetime 15",
        "mp_restartgame 1",
      ],
    ],
    [
      "preset_aim",
      [
        "mp_warmup_start",
        "mp_freezetime 0",
        "mp_buy_anywhere 1",
        "mp_buytime 9999",
        "sv_infinite_ammo 1",
        "mp_roundtime 60",
        "mp_roundtime_defuse 60",
        "mp_restartgame 1",
      ],
    ],
  ];
  for (const [action, expected] of presets) {
    calls.length = 0;
    const response = await worker.fetch(
      request("/api/action", {
        method: "POST",
        body: { action },
        token: await login(),
      }),
      env,
    );
    assert.equal(response.status, 200);
    assert.deepEqual(calls, expected);
  }

  const invalid = await worker.fetch(
    request("/api/action", {
      method: "POST",
      body: { action: "preset_arbitrary", command: "quit" },
      token: await login(),
    }),
    env,
  );
  assert.equal(invalid.status, 400);
});

test("lists supplied maps and changes map using only the selected preset", async () => {
  const token = await login();
  const listResponse = await worker.fetch(request("/api/maps", { token }), env);
  assert.equal(listResponse.status, 200);
  const { maps } = await listResponse.json();
  assert.ok(
    maps.some(
      (map) => map.key === "official:de_dust2" && map.label === "Dust 2",
    ),
  );
  assert.ok(
    maps.some(
      (map) => map.key === "workshop:3078980631" && map.label === "Guard",
    ),
  );

  let calledUrl;
  let calledLine;
  globalThis.fetch = async (url, options) => {
    calledUrl = url;
    calledLine = options.body.get("line");
    return new Response(null, { status: 200 });
  };
  const response = await worker.fetch(
    request("/api/action", {
      method: "POST",
      body: { action: "change_map", mapKey: "workshop:3078980631" },
      token,
    }),
    env,
  );
  assert.equal(response.status, 200);
  assert.equal(
    calledUrl,
    "https://dathost.com/api/0.1/game-servers/test-server/console",
  );
  assert.equal(calledLine, "host_workshop_map 3078980631");

  const invalidMap = await worker.fetch(
    request("/api/action", {
      method: "POST",
      body: { action: "change_map", mapKey: "map arbitrary_command" },
      token,
    }),
    env,
  );
  assert.equal(invalidMap.status, 400);
});
