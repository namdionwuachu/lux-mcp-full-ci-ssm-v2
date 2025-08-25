// src/api/searchHotels.js
import { normalizeSearchResponse } from "./normalize";
import { callTool } from "./rpc"; // wraps JSON-RPC {method:"tools/call", params:{name, arguments}}

/**
 * Unified hotels search:
 * - If payload.query exists -> "plan" (Planner / Jamba)
 * - Else -> "hotel_search" with structured args (city_code required)
 *
 * @param {{
 *   query?: string,
 *   stay?: {
 *     check_in: string,
 *     check_out: string,
 *     city_code: string,          // IATA city code, e.g. "PAR", "LON"
 *     adults?: number,
 *     max_price_gbp?: number,
 *     wants_indoor_pool?: boolean
 *   },
 *   currency?: string             // e.g. "GBP"
 * }} payload
 */
export async function searchHotels(payload = {}) {
  // Prevent ambiguous mixed requests
  if (payload.query && payload.stay) {
    throw new Error("Send either { query } (Planner) OR { stay, currency } (Structured), not both.");
  }

  // 1) Natural-language planner route
  if (payload.query && String(payload.query).trim()) {
    let planned;
    try {
      planned = await callTool("plan", { query: String(payload.query).trim() });
    } catch (err) {
      throw new Error(`Planner error: ${err?.message || err}`);
    }
    return normalizeSearchResponse(planned);
  }

  // 2) Structured direct search route
  const stay = payload.stay ?? {};
  const check_in  = String(stay.check_in  ?? "").trim();
  const check_out = String(stay.check_out ?? "").trim();
  const city_code = String(stay.city_code ?? "").trim().toUpperCase();

  // naive check: YYYY-MM-DD
  const iso = /^\d{4}-\d{2}-\d{2}$/;
  if (check_in && !iso.test(check_in))  throw new Error("check_in must be YYYY-MM-DD");
  if (check_out && !iso.test(check_out)) throw new Error("check_out must be YYYY-MM-DD");

  if (!check_in || !check_out) {
    throw new Error("Missing dates: provide stay.check_in and stay.check_out (YYYY-MM-DD).");
  }
  if (!city_code) {
    throw new Error("Missing stay.city_code (e.g., 'PAR' for Paris, 'LON' for London).");
  }

  const adultsRaw = stay.adults ?? 2;
  const adults = Number.isFinite(Number(adultsRaw))
    ? Math.max(1, Math.trunc(Number(adultsRaw)))
    : 2;

  const wants_indoor_pool =
    typeof stay.wants_indoor_pool === "boolean" ? stay.wants_indoor_pool : undefined;

  const max_price_gbp =
    stay.max_price_gbp != null ? Number(stay.max_price_gbp) : undefined;

  const currency = (payload.currency || import.meta?.env?.VITE_DEFAULT_CURRENCY || "GBP").toUpperCase();

  const args = {
    stay: {
      check_in,
      check_out,
      city_code,
      ...(adults ? { adults } : {}),
      ...(typeof wants_indoor_pool === "boolean" ? { wants_indoor_pool } : {}),
      ...(Number.isFinite(max_price_gbp) ? { max_price_gbp } : {}),
    },
    currency,
  };

  let raw;
  try {
    raw = await callTool("hotel_search", args);
  } catch (err) {
    throw new Error(`Hotel search error: ${err?.message || err}`);
  }

  return normalizeSearchResponse(raw);
}
