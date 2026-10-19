const API_ROOT = "https://dathost.com/api/0.1";
const TOKEN_LIFETIME_SECONDS = 15 * 60;
const encoder = new TextEncoder();

const MAP_ROWS = [
  ["official:de_dust2", "Dust 2", "Official", "map de_dust2"],
  ["official:de_mirage", "Mirage", "Official", "map de_mirage"],
  ["official:de_overpass", "Overpass", "Official", "map de_overpass"],
  ["official:de_ancient", "Ancient", "Official", "map de_ancient"],
  ["official:de_vertigo", "Vertigo", "Official", "map de_vertigo"],
  ["official:de_inferno", "Inferno", "Official", "map de_inferno"],
  ["official:de_anubis", "Anubis", "Official", "map de_anubis"],
  ["official:de_nuke", "Nuke", "Official", "map de_nuke"],
  ["official:cs_office", "Office (H)", "Official", "map cs_office"],
  ["official:cs_italy", "Italy (H)", "Official", "map cs_italy"],
  ["official:de_grail", "Grail", "Official", "map de_grail"],
  ["official:de_jura", "Jura", "Official", "map de_jura"],
  [
    "workshop:3437809122",
    "Cache CS2 Workshop",
    "Workshop",
    "host_workshop_map 3437809122",
  ],
  [
    "workshop:3330441546",
    "De Mirage Catslap",
    "Workshop",
    "host_workshop_map 3330441546",
  ],
  [
    "workshop:3077366729",
    "Mirage Night",
    "Workshop",
    "host_workshop_map 3077366729",
  ],
  [
    "workshop:3285702564",
    "Cursed Mirage",
    "Workshop",
    "host_workshop_map 3285702564",
  ],
  [
    "workshop:3124567099",
    "Inferno Night",
    "Workshop",
    "host_workshop_map 3124567099",
  ],
  [
    "workshop:3447707473",
    "Dust 2 Night",
    "Workshop",
    "host_workshop_map 3447707473",
  ],
  ["workshop:3127729110", "Dust 1", "Workshop", "host_workshop_map 3127729110"],
  [
    "workshop:de_train",
    "Train",
    "Workshop",
    "ds_workshop_changelevel de_train",
  ],
  [
    "workshop:de_biome",
    "Biome",
    "Workshop",
    "ds_workshop_changelevel de_biome",
  ],
  [
    "workshop:de_cache",
    "Cache",
    "Workshop",
    "ds_workshop_changelevel de_cache",
  ],
  ["workshop:3079692971", "Aztec", "Workshop", "host_workshop_map 3079692971"],
  ["workshop:3070598534", "Canals", "Workshop", "host_workshop_map 3070598534"],
  [
    "workshop:3079872050",
    "Assault (H)",
    "Workshop",
    "host_workshop_map 3079872050",
  ],
  [
    "workshop:3070293560",
    "Cobblestone",
    "Workshop",
    "host_workshop_map 3070293560",
  ],
  [
    "workshop:3089953774",
    "Militia (H)",
    "Workshop",
    "host_workshop_map 3089953774",
  ],
  ["workshop:3070226055", "Tuscan", "Workshop", "host_workshop_map 3070226055"],
  [
    "workshop:3070584943",
    "Agency (H)",
    "Workshop",
    "host_workshop_map 3070584943",
  ],
  [
    "workshop:3072397323",
    "Seaside",
    "Workshop",
    "host_workshop_map 3072397323",
  ],
  [
    "workshop:3114174859",
    "All Maps in One",
    "Workshop",
    "host_workshop_map 3114174859",
  ],
  ["workshop:3121217565", "Thera", "Workshop", "host_workshop_map 3121217565"],
  [
    "workshop:3165559377",
    "Memento",
    "Workshop",
    "host_workshop_map 3165559377",
  ],
  [
    "workshop:3112468244",
    "Mirage (Mirror)",
    "Workshop",
    "host_workshop_map 3112468244",
  ],
  [
    "workshop:3074691772",
    "Sandstone",
    "Workshop",
    "host_workshop_map 3074691772",
  ],
  ["workshop:3152430710", "Mills", "Workshop", "host_workshop_map 3152430710"],
  ["workshop:3070766070", "Mutiny", "Workshop", "host_workshop_map 3070766070"],
  ["workshop:3108513658", "Akiba", "Workshop", "host_workshop_map 3108513658"],
  [
    "workshop:3074700924",
    "Aim Crazyjump",
    "Workshop",
    "host_workshop_map 3074700924",
  ],
  [
    "workshop:3196360672",
    "Outferno",
    "Workshop",
    "host_workshop_map 3196360672",
  ],
  [
    "workshop:3252689713",
    "Mirage Water",
    "Workshop",
    "host_workshop_map 3252689713",
  ],
  ["workshop:3276538015", "Museum", "Workshop", "host_workshop_map 3276538015"],
  ["workshop:de_lake", "Lake", "Workshop", "ds_workshop_changelevel de_lake"],
  [
    "workshop:de_safehouse",
    "Safehouse",
    "Workshop",
    "ds_workshop_changelevel de_safehouse",
  ],
  [
    "workshop:3118830933",
    "Short Anubis",
    "Workshop",
    "host_workshop_map 3118830933",
  ],
  ["workshop:3078980631", "Guard", "Workshop", "host_workshop_map 3078980631"],
  [
    "workshop:gd_rialto",
    "Rialto",
    "Workshop",
    "ds_workshop_changelevel gd_rialto",
  ],
  [
    "workshop:3070923343",
    "Pool Day",
    "Workshop",
    "host_workshop_map 3070923343",
  ],
  [
    "workshop:3467065969",
    "Contact",
    "Workshop",
    "host_workshop_map 3467065969",
  ],
  [
    "workshop:3322402053",
    "Aim Kingdom",
    "Workshop",
    "host_workshop_map 3322402053",
  ],
  [
    "workshop:3071005299",
    "Assembly",
    "Workshop",
    "host_workshop_map 3071005299",
  ],
  [
    "workshop:3070612859",
    "Shortdust",
    "Workshop",
    "host_workshop_map 3070612859",
  ],
  [
    "workshop:3483894219",
    "Shortdust New",
    "Workshop",
    "host_workshop_map 3483894219",
  ],
  [
    "workshop:3132854332",
    "Foroglio",
    "Workshop",
    "host_workshop_map 3132854332",
  ],
  [
    "workshop:3131775712",
    "Redline",
    "Workshop",
    "host_workshop_map 3131775712",
  ],
  [
    "workshop:3081154235",
    "AWP Creek",
    "Workshop",
    "host_workshop_map 3081154235",
  ],
  [
    "workshop:3072052900",
    "Aim AWP",
    "Workshop",
    "host_workshop_map 3072052900",
  ],
  [
    "workshop:3082605693",
    "Aim Long (Dust)",
    "Workshop",
    "host_workshop_map 3082605693",
  ],
  [
    "workshop:3073259920",
    "Aim Fake",
    "Workshop",
    "host_workshop_map 3073259920",
  ],
  [
    "workshop:3159423932",
    "Aim Map",
    "Workshop",
    "host_workshop_map 3159423932",
  ],
  [
    "workshop:3125119625",
    "Nuke Mini (Different)",
    "Workshop",
    "host_workshop_map 3125119625",
  ],
  [
    "workshop:3159212000",
    "Crazybox",
    "Workshop",
    "host_workshop_map 3159212000",
  ],
  [
    "workshop:3070290240",
    "Brewery",
    "Workshop",
    "host_workshop_map 3070290240",
  ],
  [
    "workshop:3171290420",
    "Aim Sacrificial",
    "Workshop",
    "host_workshop_map 3171290420",
  ],
  [
    "workshop:3165369649",
    "AWP Anubis Lite",
    "Workshop",
    "host_workshop_map 3165369649",
  ],
  [
    "workshop:3070411770",
    "AWP India",
    "Workshop",
    "host_workshop_map 3070411770",
  ],
  [
    "workshop:3076234827",
    "2000$ Working One",
    "Workshop",
    "host_workshop_map 3076234827",
  ],
  [
    "workshop:3329381619",
    "Aim AK Bench",
    "Workshop",
    "host_workshop_map 3329381619",
  ],
  [
    "workshop:3146105097",
    "AWP Lego 2",
    "Workshop",
    "host_workshop_map 3146105097",
  ],
  [
    "workshop:3108198185",
    "Westwood",
    "Workshop",
    "host_workshop_map 3108198185",
  ],
  [
    "workshop:3075996446",
    "Aim Deagle",
    "Workshop",
    "host_workshop_map 3075996446",
  ],
  [
    "workshop:3070579459",
    "Sugarcane",
    "Workshop",
    "host_workshop_map 3070579459",
  ],
  [
    "workshop:3408790618",
    "Eldorado",
    "Workshop",
    "host_workshop_map 3408790618",
  ],
  [
    "workshop:3271111217",
    "Aim Deagle",
    "Workshop",
    "host_workshop_map 3271111217",
  ],
  [
    "workshop:3517550687",
    "Aim AWP City",
    "Workshop",
    "host_workshop_map 3517550687",
  ],
  [
    "workshop:3376496698",
    "Lake Christmas",
    "Workshop",
    "host_workshop_map 3376496698",
  ],
].map(([key, label, category, line]) => ({ key, label, category, line }));

// Size and "good" flags from the server's map sheet; maps without an entry are unsized.
const MAP_META = {
  "workshop:3437809122": { size: "Big", good: true },
  "workshop:3330441546": { size: "Big" },
  "workshop:3127729110": { size: "Big", good: true },
  "workshop:de_train": { size: "Big", good: true },
  "workshop:de_biome": { size: "Big" },
  "workshop:de_cache": { size: "Big", good: true },
  "workshop:3079692971": { size: "Big", good: true },
  "workshop:3070598534": { size: "Big" },
  "workshop:3079872050": { size: "Big", good: true },
  "workshop:3070293560": { size: "Big", good: true },
  "workshop:3089953774": { size: "Big", good: true },
  "workshop:3070226055": { size: "Big", good: true },
  "workshop:3070584943": { size: "Big", good: true },
  "workshop:3072397323": { size: "Big", good: true },
  "workshop:3114174859": { size: "Big", good: true },
  "workshop:3121217565": { size: "Big", good: true },
  "workshop:3165559377": { size: "Big" },
  "workshop:3112468244": { size: "Big" },
  "workshop:3074691772": { size: "Big" },
  "workshop:3152430710": { size: "Big" },
  "workshop:3070766070": { size: "Big", good: true },
  "workshop:3108513658": { size: "Big" },
  "workshop:3074700924": { size: "Big" },
  "workshop:3196360672": { size: "Big", good: true },
  "workshop:3252689713": { size: "Big" },
  "workshop:3276538015": { size: "Medium", good: true },
  "workshop:de_lake": { size: "Small", good: true },
  "workshop:de_safehouse": { size: "Small", good: true },
  "workshop:3118830933": { size: "Small", good: true },
  "workshop:3078980631": { size: "Small", good: true },
  "workshop:gd_rialto": { size: "Small", good: true },
  "workshop:3070923343": { size: "Small", good: true },
  "workshop:3322402053": { size: "Small", good: true },
  "workshop:3071005299": { size: "Small", good: true },
  "workshop:3070612859": { size: "Small", good: true },
  "workshop:3483894219": { size: "Medium", good: true },
  "workshop:3132854332": { size: "Small", good: true },
  "workshop:3131775712": { size: "Small", good: true },
  "workshop:3081154235": { size: "Small", good: true },
  "workshop:3072052900": { size: "Small", good: true },
  "workshop:3082605693": { size: "Small", good: true },
  "workshop:3073259920": { size: "Small" },
  "workshop:3159423932": { size: "Small" },
  "workshop:3125119625": { size: "Small" },
  "workshop:3159212000": { size: "Small" },
  "workshop:3070290240": { size: "Small" },
  "workshop:3171290420": { size: "Small" },
  "workshop:3165369649": { size: "Small" },
  "workshop:3070411770": { size: "Small" },
  "workshop:3329381619": { size: "Small" },
  "workshop:3146105097": { size: "Small" },
  "workshop:3108198185": { size: "Small" },
  "workshop:3075996446": { size: "Small" },
  "workshop:3070579459": { size: "Small", note: "Pistol only" },
  "workshop:3517550687": { size: "Small", good: true },
  "workshop:3376496698": { size: "Small", good: true },
};

const MAPS = MAP_ROWS.map((map) => ({ ...map, ...MAP_META[map.key] }));
const MAP_BY_KEY = new Map(MAPS.map((map) => [map.key, map]));
const CONSOLE_PRESETS = {
  forcecamera: "mp_forcecamera 1",
  match_restart: "mp_restartgame 1",
  warmup_end: "mp_warmup_end 1",
};
const CONFIG_PRESETS = {
  preset_warmup: ["mp_warmup_start", "mp_warmup_pausetimer 1"],
  preset_competitive: [
    "mp_warmup_end 1",
    "mp_maxrounds 24",
    "mp_halftime 1",
    "mp_freezetime 15",
    "mp_restartgame 1",
  ],
  preset_aim: [
    "mp_warmup_start",
    "mp_freezetime 0",
    "mp_buy_anywhere 1",
    "mp_buytime 9999",
    "sv_infinite_ammo 1",
    "mp_roundtime 60",
    "mp_roundtime_defuse 60",
    "mp_restartgame 1",
  ],
};

function json(data, status, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...headers,
    },
  });
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function base64Url(bytes) {
  return bytesToBase64(bytes)
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

async function signingKey(secret) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

async function issueToken(secret) {
  const payload = base64Url(
    encoder.encode(
      JSON.stringify({
        exp: Math.floor(Date.now() / 1000) + TOKEN_LIFETIME_SECONDS,
      }),
    ),
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    await signingKey(secret),
    encoder.encode(payload),
  );
  return `${payload}.${base64Url(new Uint8Array(signature))}`;
}

async function validToken(token, secret) {
  if (!token || token.length > 2048) return false;
  const [payload, encodedSignature, extra] = token.split(".");
  if (!payload || !encodedSignature || extra) return false;
  try {
    const signature = base64ToBytes(encodedSignature);
    const valid = await crypto.subtle.verify(
      "HMAC",
      await signingKey(secret),
      signature,
      encoder.encode(payload),
    );
    if (!valid) return false;
    const claims = JSON.parse(new TextDecoder().decode(base64ToBytes(payload)));
    return (
      Number.isInteger(claims.exp) && claims.exp > Math.floor(Date.now() / 1000)
    );
  } catch {
    return false;
  }
}

function sameSecret(candidate, expected) {
  const left = encoder.encode(candidate);
  const right = encoder.encode(expected);
  if (left.length > 4096) return false;
  let difference = left.length ^ right.length;
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    difference |= (left[i] || 0) ^ (right[i] || 0);
  }
  return difference === 0;
}

function allowedOrigin(request, env) {
  const origin = request.headers.get("Origin");
  const allowed = (env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return origin && allowed.includes(origin) ? origin : null;
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function serverId(env) {
  if (!env.DATHOST_SERVER_ID)
    throw new Error("DatHost server ID is not configured");
  return encodeURIComponent(env.DATHOST_SERVER_ID);
}

function accountHeaders(env) {
  if (!env.DATHOST_EMAIL || !env.DATHOST_PASSWORD)
    throw new Error("DatHost credentials are not configured");
  const credentials = bytesToBase64(
    encoder.encode(`${env.DATHOST_EMAIL}:${env.DATHOST_PASSWORD}`),
  );
  const headers = {
    Authorization: `Basic ${credentials}`,
    Accept: "application/json",
  };
  if (env.DATHOST_ACCOUNT_EMAIL)
    headers["Account-Email"] = env.DATHOST_ACCOUNT_EMAIL;
  return headers;
}

async function dathost(path, method, env) {
  const response = await fetch(`${API_ROOT}${path}`, {
    method,
    headers: accountHeaders(env),
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`DatHost returned HTTP ${response.status}`);
  return response.status === 204 ? null : response.json();
}

async function dathostConsole(line, env) {
  const form = new FormData();
  form.set("line", line);
  const response = await fetch(
    `${API_ROOT}/game-servers/${serverId(env)}/console`,
    {
      method: "POST",
      headers: accountHeaders(env),
      body: form,
      signal: AbortSignal.timeout(15000),
    },
  );
  if (!response.ok) throw new Error(`DatHost returned HTTP ${response.status}`);
}

async function dathostConsoleLines(env) {
  const response = await fetch(
    `${API_ROOT}/game-servers/${serverId(env)}/console?max_lines=500`,
    {
      method: "GET",
      headers: accountHeaders(env),
      signal: AbortSignal.timeout(15000),
    },
  );
  if (!response.ok) throw new Error(`DatHost returned HTTP ${response.status}`);
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = text.split(/\r?\n/);
  }
  if (Array.isArray(payload)) return payload.map(String);
  if (payload && typeof payload === "object") {
    const lines = payload.lines || payload.console || payload.backlog;
    if (Array.isArray(lines)) return lines.map(String);
  }
  if (typeof payload === "string") return payload.split(/\r?\n/);
  throw new Error("DatHost console backlog format is not recognized");
}

function parseConsolePlayers(lines) {
  const headerIndex = lines.findLastIndex((line) =>
    /\buserid\b.*\buniqueid\b/i.test(line),
  );
  if (headerIndex < 0) return { available: false, players: [] };

  const players = [];
  const rowPattern = /#\s*(\d+)\s+"((?:[^"\\]|\\.)*)"\s+(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)/;
  for (const line of lines.slice(headerIndex + 1)) {
    const match = line.match(rowPattern);
    if (!match) {
      if (players.length) break;
      continue;
    }
    const [, userId, rawName, uniqueId, connected, ping, , state] = match;
    if (!/^(STEAM_|\[U:\d+:)/i.test(uniqueId)) continue;
    players.push({
      id: userId,
      name: rawName.replace(/\\"/g, '"').replace(/\\\\/g, "\\"),
      connected,
      ping: Number(ping),
      state,
    });
  }
  return { available: true, players };
}

async function getConnectedPlayers(env) {
  await dathostConsole("status", env);
  for (let attempt = 0; attempt < 4; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const result = parseConsolePlayers(await dathostConsoleLines(env));
    if (result.available) return result;
  }
  return { available: false, players: [] };
}

function serverState(server) {
  const rawStatus = [server.status, server.state].find(
    (value) => typeof value === "string",
  );
  const status = rawStatus?.toLowerCase() || "unknown";
  const runningFlag = [server.running, server.on, server.is_running].find(
    (value) => typeof value === "boolean",
  );
  const runningStates = new Set([
    "running",
    "started",
    "online",
    "active",
    "starting",
    "booting",
    "restarting",
    "stopping",
    "shutting_down",
  ]);
  const stoppedStates = new Set([
    "stopped",
    "offline",
    "off",
    "terminated",
    "shutdown",
  ]);
  const transitionalStates = new Set([
    "starting",
    "booting",
    "restarting",
    "stopping",
    "shutting_down",
  ]);
  const known =
    runningFlag !== undefined ||
    runningStates.has(status) ||
    stoppedStates.has(status);
  const running = runningFlag ?? runningStates.has(status);
  return {
    status:
      status === "unknown" && runningFlag !== undefined
        ? running
          ? "running"
          : "stopped"
        : status,
    running,
    transitioning: transitionalStates.has(status),
    known,
  };
}

function currentMap(server) {
  const entries = Array.isArray(server.status)
    ? server.status
    : server.status && typeof server.status === "object"
      ? Object.entries(server.status).map(([key, value]) => ({ key, value }))
      : [];
  const mapKeys = new Set([
    "map",
    "mapname",
    "currentmap",
    "level",
    "currentlevel",
  ]);
  const mapEntry = entries.find((entry) => {
    if (typeof entry.key !== "string") return false;
    return mapKeys.has(entry.key.toLowerCase().replace(/[^a-z0-9]/g, ""));
  });
  const value = server.current_map || server.map || mapEntry?.value;
  if (typeof value !== "string" || !value.trim()) return null;
  const normalized = value.trim();
  const mapToken = normalized
    .replace(/\\/g, "/")
    .split("/")
    .at(-1)
    .replace(/\.(bsp|vpk)$/i, "");
  const match = MAPS.find((map) => {
    const presetToken = map.line.split(" ").at(-1);
    return (
      presetToken.toLowerCase() === mapToken.toLowerCase() ||
      map.key.endsWith(`:${mapToken}`) ||
      map.label.toLowerCase() === mapToken.toLowerCase()
    );
  });
  return {
    key: match?.key || null,
    label: match?.label || normalized,
    value: normalized,
  };
}

function statusEntry(server, names) {
  const wanted = new Set(
    names.map((name) => name.toLowerCase().replace(/[^a-z0-9]/g, "")),
  );
  const entries = Array.isArray(server.status)
    ? server.status
    : server.status && typeof server.status === "object"
      ? Object.entries(server.status).map(([key, value]) => ({ key, value }))
      : [];
  return entries.find(
    (entry) =>
      typeof entry.key === "string" &&
      wanted.has(entry.key.toLowerCase().replace(/[^a-z0-9]/g, "")),
  )?.value;
}

function serverUptime(server) {
  const value = statusEntry(server, [
    "uptime",
    "server_uptime",
    "uptime_seconds",
  ]);
  if (typeof value === "number" && Number.isFinite(value) && value >= 0)
    return Math.floor(value);
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (/^\d+(\.\d+)?$/.test(text)) return Math.floor(Number(text));
  const clock = text.match(/^(\d+):([0-5]?\d):([0-5]?\d)$/);
  if (clock)
    return Number(clock[1]) * 3600 + Number(clock[2]) * 60 + Number(clock[3]);
  const parts = [...text.matchAll(/(\d+)\s*(d|h|m|s)/gi)];
  if (!parts.length) return null;
  const units = { d: 86400, h: 3600, m: 60, s: 1 };
  return parts.reduce(
    (sum, [, amount, unit]) => sum + Number(amount) * units[unit.toLowerCase()],
    0,
  );
}

async function handle(request, env) {
  const origin = allowedOrigin(request, env);
  if (!origin) return json({ error: "Origin is not allowed" }, 403);
  const cors = corsHeaders(origin);
  if (request.method === "OPTIONS")
    return new Response(null, { status: 204, headers: cors });

  const url = new URL(request.url);
  if (url.pathname === "/api/login" && request.method === "POST") {
    if (!env.CONTROL_PASSPHRASE || !env.SESSION_SECRET)
      return json({ error: "Worker secrets are not configured" }, 503, cors);
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "Invalid JSON" }, 400, cors);
    }
    if (
      !body ||
      typeof body !== "object" ||
      !sameSecret(
        typeof body.passphrase === "string" ? body.passphrase : "",
        env.CONTROL_PASSPHRASE,
      )
    )
      return json({ error: "Incorrect passphrase" }, 401, cors);
    return json(
      {
        token: await issueToken(env.SESSION_SECRET),
        expiresIn: TOKEN_LIFETIME_SECONDS,
      },
      200,
      cors,
    );
  }

  if (![
    "/api/status",
    "/api/maps",
    "/api/players",
    "/api/action",
  ].includes(url.pathname))
    return json({ error: "Not found" }, 404, cors);
  if (!env.SESSION_SECRET)
    return json({ error: "Worker secrets are not configured" }, 503, cors);
  const authorization = request.headers.get("Authorization") || "";
  const token = authorization.startsWith("Bearer ")
    ? authorization.slice(7)
    : "";
  if (!(await validToken(token, env.SESSION_SECRET)))
    return json({ error: "Session expired; sign in again" }, 401, cors);

  try {
    const id = serverId(env);
    if (url.pathname === "/api/maps" && request.method === "GET") {
      return json(
        {
          maps: MAPS.map(({ key, label, category, size, good, note }) => ({
            key,
            label,
            category,
            size: size || null,
            good: Boolean(good),
            note: note || null,
          })),
        },
        200,
        cors,
      );
    }

    if (url.pathname === "/api/players" && request.method === "GET") {
      const result = await getConnectedPlayers(env);
      if (!result.available)
        return json(
          { error: "Could not read the live player list from the server console" },
          502,
          cors,
        );
      return json(
        { players: result.players, checkedAt: new Date().toISOString() },
        200,
        cors,
      );
    }

    if (url.pathname === "/api/status" && request.method === "GET") {
      const server = await dathost(`/game-servers/${id}`, "GET", env);
      const state = serverState(server);
      const players = Number.isInteger(server.players_online)
        ? server.players_online
        : Array.isArray(server.players)
          ? server.players.length
          : Number.isInteger(server.players)
            ? server.players
            : null;
      const address =
        typeof server.ip === "string" && server.ip
          ? `${server.ip}${Number.isInteger(server.ports?.game) ? `:${server.ports.game}` : ""}`
          : null;
      return json(
        {
          ...state,
          map: currentMap(server),
          players,
          address,
          uptimeSeconds: serverUptime(server),
          checkedAt: new Date().toISOString(),
        },
        200,
        cors,
      );
    }

    if (url.pathname === "/api/action" && request.method === "POST") {
      let body;
      try {
        body = await request.json();
      } catch {
        return json({ error: "Invalid JSON" }, 400, cors);
      }
      if (!body || typeof body !== "object")
        return json({ error: "Invalid action" }, 400, cors);

      if (body.action === "disconnect_player") {
        const playerId = typeof body.playerId === "string" ? body.playerId : "";
        if (!/^\d{1,6}$/.test(playerId))
          return json({ error: "Invalid player session ID" }, 400, cors);
        const live = await getConnectedPlayers(env);
        if (!live.available)
          return json({ error: "Could not verify the current player list" }, 502, cors);
        const player = live.players.find((candidate) => candidate.id === playerId);
        if (!player)
          return json({ error: "That player is no longer connected" }, 409, cors);
        await dathostConsole(
          `kickid ${player.id} "Disconnected by server admin"`,
          env,
        );
        return json(
          { ok: true, action: "disconnect_player", playerId: player.id },
          200,
          cors,
        );
      }

      if (Object.hasOwn(CONSOLE_PRESETS, body.action)) {
        await dathostConsole(CONSOLE_PRESETS[body.action], env);
        return json({ ok: true, action: body.action }, 200, cors);
      }
      if (Object.hasOwn(CONFIG_PRESETS, body.action)) {
        for (const line of CONFIG_PRESETS[body.action])
          await dathostConsole(line, env);
        return json({ ok: true, action: body.action }, 200, cors);
      }
      if (body.action === "change_map") {
        const map =
          typeof body.mapKey === "string" ? MAP_BY_KEY.get(body.mapKey) : null;
        if (!map)
          return json(
            { error: "Select a map from the provided list" },
            400,
            cors,
          );
        await dathostConsole(map.line, env);
        return json(
          { ok: true, action: "change_map", map: map.key },
          200,
          cors,
        );
      }

      const actions = { start: "start", stop: "stop", restart: "restart" };
      const action = actions[body.action];
      if (!action)
        return json({ error: "Unsupported server action" }, 400, cors);
      await dathost(`/game-servers/${id}/${action}`, "POST", env);
      return json({ ok: true, action }, 200, cors);
    }
    return json({ error: "Method not allowed" }, 405, cors);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Request failed";
    const status = message.includes("not configured") ? 503 : 502;
    return json({ error: message }, status, cors);
  }
}

export default { fetch: handle };
