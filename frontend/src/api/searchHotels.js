
import { normalizeSearchResponse } from "./normalize";
import { rpcCall } from "./rpc.js";

// Supports either free-text query (planner) or structured search
export async function searchHotels(payload = {}) {
  if (payload.query) {
    const planned = await rpcCall("plan", { query: payload.query });
    return normalizeSearchResponse(planned);
  }

  const {
    city,
    check_in,
    check_out,
    adults = 2,
    currency = "GBP",
  } = payload;

  const raw = await rpcCall("hotel_search", {
    city,
    check_in,
    check_out,
    adults,
    currency,
  });

  return normalizeSearchResponse(raw);
}

