import { normalizeSearchResponse } from "./normalize";
import { rpcCall } from "./rpc.js";

// Small helper to call an MCP tool
async function callTool(name, args) {
  return rpcCall("tools/list", {}).then(() =>
    rpcCall("tools/call", { name, arguments: args })
  );
}

// Supports either free‑text query (planner) or structured search
export async function searchHotels(payload = {}) {
  // 1) Planner flow (free‑text)
  if (payload.query) {
    // Tool is named "planner_plan"
    const planned = await callTool("planner_plan", { query: payload.query });
    return normalizeSearchResponse(planned);
  }

  // 2) Structured hotel search (hotel_search)
  // Accept both the older shape and the new MCP shape
  const stay = payload.stay || {};
  const check_in = payload.check_in || stay.check_in;
  const check_out = payload.check_out || stay.check_out;

  // Optional fields
  const city_code =
    payload.city_code ??
    stay.city_code ??
    payload.city ?? // fallback if you were passing "London" before
    undefined;

  const adults =
    payload.adults ??
    stay.adults ??
    (typeof payload.adults === "number" ? payload.adults : 2);

  const wants_indoor_pool =
    payload.wants_indoor_pool ??
    stay.wants_indoor_pool ??
    (Array.isArray(payload.preferences)
      ? payload.preferences.includes("indoor_pool")
      : undefined);

  const max_price_gbp =
    payload.max_price_gbp ??
    stay.max_price_gbp ??
    payload.budget_max ??
    undefined;

  const args = {
    stay: {
      check_in,
      check_out,
      ...(city_code ? { city_code } : {}),
      ...(adults ? { adults: Number(adults) } : {}),
      ...(typeof wants_indoor_pool === "boolean" ? { wants_indoor_pool } : {}),
      ...(max_price_gbp ? { max_price_gbp: Number(max_price_gbp) } : {}),
    },
  };

  const raw = await callTool("hotel_search", args);
  return normalizeSearchResponse(raw);
}

