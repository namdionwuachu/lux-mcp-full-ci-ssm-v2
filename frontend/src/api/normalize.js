// Robust normalizer that accepts legacy + newer shapes.
// It tries, in order, to find hotels in: api.hotels | api.results | api.top | api.candidates | api.hits
// Price fields it understands: est_price_gbp | est_price (+ currency) | price.amount (+ price.currency) | best_total
// Images fields: images | photo_urls | photos[].url
// URL: url | link | deep_link (fallback to maps search in the card)
function pickArray(...candidates) {
  for (const c of candidates) if (Array.isArray(c) && c.length) return c;
  return [];
}
function pick(obj, path, def) {
  try {
    return path.split('.').reduce((o, k) => (o && k in o ? o[k] : undefined), obj) ?? def;
  } catch { return def; }
}
function coerceNumber(n) {
  const v = typeof n === "string" ? Number(n) : n;
  return Number.isFinite(v) ? v : undefined;
}

export function normalizeSearchResponse(api) {
  if (!api || typeof api !== "object") {
    return { hotels: [], narrative: "", notes: [], use_responder: false };
  }

  // ------------- narrative / notes / version -------------
  const narrative =
    pick(api, "narrative") ??
    pick(api, "responder.narrative") ??
    "";

  // notes can be string or array (planner notes)
  const notesRaw =
    pick(api, "notes") ??
    pick(api, "plan.notes") ??
    pick(api, "planner.notes");
  const notes = Array.isArray(notesRaw) ? notesRaw : (notesRaw ? [notesRaw] : []);

  // optional: read api version if backend provides it (future-proofing)
  const apiVersion =
    pick(api, "version") ??
    pick(api, "plan.api_version") ??
    pick(api, "meta.api_version");

  // ------------- choose the hotel list -------------
  const hotelsSource = pickArray(
    pick(api, "hotels"),
    pick(api, "results"),
    pick(api, "top"),
    pick(api, "candidates"),
    pick(api, "hits")
  );

  const hotels = hotelsSource.map((h, i) => {
    const name =
      h.name ??
      h.title ??
      `Hotel ${i + 1}`;

    // address & location
    const address =
      h.address ??
      h.location_note ??
      pick(h, "location.address") ??
      pick(h, "vicinity") ??
      "";

    const lat = coerceNumber(h.lat ?? pick(h, "location.lat"));
    const lon = coerceNumber(h.lon ?? pick(h, "location.lon"));

    // rating / stars: prefer float rating, fallback to integer stars
    const rating = coerceNumber(h.rating ?? h.stars ?? pick(h, "user_rating"));

    // price + currency (support multiple shapes)
    const priceAmount =
      coerceNumber(h.est_price_gbp) ??
      coerceNumber(h.est_price) ??
      coerceNumber(pick(h, "price.amount")) ??
      coerceNumber(h.best_total);

    const currency =
      (h.est_price_gbp != null ? "GBP" : undefined) ??
      h.currency ??
      pick(h, "price.currency") ??
      pick(api, "currency") ?? // sometimes returned top-level
      undefined;

    // url fields (backend may provide a deep link, or we leave blank to fallback in UI)
    const url = h.url ?? h.link ?? h.deep_link ?? "";

    // images in various shapes
    const images =
      (Array.isArray(h.images) && h.images.length ? h.images :
        (Array.isArray(h.photo_urls) && h.photo_urls.length ? h.photo_urls :
          (Array.isArray(h.photos) ? h.photos.map(p => p.url).filter(Boolean) : undefined)
        )
      ) || undefined;

    // id: stable-ish
    const id =
      h.id ??
      h.hotel_id ??
      `${i}-${name.toLowerCase().replace(/\s+/g, "-").slice(0, 40)}`;

    return {
      id,
      name,
      address,
      rating,
      est_price: priceAmount,
      currency,
      url,
      images,
      lat,
      lon,
      // carry-through optional flags if present
      passes_budget: h.passes_budget,
      pool_bonus: h.pool_bonus,
    };
  });

  return {
    hotels,
    narrative,
    notes,
    use_responder: Boolean(narrative),
    api_version: apiVersion,
  };
}

