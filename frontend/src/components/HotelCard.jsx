import { useState } from "react";

/**
 * Renders one hotel card.
 * Expects hotel to include: name, address?, rating?, est_price?, currency?, url?, images?
 */
export default function HotelCard({ hotel }) {
  const { name, address, rating, est_price, currency, url, images } = hotel;
  const hasImages = Array.isArray(images) && images.length > 0;
  const [mainIdx, setMainIdx] = useState(0);

  const mapsHref =
    url ??
    `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
      [name, address].filter(Boolean).join(" ")
    )}`;

  const formatPrice = (val, ccy) => {
    if (val == null) return null;
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency: ccy || "GBP" }).format(val);
    } catch {
      return `${ccy ?? ""} ${val}`;
    }
  };

  return (
    <article className="rounded-2xl border shadow-sm overflow-hidden bg-white">
      {/* Primary image */}
      <div className="aspect-[16/10] bg-gray-100">
        {hasImages ? (
          <img
            src={images[mainIdx]}
            alt={`${name} photo ${mainIdx + 1}`}
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
        {/* Title → link to Maps/provider */}
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
        <div className="text-sm text-gray-600">
          {address && <div className="truncate">{address}</div>}
          <div className="flex items-center gap-3">
            {typeof rating === "number" ? <span>⭐ {rating.toFixed(1)}</span> : null}
            {est_price != null && <span>{formatPrice(est_price, currency)}</span>}
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

