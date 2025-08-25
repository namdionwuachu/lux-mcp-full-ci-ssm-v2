// src/api/rpc.js
// JSON‑RPC client for your MCP Lambda

const baseRaw = import.meta.env.VITE_LUX_API;
if (!baseRaw) throw new Error("VITE_LUX_API is not set");

const MCP_BASE = /\/mcp\/?$/.test(baseRaw)
  ? baseRaw.replace(/\/+$/, "")
  : (baseRaw.replace(/\/+$/, "") + "/mcp");

if (import.meta.env?.DEV) {
  console.log("[Lux] VITE_LUX_API =", baseRaw, "→ MCP =", MCP_BASE);
}

// ---- Low-level helpers ----
function rpc(method, params) {
  const id = (crypto.randomUUID?.() || String(Date.now()));
  return { jsonrpc: "2.0", id, method, params };
}

function pickContent(result) {
  // Prefer the first { json }, then { text }; fall back to result
  const items = result?.content;
  if (Array.isArray(items) && items.length) {
    const jsonItem = items.find(it => Object.prototype.hasOwnProperty.call(it, "json"));
    if (jsonItem) return jsonItem.json;
    const textItem = items.find(it => Object.prototype.hasOwnProperty.call(it, "text"));
    if (textItem) return textItem.text;
  }
  return result ?? null;
}

async function postJSON(url, payload, {
  timeoutMs = 20000,
  headers = {},
  // retry options (off by default)
  retries = 0,
  retryDelayMs = 400
} = {}) {
  let attempt = 0;
  let lastErr;

  while (attempt <= retries) {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(new Error("Request timed out")), timeoutMs);

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-correlation-id": crypto.randomUUID?.() || String(Date.now()),
          ...headers,
        },
        body: JSON.stringify(payload),
        signal: ac.signal,
      });

      const reqId = res.headers.get("x-amzn-requestid") || res.headers.get("x-request-id");
      const status = res.status;

      const text = await res.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        throw new Error(`Non-JSON response (${status})${reqId ? ` [reqId:${reqId}]` : ""}: ${text.slice(0,200)}`);
      }

      // HTTP-level error
      if (!res.ok) {
        const msg = data?.error?.message || text || `HTTP ${status}`;
        const err = new Error(`${msg}${reqId ? ` [reqId:${reqId}]` : ""}`);
        err.status = status;
        err.requestId = reqId;
        throw err;
      }

      return { data, status, requestId: reqId };
    } catch (e) {
      clearTimeout(timer);
      const isAbort = e?.name === "AbortError" || /timed out/i.test(String(e?.message || ""));
      const is5xx = e?.status && e.status >= 500 && e.status <= 599;

      lastErr = isAbort ? new Error("Request timed out") : e;

      // Retry only on 5xx if enabled
      if (attempt < retries && is5xx) {
        await new Promise(r => setTimeout(r, retryDelayMs * Math.pow(2, attempt)));
        attempt++;
        continue;
      }
      throw lastErr;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr;
}

// ---- Public API ----

export async function callTool(name, args = {}, options = {}) {
  const payload = rpc("tools/call", { name, arguments: args });
  const { data } = await postJSON(MCP_BASE, payload, options);

  // JSON-RPC error envelope
  if (data?.error) {
    const { code, message, data: errData } = data.error;
    const detail = typeof errData === "string" ? ` — ${errData}` : "";
    throw new Error(`MCP "${name}" error ${code}: ${message}${detail}`);
  }

  const result = pickContent(data?.result);
  if (!result) throw new Error("Empty MCP result content");
  return result;
}

// Advanced/Debug only
export async function rpcCall(method, params, options = {}) {
  const payload = rpc(method, params);
  const { data } = await postJSON(MCP_BASE, payload, options);
  return data?.result ?? data;
}

export function getMcpBase() {
  return MCP_BASE;
}
