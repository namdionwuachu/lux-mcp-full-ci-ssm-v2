// frontend/src/api/searchHotels.js
import { callTool } from "./rpc";
import { normalizeSearchResponse } from "./normalize";

// Helper to normalize city input to 3-letter codes
const toCityCode = (input = "") => {
  const s = String(input).trim().toUpperCase();
  const map = {
    "LONDON": "LON",
    "PARIS": "PAR",
    "NEW YORK": "NYC",
    "LOS ANGELES": "LAX",
    "DUBAI": "DXB",
    "SINGAPORE": "SIN",
  };
  if (s.length === 3) return s;
  return map[s] || s.slice(0, 3);
};


/**
 * Call MCP "hotel_search" and normalize the response for the UI.
 * Returns: { items, hotels, narrative, meta, _raw }
 */
async function runHotelSearch(toolArgs, { timeoutMs = 20000 } = {}) {
  const res = await callTool("hotel_search", toolArgs, { timeoutMs });
  // rpc.js sometimes returns JSON-RPC shape: { content: [{ json: {...} }] }
  const raw = res?.content?.[0]?.json ?? res ?? {};
  const normalized = normalizeSearchResponse(raw);
  // Keep the raw payload for debugging in the UI if needed
  return { ...normalized, _raw: raw };
}

/**
 * Normalize dates to YYYY-MM-DD (accepts DD/MM/YYYY, YYYY-MM-DD, ISO with time)
 */
function toYMD(input) {
  if (!input || typeof input !== "string") return "";
  const s = input.trim();
  if (!s) return "";

  // DD/MM/YYYY or D/M/YYYY
  if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(s)) {
    const [d, m, y] = s.split("/").map(String);
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }

  // ISO with time
  if (/^\d{4}-\d{1,2}-\d{1,2}T/.test(s)) {
    return s.slice(0, 10);
  }

  // YYYY-MM-DD or YYYY-M-D
  if (/^\d{4}-\d{1,2}-\d{1,2}$/.test(s)) {
    const [y, m, d] = s.split("-");
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }

  // Fallback: return as-is (backend is tolerant)
  return s;
}

function hasLikeDate(s) {
  return typeof s === "string" && /\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\/\d{1,2}\/\d{4}/.test(s);
}

/**
 * Main entry.
 * If payload has { query } without { stay }, uses QUERY path (LLM/planner style).
 * Otherwise uses STRUCTURED path with explicit params.
 */
async function searchHotels(payload = {}) {
  console.log("=== SEARCH HOTELS CALLED ===");
  const hasQuery = !!payload.query;
  const hasStay  = !!payload.stay || !!payload.city_code || !!payload.adults || !!payload.currency;
  console.log("Has query:", hasQuery);
  console.log("Has stay:", hasStay);

  // ---- QUERY PATH (freeform) ----
  if (hasQuery && !payload.stay) {
    console.log("Taking path: QUERY");
    const toolArgs = { query: payload.query };
    const out = await runHotelSearch(toolArgs, { timeoutMs: 30000 });
    console.log("[searchHotels] normalized (QUERY):", out);
    return out;
  }

  // ---- STRUCTURED PATH ----
  console.log("Taking path: STRUCTURED");

  // Extract + normalize structured fields
  const stay = payload.stay ?? {};
  const checkIn  = toYMD(stay.check_in ?? payload.check_in ?? "");
  const checkOut = toYMD(stay.check_out ?? payload.check_out ?? "");

  if (!hasLikeDate(checkIn)) throw new Error(`Check-in date is required (got "${stay.check_in ?? payload.check_in ?? ""}"). Use DD/MM/YYYY or YYYY-MM-DD.`);
  if (!hasLikeDate(checkOut)) throw new Error(`Check-out date is required (got "${stay.check_out ?? payload.check_out ?? ""}"). Use DD/MM/YYYY or YYYY-MM-DD.`);

  const city_code = String(payload.city_code ?? stay.city_code ?? "").trim().toUpperCase();
  if (!city_code) throw new Error("Provide city_code (e.g., PAR or LON).");

  const adultsRaw = payload.adults ?? stay.adults ?? 2;
  const adults = Number.isFinite(Number(adultsRaw)) ? Math.max(1, Math.trunc(Number(adultsRaw))) : 2;

  const currency =
    String(payload.currency || stay.currency || import.meta?.env?.VITE_DEFAULT_CURRENCY || "GBP")
      .trim()
      .toUpperCase();

  const toolArgs = {
  stay: {
    check_in: checkIn,
    check_out: checkOut,
    city_code: toCityCode(city_code || ""),       // ✅ move inside stay
    adults,
    currency,
    wants_indoor_pool: !!(payload.wantsIndoorPool ?? stay.wants_indoor_pool), // ✅ boolean flag
    max_price_gbp: Number(payload.maxPrice ?? stay.max_price_gbp ?? 0) || null, // ✅ budget key the backend expects
  },
  top_n: payload.topN ?? 5,
  use_responder: true,
};

  console.log("[OUT toolArgs.stay]", JSON.stringify(toolArgs.stay, null, 2));

  console.log("Structured call args:", toolArgs);

  const out = await runHotelSearch(toolArgs, { timeoutMs: 20000 });
  console.log("[searchHotels] normalized (STRUCTURED):", out);
  return out;
}

export { searchHotels };
export default searchHotels;
