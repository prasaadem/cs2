import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import worker, { bestSplit } from "../src/index.js";

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

test("lists connected human players without exposing Steam IDs", async () => {
  const consoleLines = [
    "# userid name uniqueid connected ping loss state rate",
    '# 2 "Alpha Player" STEAM_1:0:123 00:10:20 42 0 active 786432',
    '# 3 "Practice Bot" BOT 00:10:20 5 0 active 786432',
  ];
  globalThis.fetch = async (url, options) => {
    if (options.method === "GET") return Response.json(consoleLines);
    return new Response(null, { status: 200 });
  };
  const response = await worker.fetch(
    request("/api/players", { token: await login() }),
    env,
  );
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).players, [
    {
      id: "2",
      name: "Alpha Player",
      connected: "00:10:20",
      ping: 42,
      state: "active",
    },
  ]);
});

test("disconnects only a currently connected session and never bans", async () => {
  const consoleLines = [
    "# userid name uniqueid connected ping loss state rate",
    '# 2 "Alpha Player" STEAM_1:0:123 00:10:20 42 0 active 786432',
  ];
  const sentLines = [];
  globalThis.fetch = async (_url, options) => {
    if (options.method === "GET") return Response.json(consoleLines);
    sentLines.push(options.body.get("line"));
    return new Response(null, { status: 200 });
  };
  const response = await worker.fetch(
    request("/api/action", {
      method: "POST",
      body: { action: "disconnect_player", playerId: "2" },
      token: await login(),
    }),
    env,
  );
  assert.equal(response.status, 200);
  assert.deepEqual(sentLines, [
    "status",
    'kickid 2 "Disconnected by server admin"',
  ]);
  assert.equal(sentLines.some((line) => /\\bban(id)?\\b/i.test(line)), false);
});

test("rejects stale and malformed player session IDs without disconnecting", async () => {
  const sentLines = [];
  globalThis.fetch = async (_url, options) => {
    if (options.method === "GET")
      return Response.json([
        "# userid name uniqueid connected ping loss state rate",
      ]);
    sentLines.push(options.body.get("line"));
    return new Response(null, { status: 200 });
  };
  for (const playerId of ["999", "2;quit", "0"] ) {
    const response = await worker.fetch(
      request("/api/action", {
        method: "POST",
        body: { action: "disconnect_player", playerId },
        token: await login(),
      }),
      env,
    );
    assert.ok([400, 409].includes(response.status));
  }
  assert.deepEqual(sentLines, ["status", "status"]);
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
  const guard = maps.find((map) => map.key === "workshop:3078980631");
  assert.equal(guard.size, "Small");
  assert.equal(guard.good, true);
  const sugarcane = maps.find((map) => map.key === "workshop:3070579459");
  assert.equal(sugarcane.note, "Pistol only");
  assert.ok(maps.every((map) => !("line" in map)));

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

// ---- team balancer ----

function fakeKv() {
  const store = new Map();
  return {
    store,
    async get(key, options) {
      const value = store.get(key);
      if (value === undefined) return null;
      return options?.type === "json" ? JSON.parse(value) : value;
    },
    async put(key, value) {
      store.set(key, value);
    },
  };
}

const ratingsToken = "test ratings token";
const samplePlayers = {
  1: { name: "Ace", rating: 1.5, games: 30 },
  2: { name: "Bolt", rating: 1.0, games: 30 },
  3: { name: "Cobra", rating: 0.5, games: 30 },
  4: { name: "Dune", rating: 0.0, games: 30 },
  5: { name: "Echo", rating: -0.5, games: 30 },
  6: { name: "Frost", rating: -1.0, games: 30 },
  7: { name: "Ghost", rating: -1.5, games: 3, provisional: true },
};

function balancerEnv() {
  return { ...env, RATINGS_TOKEN: ratingsToken, RATINGS: fakeKv() };
}

function putRatings(benv, payload, token = ratingsToken) {
  return worker.fetch(
    new Request("https://worker.example/ratings", {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }),
    benv,
  );
}

test("stores ratings only with the ratings token and a valid payload", async () => {
  const benv = balancerEnv();
  assert.equal(
    (await putRatings(benv, { v: 1, players: samplePlayers }, "wrong")).status,
    401,
  );
  assert.equal(benv.RATINGS.store.size, 0);
  assert.equal(
    (await putRatings(benv, { v: 1, players: { x: { name: "a" } } })).status,
    400,
  );
  const ok = await putRatings(benv, { v: 1, players: samplePlayers });
  assert.equal(ok.status, 200);
  assert.equal((await ok.json()).players, 7);
  assert.ok(benv.RATINGS.store.has("ratings"));
});

test("ratings storage reports 503 until the token and KV are configured", async () => {
  const response = await putRatings(env, { v: 1, players: samplePlayers });
  assert.equal(response.status, 503);
});

test("split returns two rosters and a label, never ratings", async () => {
  const benv = balancerEnv();
  await putRatings(benv, { v: 1, generated: "2026-11-07T00:00:00Z", players: samplePlayers });
  const response = await worker.fetch(
    request("/api/split", {
      method: "POST",
      body: { players: ["ace", "Bolt", "[U:1:3]", "4", "Echo", "Frost", "Newbie"] },
    }),
    benv,
  );
  assert.equal(response.status, 200);
  const text = await response.text();
  assert.ok(!text.includes("rating\""), "response must not include ratings");
  const body = JSON.parse(text);
  assert.equal(body.teams.length, 2);
  assert.equal(body.teams[0].length + body.teams[1].length, 7);
  assert.deepEqual(body.unknown, ["Newbie"]);
  assert.ok(["even", "close", "uneven"].includes(body.balance));
  assert.equal(body.ratingsUpdated, "2026-11-07T00:00:00Z");
});

test("split needs an allowed origin, published ratings and a sane player list", async () => {
  const benv = balancerEnv();
  const send = (players, requestOrigin) =>
    worker.fetch(
      request("/api/split", { method: "POST", body: { players }, requestOrigin }),
      benv,
    );
  assert.equal((await send(["Ace", "Bolt"], "https://attacker.example")).status, 403);
  assert.equal((await send(["Ace", "Bolt"])).status, 503);
  await putRatings(benv, { v: 1, players: samplePlayers });
  assert.equal((await send(["Ace"])).status, 400);
  assert.equal((await send(["Ace", "ace"])).status, 400);
  assert.equal((await send([1, 2])).status, 400);
  assert.equal((await send(["Ace", "Bolt"])).status, 200);
});

test("even split balances team means exactly when possible", () => {
  const players = [1.5, 1.0, 0.5, 0.0, -0.5, -1.5].map((rating) => ({ rating }));
  const { teamA, teamB, miss } = bestSplit(players, () => 0);
  const mean = (t) => t.reduce((s, p) => s + p.rating, 0) / t.length;
  assert.equal(teamA.length, 3);
  assert.ok(miss < 1e-9);
  assert.ok(Math.abs(mean(teamA) - mean(teamB)) < 1e-9);
});

test("odd split makes the short team slightly stronger", () => {
  const players = [1.5, 1.0, 0.5, 0.0, -0.5, -1.0, -1.5].map((rating) => ({ rating }));
  const { teamA, teamB } = bestSplit(players, () => 0);
  const mean = (t) => t.reduce((s, p) => s + p.rating, 0) / t.length;
  assert.equal(teamA.length, 3);
  assert.equal(teamB.length, 4);
  assert.ok(mean(teamA) > mean(teamB));
});

// ---- Discord /teams ----

async function discordSetup() {
  const keys = await crypto.subtle.generateKey({ name: "Ed25519" }, true, [
    "sign",
    "verify",
  ]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", keys.publicKey));
  const benv = {
    ...balancerEnv(),
    DISCORD_PUBLIC_KEY: Buffer.from(raw).toString("hex"),
  };
  await putRatings(benv, { v: 1, players: samplePlayers });
  const send = async (interaction, { tamper = false } = {}) => {
    const body = JSON.stringify(interaction);
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = new Uint8Array(
      await crypto.subtle.sign(
        { name: "Ed25519" },
        keys.privateKey,
        new TextEncoder().encode(timestamp + body),
      ),
    );
    return worker.fetch(
      new Request("https://worker.example/discord/interactions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Signature-Ed25519": Buffer.from(signature).toString("hex"),
          "X-Signature-Timestamp": timestamp,
        },
        body: tamper ? body.replace("teams", "teamz") : body,
      }),
      benv,
    );
  };
  return send;
}

const teamsCommand = (value) => ({
  type: 2,
  data: { name: "teams", options: [{ name: "players", type: 3, value }] },
});

test("discord: answers PING and rejects bad signatures", async () => {
  const send = await discordSetup();
  const ping = await send({ type: 1 });
  assert.equal(ping.status, 200);
  assert.deepEqual(await ping.json(), { type: 1 });
  assert.equal((await send(teamsCommand("Ace, Bolt"), { tamper: true })).status, 401);
  const unsigned = await worker.fetch(
    new Request("https://worker.example/discord/interactions", {
      method: "POST",
      body: "{}",
    }),
    { ...env, DISCORD_PUBLIC_KEY: "00".repeat(32) },
  );
  assert.equal(unsigned.status, 401);
});

test("discord: /teams replies publicly with two teams and no ratings", async () => {
  const send = await discordSetup();
  const response = await send(teamsCommand("Ace, Bolt, cobra, Dune, Echo, Frost, Ghost, new_guy"));
  const body = await response.json();
  assert.equal(body.type, 4);
  assert.equal(body.data.flags, 0);
  assert.deepEqual(body.data.allowed_mentions, { parse: [] });
  const text = body.data.content;
  assert.match(text, /\*\*Team A\*\* \(4\)/);
  assert.match(text, /\*\*Team B\*\* \(4\)/);
  assert.match(text, /Ghost \(new\)/);
  assert.match(text, /counted as average: new\\_guy/);
  assert.doesNotMatch(text, /1\.5|-0\.5/);
});

test("discord: bad player lists get a private hint", async () => {
  const send = await discordSetup();
  const body = await (await send(teamsCommand("Ace"))).json();
  assert.equal(body.data.flags, 64);
  assert.match(body.data.content, /separated by commas/);
});
