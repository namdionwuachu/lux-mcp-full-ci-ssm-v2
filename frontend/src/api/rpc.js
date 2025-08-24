// frontend/src/api/rpc.js
const baseRaw = import.meta.env.VITE_LUX_API || "";
const base = baseRaw.replace(/\/+$/, "") + "/mcp";

console.log("[Lux] VITE_LUX_API =", baseRaw, "→ final MCP URL =", base);

function rpc(method, params) {
  return { jsonrpc: "2.0", id: crypto.randomUUID(), method, params };
}

export async function rpcCall(method, params) {
  const res = await fetch(base, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-correlation-id": crypto.randomUUID(),
    },
    body: JSON.stringify(rpc(method, params)),
  });

  // Read raw text so we can log helpful errors
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch {}

  if (!res.ok) {
    console.error("MCP HTTP error:", res.status, text);
    throw new Error(`HTTP ${res.status}: ${text || "(no body)"}`);
  }
  if (data.error) {
    console.error("MCP JSON-RPC error:", data.error);
    throw new Error(`${data.error.code}: ${data.error.message}`);
  }
  return data.result ?? data;
}

