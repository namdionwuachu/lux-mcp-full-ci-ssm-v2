// frontend/src/components/HotelCard.jsx
import { useState } from "react";

/* ===== Helpers ===== */
const FIX_PARAM_FROM = "photo_reference=";
const FIX_PARAM_TO   = "photoreference=";

function fixGooglePhotoUrl(u) {
  if (!u) return u;
  u = String(u).trim();
  // strip wrapping quotes
  if ((u.startsWith('"') && u.endsWith('"')) || (u.startsWith("'") && u.endsWith("'"))) {
    u = u.slice(1, -1);
  }
  // correct Google Places param
  if (u.includes("/maps.googleapis.com/maps/api/place/photo") && u.includes(FIX_PARAM_FROM)) {
    u = u.replace(FIX_PARAM_FROM, FIX_PARAM_TO);
  }
  return u;
}

function dedupe(arr = []) {
  const s = new Set();
  const out = [];
  for (const x of arr) {
    const k = String(x);
    if (!s.has(k)) { s.add(k); out.push(k); }
  }
  return out;
}

function gatherImages(hotel = {}) {
  const pool = [];
  if (hotel.thumbnail) pool.push(hotel.thumbnail);
  if (Array.isArray(hotel.images)) pool.push(...hotel.images);
  if (Array.isArray(hotel.raw?.images)) pool.push(...hotel.raw.images);
  if (Array.isArray(hotel.raw?.photos)) {
    for (const p of hotel.raw.photos) {
      const u = typeof p === "string" ? p : (p?.url || p?.href || p?.src || null);
      if (u) pool.push(u);
    }
  }
  return dedupe(pool.filter(Boolean).map(fixGooglePhotoUrl));
}

function compact(arr) { return (arr || []).filter(Boolean); }

function toNum(v) {
  if (v == null || v === '') return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function parsePrice(v) {
  if (v == null) return null;
  let s = String(v).trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    s = s.slice(1, -1).trim();
  }
  const m = s.match(/-?\d+(?:[.,]\d+)?/);
  if (!m) return null;
  const n = parseFloat(m[0].replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function formatPrice(val, currency = "GBP") {
  if (val == null) return null;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "GBP" }).format(val);
  } catch {
    return `${currency} ${Number(val).toFixed(2)}`;
  }
}

/* ===== Component ===== */
export default function HotelCard({ hotel = {}, index }) {
  const [imageError, setImageError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [mainIdx, setMainIdx] = useState(0);
  const [forceSrc, setForceSrc] = useState(null);

  // Basic hotel info
  const name = hotel.name || hotel.title || hotel.property?.name || `Hotel ${index + 1}`;
  const address = hotel.address || hotel.location_note || hotel.location?.address || null;
  const city = hotel.city || hotel.location?.city || hotel.property?.address?.city || null;
  const displayAddress = compact([address, city]).join(", ") || null;

  const stars = toNum(hotel.stars) ?? toNum(hotel.rating?.stars) ?? toNum(hotel.class) ?? null;
  const rating = toNum(hotel.rating) ?? toNum(hotel.rating?.value) ?? toNum(hotel.reviewScore) ?? toNum(hotel.score) ?? toNum(hotel.guestRating) ?? null;

  // Price (normalized or raw fallback) - supports new backend shape
  const price =
    // prefer proper numbers without re-parsing
    (typeof hotel?.price === "number" ? hotel.price : undefined) ??
    (typeof hotel?.est_price === "number" ? hotel.est_price : undefined) ??
    (typeof hotel?.raw?.est_price === "number" ? hotel.raw.est_price : undefined) ??
    (typeof hotel?.raw?.est_price_gbp === "number" ? hotel.raw.est_price_gbp : undefined) ??
    (typeof hotel?.bestOffer?.price?.total === "number" ? hotel.bestOffer.price.total : undefined) ??
    (typeof hotel?.raw?.price?.total === "number" ? hotel.raw.price.total : undefined) ??
    // fall back to parsing strings if needed
    parsePrice(hotel?.price) ??
    parsePrice(hotel?.est_price) ??
    parsePrice(hotel?.raw?.est_price) ??
    parsePrice(hotel?.raw?.est_price_gbp) ??
    parsePrice(hotel?.bestOffer?.price?.total) ??
    parsePrice(hotel?.raw?.price?.total) ??
    null;

  const currency = (
    hotel?.currency ||
    hotel?.raw?.currency ||
    hotel?.bestOffer?.price?.currency ||
    hotel?.raw?.price?.currency ||
    "GBP"
  ).toUpperCase();


  // Images (fix URLs -> photoreference, strip quotes)
  const images = gatherImages(hotel);
  const hasImages = images.length > 0 && !imageError;

  //debug block
  // After: const images = gatherImages(hotel); const hasImages = ...
  if (import.meta?.env?.MODE === 'development') {
    console.log("CARD DEBUG", {
      name,
      priceInput: hotel.price,
      priceFromRaw: hotel.raw?.est_price_gbp,
      parsedPrice: price,
      firstImage: images[0],
      hasPhotoreference: images[0]?.includes("photoreference="),
      wrappedQuoteStart: images[0]?.startsWith('"') || images[0]?.startsWith("'"),
    });
  }

  const mapsHref = hotel.url || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(compact([name, displayAddress]).join(" "))}`;

  const handleImageError = (e) => {
    const failedUrl = e.target.src || "";
    console.warn(`Image failed to load for ${name}:`, {
      url: failedUrl,
      urlLength: failedUrl.length,
      hadWrongParam: failedUrl.includes(FIX_PARAM_FROM)
    });
    // One retry if the param was wrong
    if (failedUrl.includes(FIX_PARAM_FROM)) {
      const fixed = fixGooglePhotoUrl(failedUrl);
      if (fixed && fixed !== failedUrl) {
        setForceSrc(fixed);
        return;
      }
    }
    setImageError(true);
  };

  const handleImageLoad = () => setImageLoaded(true);

  // Dev-only debug
  if (import.meta?.env?.MODE === 'development') {
    console.log(`%cHotelCard ${index} DATA:`, 'color: red; font-weight: bold;', {
      name, price, currency, thumbnail: hotel.thumbnail,
      legacy_raw_est_gbp: hotel.raw?.est_price_gbp,
      new_est_price: hotel.est_price,
      raw_est_price: hotel.raw?.est_price,
      bestOfferTotal: hotel.bestOffer?.price?.total,
      rawPriceTotal: hotel.raw?.price?.total,
      firstImage: images[0],
      fixedParam: images[0]?.includes('photoreference='),
      startsWithQuote: images[0]?.startsWith('"') || images[0]?.startsWith("'"),
    });
  }

  return (
    <article className="rounded-2xl border shadow-sm overflow-hidden bg-white hover:shadow-md transition-shadow">
      <div className="aspect-[16/10] bg-gray-100 relative">
        {hasImages ? (
          <>
            <img
              src={forceSrc || images[Math.min(mainIdx, images.length - 1)]}
              alt={`${name} photo ${Math.min(mainIdx, images.length - 1) + 1}`}
              className="h-full w-full object-cover"
              loading="lazy"
              decoding="async"
              onError={handleImageError}
              onLoad={handleImageLoad}
            />
            {!imageLoaded && !imageError && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-50">
                <div className="animate-pulse bg-gray-300 rounded-full w-8 h-8"></div>
              </div>
            )}
          </>
        ) : (
          <div className="h-full w-full flex items-center justify-center text-gray-500 bg-gradient-to-br from-gray-50 to-gray-100">
            <div className="text-center">
              <div className="text-2xl mb-2">🏨</div>
              <div className="text-sm font-medium">{name}</div>
            </div>
          </div>
        )}
      </div>

      <div className="p-4 space-y-3">
        <h3 className="text-lg font-semibold leading-tight text-gray-800">
          <a href={mapsHref} target="_blank" rel="noopener noreferrer" className="hover:underline hover:text-blue-600 transition-colors" aria-label={`Open ${name} in Google Maps`}>
            {name}
          </a>
        </h3>

        {displayAddress && <div className="text-sm text-gray-600 truncate">{displayAddress}</div>}

        <div className="flex items-center gap-3 flex-wrap text-sm">
          {stars != null && (<span className="flex items-center gap-1 text-yellow-600">★ <span className="font-medium">{stars}</span></span>)}
          {rating != null && (<span className="flex items-center gap-1 text-green-600">⭐ <span className="font-medium">{Number(rating).toFixed(1)}</span></span>)}
          {price != null ? (
            <span className="font-bold text-blue-600 text-lg bg-blue-50 px-3 py-1 rounded-lg ml-auto">
              {formatPrice(price, currency)}
            </span>
          ) : (
            <span className="text-gray-500 text-sm bg-gray-100 px-2 py-1 rounded ml-auto">Price unavailable</span>
          )}
        </div>

        {hasImages && images.length > 1 && (
          <div className="flex gap-2 overflow-x-auto pb-2">
            {images.slice(0, 6).map((src, idx) => (
              <button
                key={`${src}-${idx}`}
                onClick={() => setMainIdx(idx)}
                className={`h-14 w-20 flex-shrink-0 rounded-md overflow-hidden border-2 transition-all ${
                  idx === mainIdx ? "ring-2 ring-blue-500 border-blue-500 scale-105" : "border-gray-200 hover:border-gray-300"
                }`}
                aria-label={`Show image ${idx + 1}`}
              >
                <img
                  src={src}
                  alt={`${name} thumbnail ${idx + 1}`}
                  className="h-full w-full object-cover"
                  loading="lazy"
                  decoding="async"
                  onError={(e) => {
                    e.currentTarget.style.visibility = "hidden";
                    e.currentTarget.parentElement.style.display = "none";
                  }}
                />
              </button>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

