const API_ROOT = "https://dathost.com/api/0.1";
const TOKEN_LIFETIME_SECONDS = 15 * 60;
const encoder = new TextEncoder();

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
    ) {
      return json({ error: "Incorrect passphrase" }, 401, cors);
    }
    return json(
      {
        token: await issueToken(env.SESSION_SECRET),
        expiresIn: TOKEN_LIFETIME_SECONDS,
      },
      200,
      cors,
    );
  }

  if (!["/api/status", "/api/action"].includes(url.pathname))
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
    if (url.pathname === "/api/status" && request.method === "GET") {
      const server = await dathost(`/game-servers/${id}`, "GET", env);
      const state = serverState(server);
      const players = Array.isArray(server.players)
        ? server.players.length
        : Number.isInteger(server.players)
          ? server.players
          : null;
      return json(
        { ...state, players, checkedAt: new Date().toISOString() },
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
      const actions = { start: "start", stop: "stop", restart: "restart" };
      const action =
        body && typeof body === "object" ? actions[body.action] : null;
      if (body?.action === "warmup_end") {
        await dathostConsole("mp_warmup_end", env);
        return json({ ok: true, action: "warmup_end" }, 200, cors);
      }
      if (!action)
        return json(
          { error: "Action must be start, stop, or restart" },
          400,
          cors,
        );
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
