// frontend/src/api/normalize.js

export function normalizeSearchResponse(input) {
  if (!input) return empty();
  // 🔓 Unwrap JSON-RPC envelopes like: result.content[0].json
  const env = input?.result?.content?.[0]?.json ?? input;


  // Pull from many common shapes
  const candidates = [
    env.items,
    env.results,
    env.offers,

    // nested hotel collections
    env.hotels?.hotels,
    env.hotels?.items,
    env.hotels?.results,

    // planner-style outputs
    env.top,
    env.candidates,

    // misc
    env.hotels,
    env.data,
    env.payload,
    env.steps && flattenSteps(env.steps),
  ].filter(Boolean);

  const flat = candidates.flatMap(a => (Array.isArray(a) ? a : []));
  const sourceItems = flat.length
    ? flat
    : (looksLikeHotel(env) || looksLikeOffer(env)) ? [env] : [];

  const items = uniqByIdOrName(
    sourceItems
      .map(coerceItem)      // <— RESTORED helper
      .map(normalizeItem)
      .filter(Boolean)
  );

  const meta = extractMeta(env);
  meta.counts = { pools: flat.length, items: items.length };
  // Expose budget filter counts nicely if present
  const budget = env?.meta?.budget_filter || null;
  if (budget) {
    meta.budget = budget;                      // existing you already had
    meta.counts.under_budget = budget.under_budget ?? null;
    if (typeof env?.meta?.total_in === "number") {
       meta.counts.total_in = env.meta.total_in;
    }
  }
  return {
    items,
    meta,
    hotels: items,                     // compatibility alias
    narrative: meta?.narrative ?? "",
  };
}

/* ----------------- helpers ----------------- */

function empty() {
  return { items: [], meta: {}, hotels: [], narrative: "" };
}

function flattenSteps(steps) {
  const out = [];
  for (const s of steps || []) {
    const r = s?.result || s?.output || s?.data || null;
    const pools = [
      r?.offers, r?.items, r?.results, r?.hotels, r?.data,
      r?.hotels?.hotels, r?.hotels?.items, r?.hotels?.results,
      r?.top, r?.candidates,
    ];
    for (const pool of pools) if (Array.isArray(pool)) out.push(...pool);
  }
  return out.length ? out : undefined;
}

function looksLikeHotel(x = {}) {
  return !!(x.name || x.hotelName || x.propertyName || x.hotel || x.property);
}

function looksLikeOffer(x = {}) {
  return !!(x.est_price || x.total || x.amount || x.rate || x.nightlyPrice || x.pricing || x.offer || x.room);
}

// *** RESTORED ***
function coerceItem(x = {}) {
  if (x.data && (looksLikeHotel(x.data) || looksLikeOffer(x.data))) return x.data;
  if (x.result && (looksLikeHotel(x.result) || looksLikeOffer(x.result))) return x.result;
  if (x.hotel) return x.hotel;
  if (x.offer) return x.offer;
  return x;
}

function normalizeItem(x = {}) {
  // Name / property
  const name =
    x.name || x.hotelName || x.propertyName || x.title ||
    x.property?.name || x.hotel?.name || null;

  // ID
  const id =
    x.id || x.hotelId || x.propertyId || x.offerId || x.reference ||
    (name ? slug(`${name}-${x.checkIn || x.check_in || ""}-${x.checkOut || x.check_out || ""}`) : null);

  // Price & currency
  const price =
    num(x.est_price) ??                                // ← NEW backend field
    num(x.est_price_gbp) ??                            // ← prefer normalized per-night
    num(x.price?.total) ?? num(x.price?.amount) ?? num(x.price) ??
    num(x.total) ?? num(x.amount) ?? num(x.rate?.amount) ??
    num(x.nightlyPrice) ?? num(x.pricing?.total) ?? null;
    

  const currency =
    x.currency ||
    x.price?.currency ||
    x.rate?.currency ||
    x.pricing?.currency ||
    (x.est_price_gbp != null ? "GBP" : null) ||
    "GBP";
    

  // Address / city
  const address =
    joinParts([
      x.address?.line1 || x.address?.address1 || x.address?.street,
      x.address?.line2 || x.address?.address2,
      x.address?.postalCode || x.address?.zip,
    ]) || x.address?.freeform || x.address?.full || x.location?.address || null;

  const city =
    x.address?.city || x.city || x.location?.city || x.property?.address?.city || null;

  // Geo
  const lat =
    num(x.lat) ?? num(x.location?.lat) ?? num(x.location?.latitude) ??
    num(x.coordinates?.lat) ?? num(x.coordinates?.latitude) ?? null;

  const lng =
    num(x.lon) ?? num(x.lng) ?? num(x.location?.lng) ?? num(x.location?.lon) ??
    num(x.location?.longitude) ?? num(x.coordinates?.lng) ?? num(x.coordinates?.lon) ??
    num(x.coordinates?.longitude) ?? null;

  // Quality
  const stars = num(x.stars) ?? num(x.rating?.stars) ?? num(x.class) ?? num(x.starRating) ?? null;
  const rating = num(x.rating?.value) ?? num(x.reviewScore) ?? num(x.score) ?? num(x.guestRating) ?? null;

  // Media (fix Google photoreference + strip quotes)
  const thumbnail = pickThumbnailFrom(x);

  const source = x._source || x.source || (hasHotelSearchFields(x) ? "hotel_search" : "plan");

  if (!name && !id) return null;

  return { id, name, price, est_price: price, currency, address, city, lat, lng, stars, rating, thumbnail, source, raw: x };
}

function hasHotelSearchFields(x = {}) {
  return !!(x.check_in || x.checkIn || x.check_in_date || x.dateRange || x.room || x.rate);
}

function num(v) {
  if (v == null) return null;
  let s = String(v).trim();
  // Strip wrapping quotes: "123.45" or '123.45'
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    s = s.slice(1, -1).trim();
  }
  // Pull first numeric token (handles "£420", "420 GBP", etc.)
  const m = s.match(/-?\d+(?:[.,]\d+)?/);
  if (!m) return null;
  const n = parseFloat(m[0].replace(",", "."));
  return Number.isFinite(n) ? n : null;
}


function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
}

function joinParts(arr) {
  return arr.filter(Boolean).join(", ") || null;
}

function fixGooglePhotoUrl(u) {
  if (!u) return u;
  try {
    u = String(u).trim();
    // strip wrapping quotes
    if ((u.startsWith('"') && u.endsWith('"')) || (u.startsWith("'") && u.endsWith("'"))) {
      u = u.slice(1, -1);
    }
    // correct Google Places param
    if (u.includes("/maps.googleapis.com/maps/api/place/photo") && u.includes("photo_reference=")) {
      u = u.replace("photo_reference=", "photoreference=");
    }
  } catch {}
  return u;
}

function pickThumbnailFrom(x = {}) {
  const candidates = [
    x.thumbnail,
    x.image,
    Array.isArray(x.images) ? x.images[0] : null,
    Array.isArray(x.photos) ? (x.photos[0]?.url || x.photos[0]) : null,
    Array.isArray(x.media) ? (x.media[0]?.url || x.media[0]) : null,
  ].filter(Boolean);

  const first = candidates[0];
  if (!first) return null;

  if (typeof first === "object") {
    const objUrl = first.url || first.src || first.href || first.link || null;
    return fixGooglePhotoUrl(objUrl);
  }
  return fixGooglePhotoUrl(String(first));
}

function uniqByIdOrName(arr = []) {
  const map = new Map();
  for (const x of arr) {
    if (!x) continue;
    const key =
      (x.id && String(x.id).toLowerCase()) ||
      (x.name && String(x.name).toLowerCase()) ||
      null;
    if (key && !map.has(key)) map.set(key, x);
    if (!key) map.set(`__idx_${map.size}`, x);
  }
  return Array.from(map.values());
}

function extractMeta(input = {}) {
  const narrative =
    input.narrative ||
    input.summary ||
    input.text ||
    input.message ||
    input.hotels?.narrative ||
    (Array.isArray(input.notes) ? input.notes.join(" • ") : "") ||
    "";
  const agent = input.agent || input.tool || input.type || input.workflow || null;
  return { narrative, agent };
}

