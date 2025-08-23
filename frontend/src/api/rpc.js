// frontend/src/api/rpc.js

const baseRaw = import.meta.env.VITE_LUX_API || "";
// Always normalize so it ends with /mcp
const base = baseRaw.replace(/\/+$/, "") + "/mcp";

function rpc(method, params) {
  return { jsonrpc: "2.0", id: crypto.randomUUID(), method, params };
}

export async function rpcCall(method, params) {
  const url = base;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-correlation-id": crypto.randomUUID(),
    },
    body: JSON.stringify(rpc(method, params)),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${JSON.stringify(data)}`);
  if (data.error) throw new Error(`${data.error.code}: ${data.error.message}`);
  return data.result ?? data;
}

