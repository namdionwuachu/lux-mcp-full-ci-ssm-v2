// frontend/src/api/normalize.js

/**
 * Normalize a variety of backend shapes (planner or direct search)
 * into a consistent structure:
 *
 * Canonical (legacy) shape:
 *   { items: [...], meta: {...} }
 *
 * Plus compatibility for newer callers:
 *   { hotels: items, narrative: meta.narrative ?? "" }
 */

export function normalizeSearchResponse(input) {
  if (!input) return empty();

  // planner outputs often contain steps with embedded search results
  // try several common locations where items/offers may live
  const candidates = [
    input.items,
    input.results,
    input.offers,
    input.hotels,
    input.data,
    input.payload,
    input.steps && flattenSteps(input.steps),
  ].filter(Boolean);

  const flat = flattenArray(candidates);

  // last resort: if no obvious array, but input itself looks like a single item
  const sourceItems = flat.length
    ? flat
    : (looksLikeHotel(input) || looksLikeOffer(input)) ? [input] : [];

  const items = sourceItems
    .map(coerceItem)     // unwrap step/data/result containers
    .map(normalizeItem)  // map to canonical fields
    .filter(Boolean);

  const meta = extractMeta(input);

  // Return both legacy + compatibility fields
  return {
    items,
    meta,
    // compatibility for callers expecting these:
    hotels: items,
    narrative: meta?.narrative ?? ""
  };
}

/* ----------------- helpers ----------------- */

function empty() {
  return { items: [], meta: {}, hotels: [], narrative: "" };
}

function flattenArray(arrays) {
  const out = [];
  for (const a of arrays) {
    if (Array.isArray(a)) out.push(...a);
  }
  return out;
}

function flattenSteps(steps) {
  // Handle shapes like [{type:"hotel_search", result:{offers:[...]}}]
  const out = [];
  for (const s of steps || []) {
    if (!s) continue;
    const r = s.result || s.output || s.data || null;
    const pools = [r?.offers, r?.items, r?.results, r?.hotels, r?.data];
    for (const pool of pools) {
      if (Array.isArray(pool)) out.push(...pool);
    }
  }
  return out.length ? out : undefined;
}

function looksLikeHotel(x = {}) {
  return !!(
    x.name ||
    x.hotelName ||
    x.propertyName ||
    x.hotel ||
    x.property
  );
}

function looksLikeOffer(x = {}) {
  return !!(
    x.price ||
    x.total ||
    x.amount ||
    x.rate ||
    x.nightlyPrice ||
    x.pricing ||
    x.offer ||
    x.room
  );
}

function coerceItem(x = {}) {
  // If planner wrapped the item like {type:"hotel", data:{...}}
  if (x.data && (looksLikeHotel(x.data) || looksLikeOffer(x.data))) return x.data;
  if (x.result && (looksLikeHotel(x.result) || looksLikeOffer(x.result))) return x.result;
  if (x.hotel) return x.hotel;
  if (x.offer) return x.offer;
  return x;
}

function normalizeItem(x = {}) {
  // Name / property
  const name =
    x.name ||
    x.hotelName ||
    x.propertyName ||
    x.title ||
    x.property?.name ||
    x.hotel?.name ||
    null;

  // ID
  const id =
    x.id ||
    x.hotelId ||
    x.propertyId ||
    x.offerId ||
    x.reference ||
    (name ? slug(`${name}-${x.checkIn || x.check_in || ""}-${x.checkOut || x.check_out || ""}`) : null);

  // Price & currency
  const price =
    num(x.price?.total) ??
    num(x.price?.amount) ??
    num(x.price) ??
    num(x.total) ??
    num(x.amount) ??
    num(x.rate?.amount) ??
    num(x.nightlyPrice) ??
    num(x.pricing?.total) ??
    null;

  const currency =
    x.price?.currency ||
    x.currency ||
    x.rate?.currency ||
    x.pricing?.currency ||
    null;

  // Address / city
  const address =
    joinParts([
      x.address?.line1 || x.address?.address1 || x.address?.street,
      x.address?.line2 || x.address?.address2,
      x.address?.postalCode || x.address?.zip,
    ]) ||
    x.address?.freeform ||
    x.address?.full ||
    x.location?.address ||
    null;

  const city =
    x.address?.city ||
    x.city ||
    x.location?.city ||
    x.property?.address?.city ||
    null;

  // Geo
  const lat =
    num(x.location?.lat) ??
    num(x.location?.latitude) ??
    num(x.coordinates?.lat) ??
    num(x.coordinates?.latitude) ??
    null;

  const lng =
    num(x.location?.lng) ??
    num(x.location?.lon) ??
    num(x.location?.longitude) ??
    num(x.coordinates?.lng) ??
    num(x.coordinates?.lon) ??
    num(x.coordinates?.longitude) ??
    null;

  // Quality signals
  const stars =
    num(x.stars) ??
    num(x.rating?.stars) ??
    num(x.class) ??
    num(x.starRating) ??
    null;

  const rating =
    num(x.rating?.value) ??
    num(x.reviewScore) ??
    num(x.score) ??
    num(x.guestRating) ??
    null;

  // Media
  const thumbnail =
    x.thumbnail ||
    x.image ||
    x.images?.[0] ||
    x.photos?.[0]?.url ||
    x.media?.[0]?.url ||
    null;

  // Source (best guess)
  const source =
    x._source ||
    x.source ||
    (hasHotelSearchFields(x) ? "hotel_search" : "plan");

  // If we didn't get a name or id, consider it unusable
  if (!name && !id) return null;

  return {
    id,
    name,
    price,
    currency,
    address,
    city,
    lat,
    lng,
    stars,
    rating,
    thumbnail,
    source,
    raw: x,
  };
}

function hasHotelSearchFields(x = {}) {
  return !!(x.check_in || x.checkIn || x.check_in_date || x.dateRange || x.room || x.rate);
}

function num(v) {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function slug(s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function joinParts(arr) {
  return arr.filter(Boolean).join(", ") || null;
}

/**
 * Extract useful metadata that callers may show in the UI.
 * This also feeds `narrative` for compatibility return.
 */
function extractMeta(input = {}) {
  // Try multiple likely keys for LLM narration / notes
  const narrative =
    input.narrative ||
    input.summary ||
    input.text ||
    input.message ||
    (Array.isArray(input.notes) ? input.notes.join(" • ") : "") ||
    "";

  // Surface any tool/agent info if present
  const agent =
    input.agent ||
    input.tool ||
    input.type ||
    input.workflow ||
    null;

  // You can add more fields here as needed (tokens, timing, trace IDs, etc.)
  return { narrative, agent };
}

