// src/api/searchHotels.js
import { normalizeSearchResponse } from "./normalize";
import { callTool } from "./rpc"; // wraps JSON-RPC {method:"tools/call", params:{name, arguments}}

/**
 * Search hotels via MCP.
 * - If payload.query exists -> uses "plan"
 * - Else -> uses "hotel_search" with structured args
 *
 * @param {{
 *   query?: string,
 *   stay?: {
 *     check_in?: string,
 *     check_out?: string,
 *     city_code?: string,
 *     city?: string,                // legacy fallback
 *     adults?: number,
 *     max_price_gbp?: number,
 *     wants_indoor_pool?: boolean
 *   },
 *   // legacy fallbacks (top-level):
 *   check_in?: string, check_out?: string, city_code?: string, city?: string,
 *   adults?: number, max_price_gbp?: number, budget_max?: number,
 *   wants_indoor_pool?: boolean, preferences?: string[],
 *   currency?: string
 * }} payload
 */
export async function searchHotels(payload = {}) {
  // --- 1) Natural language route (planner) ---
  if (payload.query && String(payload.query).trim()) {
    const planned = await callTool("plan", { query: String(payload.query).trim() });
    return normalizeSearchResponse(planned);
  }

  // --- 2) Structured route (hotel_search) ---
  const stayIn = payload.stay || {};

  const check_in  = (payload.check_in  ?? stayIn.check_in  ?? "").trim();
  const check_out = (payload.check_out ?? stayIn.check_out ?? "").trim();

  // Accept "PAR" or legacy city name; backend expects code
  const city_code_raw = (payload.city_code ?? stayIn.city_code ?? payload.city ?? "").trim();
  const city_code = city_code_raw.toUpperCase();

  const adults = Number(
    payload.adults ??
    stayIn.adults ??
    2
  );

  // Only include wants_indoor_pool if provided or inferred; otherwise omit
  const wants_pool_input =
    payload.wants_indoor_pool ??
    stayIn.wants_indoor_pool ??
    (Array.isArray(payload.preferences) && payload.preferences.includes("indoor_pool") ? true : undefined);

  // Map budget fields; omit if not provided
  const max_price_gbp_val =
    payload.max_price_gbp ??
    stayIn.max_price_gbp ??
    payload.budget_max ??
    undefined;

  const currency = (payload.currency || "GBP").toUpperCase();

  // Basic validations (keep friendly)
  if (!check_in || !check_out) {
    throw new Error("Missing dates: provide check_in and check_out (YYYY-MM-DD).");
  }
  if (!city_code) {
    throw new Error("Missing city_code (e.g., 'PAR' for Paris, 'LON' for London).");
  }

  const args = {
    stay: {
      check_in,
      check_out,
      city_code,
      ...(Number.isFinite(adults) && adults > 0 ? { adults } : {}),
      ...(typeof wants_pool_input === "boolean" ? { wants_indoor_pool: wants_pool_input } : {}),
      ...(max_price_gbp_val != null ? { max_price_gbp: Number(max_price_gbp_val) } : {}),
    },
    currency,
  };

  try {
    const raw = await callTool("hotel_search", args);
    return normalizeSearchResponse(raw);
  } catch (e) {
    console.error("hotel_search failed:", e);
    throw e;
  }
}


