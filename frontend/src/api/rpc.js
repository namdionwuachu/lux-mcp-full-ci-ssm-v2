// src/api/rpc.js
// JSON‑RPC client for your MCP Lambda

// Build the final endpoint:
// - If VITE_LUX_API already ends with /mcp, use it as-is
// - Otherwise, append /mcp
const baseRaw = import.meta.env.VITE_LUX_API || "";
const base = /\/mcp\/?$/.test(baseRaw) ? baseRaw.replace(/\/+$/, "") : (baseRaw.replace(/\/+$/, "") + "/mcp");

console.log("[Lux] VITE_LUX_API =", baseRaw, "→ final MCP URL =", base);

// Low-level JSON-RPC envelope
function rpc(method, params) {
  return { jsonrpc: "2.0", id: crypto.randomUUID(), method, params };
}

// POST helper that always parses JSON (or throws with raw text for debugging)
async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-correlation-id": crypto.randomUUID(),
    },
    body: JSON.stringify(payload),
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
    console.error("MCP HTTP error:", res.status, msg);
    throw new Error(msg);
  }

  return data;
}

/**
 * Generic JSON-RPC call — for advanced cases.
 * NOTE: This sends your method verb directly. For MCP tools, prefer callTool().
 */
export async function rpcCall(method, params) {
  const payload = rpc(method, params);
  const data = await postJSON(base, payload);
  // If the server replied with classic JSON-RPC result, return it;
  // otherwise return the whole parsed body.
  return data.result ?? data;
}

/**
 * Call an MCP tool ("plan" | "hotel_search" | "budget_filter" | "responder_narrate")
 * Wraps the JSON-RPC envelope as the Lambda expects: method "tools/call",
 * params: { name, arguments }
 */
export async function callTool(name, args = {}) {
  const payload = rpc("tools/call", { name, arguments: args });
  const data = await postJSON(base, payload);

  if (data?.error) {
    const { code, message } = data.error;
    console.error("MCP JSON-RPC error:", code, message);
    throw new Error(`MCP ${name} error ${code}: ${message}`);
  }

  // Unwrap your server shape: { result: { content: [ { type, json|text } ] } }
  const item = data?.result?.content?.[0];
  if (!item) throw new Error("Empty MCP content");
  if (Object.prototype.hasOwnProperty.call(item, "json")) return item.json;
  if (Object.prototype.hasOwnProperty.call(item, "text")) return item.text;
  return item; // fallback, just in case
}

