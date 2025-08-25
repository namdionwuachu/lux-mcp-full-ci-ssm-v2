// src/api/rpc.js
// JSON‑RPC client for your MCP Lambda

// Resolve final MCP endpoint:
// - If VITE_LUX_API already ends with /mcp, use it (trim trailing slash)
// - Else, append /mcp to whatever is provided (origin or base URL)
const baseRaw = import.meta.env.VITE_LUX_API || "";
const MCP_BASE = /\/mcp\/?$/.test(baseRaw)
  ? baseRaw.replace(/\/+$/, "")
  : (baseRaw.replace(/\/+$/, "") + "/mcp");

if (import.meta.env?.DEV) {
  console.log("[Lux] VITE_LUX_API =", baseRaw, "→ MCP =", MCP_BASE);
}

// ---- Low-level helpers ----
function rpc(method, params) {
  return { jsonrpc: "2.0", id: crypto.randomUUID(), method, params };
}

async function postJSON(url, payload, { timeoutMs = 20000, headers = {} } = {}) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(new Error("Request timed out")), timeoutMs);

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-correlation-id": crypto.randomUUID(),
        ...headers,
      },
      body: JSON.stringify(payload),
      signal: ac.signal,
    });

    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`);
    }

    if (!res.ok) {
      const msg = data?.error?.message || text || `HTTP ${res.status}`;
      throw new Error(msg);
    }

    return data;
  } finally {
    clearTimeout(timer);
  }
}

// ---- Public API ----

/**
 * Call an MCP tool (normal path).
 * Wraps the JSON-RPC envelope that the Lambda expects:
 *   method: "tools/call"
 *   params: { name, arguments }
 *
 * Example:
 *   await callTool("hotel_search", { stay: {...}, currency: "GBP" })
 *   await callTool("plan", { query: "3 nights in PAR" })
 */
export async function callTool(name, args = {}, options = {}) {
  const payload = rpc("tools/call", { name, arguments: args });
  const data = await postJSON(MCP_BASE, payload, options);

  if (data?.error) {
    const { code, message } = data.error;
    throw new Error(`MCP ${name} error ${code}: ${message}`);
  }

  // Unwrap common content shape
  const item = data?.result?.content?.[0];
  if (!item) throw new Error("Empty MCP content");

  if (Object.prototype.hasOwnProperty.call(item, "json")) return item.json;
  if (Object.prototype.hasOwnProperty.call(item, "text")) return item.text;

  // Fallbacks (defensive)
  return data?.result ?? item ?? data;
}

/**
 * Generic JSON-RPC call — ADVANCED/DEBUG ONLY.
 * App code should NOT use this for normal tools; prefer callTool().
 * Useful for things like "tools/list", "ping", etc. if supported by backend.
 *
 * Example:
 *   await rpcCall("tools/list", {})
 */
export async function rpcCall(method, params, options = {}) {
  const payload = rpc(method, params);
  const data = await postJSON(MCP_BASE, payload, options);
  return data?.result ?? data;
}

// Optional helper for tests/logging
export function getMcpBase() {
  return MCP_BASE;
}
