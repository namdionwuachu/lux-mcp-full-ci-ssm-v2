// frontend/src/components/SearchResults.jsx
import HotelCard from "./HotelCard";

export default function SearchResults({ data, isLoading }) {
  if (isLoading) return <div>Loading…</div>;

  // Prefer normalized items; fall back to common shapes
  const hotels =
    (Array.isArray(data?.items) && data.items.length ? data.items : null) ??
    (Array.isArray(data?.hotels) && data.hotels.length ? data.hotels : null) ??
    (Array.isArray(data?.hotels?.hotels) && data.hotels.hotels.length ? data.hotels.hotels : null) ??
    [];

  // Debug (optional)
  if (import.meta?.env?.MODE === "development") {
    console.log("SearchResults → count:", hotels.length);
    console.log("First item:", hotels[0]);
  }

  return (
    <div className="space-y-4">
      {data?.narrative ? (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="text-xl font-semibold mb-2">Summary</h2>
          <p className="text-gray-800 whitespace-pre-wrap">{data.narrative}</p>
        </section>
      ) : null}

      {hotels.length === 0 ? (
        <div className="rounded-md border border-gray-200 bg-white p-4 text-gray-700">
          No results yet — try adjusting your query or dates.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {hotels.map((h, i) => (
            <HotelCard key={h.id ?? `${h.name ?? "hotel"}-${i}`} hotel={h} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
