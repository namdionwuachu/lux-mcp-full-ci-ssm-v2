// frontend/src/components/HotelCard.jsx
import { useState } from "react";

export default function HotelCard({ hotel = {} }) {
  // ---- Prefer normalized fields, fall back to raw/legacy
  const name =
    hotel.name ||
    hotel.title ||
    hotel.property?.name ||
    "Hotel";

  const address =
    hotel.address ||
    hotel.location_note ||
    hotel.location?.address ||
    null;

  const city =
    hotel.city ||
    hotel.location?.city ||
    hotel.property?.address?.city ||
    null;

  const stars =
    toNum(hotel.stars) ??
    toNum(hotel.rating?.stars) ??
    toNum(hotel.class) ??
    toNum(hotel.starRating) ??
    null;

  const rating =
    toNum(hotel.rating) ??
    toNum(hotel.rating?.value) ??
    toNum(hotel.reviewScore) ??
    toNum(hotel.score) ??
    toNum(hotel.guestRating) ??
    null;

  // price: normalized `price` or common raw fields
  const price =
    toNum(hotel.price) ??
    toNum(hotel.est_price_gbp) ??
    toNum(hotel.est_price) ??
    toNum(hotel.price?.total) ??
    toNum(hotel.total) ??
    null;

  const currency =
    (hotel.currency ||
      hotel.price?.currency ||
      (hotel.est_price_gbp != null ? "GBP" : null) ||
      "GBP").toUpperCase();

  // images: prefer normalized thumbnail, else typical arrays
  const images = compact([
    hotel.thumbnail,
    ...(Array.isArray(hotel.images) ? hotel.images : []),
    ...(Array.isArray(hotel.photos) ? hotel.photos.map(p => p?.url || p).filter(Boolean) : []),
    ...(Array.isArray(hotel.media) ? hotel.media.map(m => m?.url || m).filter(Boolean) : []),
  ]);

  const hasImages = images.length > 0;
  const [mainIdx, setMainIdx] = useState(0);

  const displayAddress = compact([address, city]).join(", ") || null;

  // URL: provider/url if given, otherwise Google Maps
  const mapsHref =
    hotel.url ||
    `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
      compact([name, displayAddress]).join(" ")
    )}`;

  return (
    <article className="rounded-2xl border shadow-sm overflow-hidden bg-white">
      {/* Primary image */}
      <div className="aspect-[16/10] bg-gray-100">
        {hasImages ? (
          <img
            src={images[Math.min(mainIdx, images.length - 1)]}
            alt={`${name} photo ${Math.min(mainIdx, images.length - 1) + 1}`}
            className="h-full w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="h-full w-full flex items-center justify-center text-gray-400">
            No image
          </div>
        )}
      </div>

      <div className="p-4 space-y-2">
        {/* Title → link */}
        <h3 className="text-lg font-semibold leading-tight">
          <a
            href={mapsHref}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
            aria-label={`Open ${name} in Google Maps`}
          >
            {name}
          </a>
        </h3>

        {/* Meta */}
        <div className="text-sm text-gray-600 space-y-1">
          {displayAddress && <div className="truncate">{displayAddress}</div>}
          <div className="flex items-center gap-3">
            {stars != null && <span>★ {stars}</span>}
            {rating != null && <span>⭐ {Number(rating).toFixed(1)}</span>}
            {price != null && <span>{formatPrice(price, currency)}</span>}
          </div>
        </div>

        {/* Mini gallery if >1 image */}
        {hasImages && images.length > 1 && (
          <div className="mt-2 flex gap-2 overflow-x-auto">
            {images.slice(0, 6).map((src, idx) => (
              <button
                key={src + idx}
                onClick={() => setMainIdx(idx)}
                className={`h-14 w-20 flex-shrink-0 rounded-md overflow-hidden border ${
                  idx === mainIdx ? "ring-2 ring-blue-500" : "border-gray-200"
                }`}
                aria-label={`Show image ${idx + 1}`}
              >
                <img
                  src={src}
                  alt={`${name} thumbnail ${idx + 1}`}
                  className="h-full w-full object-cover"
                  loading="lazy"
                />
              </button>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

/* ------------ helpers ------------ */

function compact(arr) {
  return (arr || []).filter(Boolean);
}

function toNum(v) {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function formatPrice(val, currency = "GBP") {
  if (val == null) return null;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(val);
  } catch {
    // Fallback if currency code is unknown in current locale/runtime
    return `${currency} ${val}`;
  }
}
