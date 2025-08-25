// frontend/src/components/SearchResults.jsx
import HotelCard from "./HotelCard";

/**
 * Renders optional narrative + planner notes, then a grid of hotels.
 * Expected data shape (post-normalization):
 *   {
 *     hotels: Hotel[] | { hotels: Hotel[] } | Hotel[][],
 *     narrative?: string,
 *     notes?: string[]
 *   }
 */
export default function SearchResults({ data, isLoading }) {
  if (isLoading) return <div>Loading…</div>;

  // Be robust to a few possible shapes
  const hotels =
    data?.hotels?.hotels || // { hotels: { hotels: [] } }
    data?.hotels ||         // { hotels: [] }
    data?.results ||        // legacy
    [];

  const flatHotels = Array.isArray(hotels) ? hotels : [];

  return (
    <div className="space-y-4">
      {/* Narrative (from Planner/Responder) */}
      {data?.narrative && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="text-xl font-semibold mb-2">Summary</h2>
          <p className="text-gray-800 whitespace-pre-wrap">{data.narrative}</p>
        </section>
      )}

      {/* Planner notes (optional) */}
      {Array.isArray(data?.notes) && data.notes.length > 0 && (
        <div className="text-sm text-gray-600">
          <span className="font-medium">Planner notes: </span>
          {data.notes.join(" • ")}
        </div>
      )}

      {/* Results */}
      {flatHotels.length === 0 ? (
        <div className="rounded-md border border-gray-200 bg-white p-4 text-gray-700">
          No results yet — try adjusting your query or dates.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {flatHotels.map((h, i) => (
            <HotelCard key={h.id ?? `${h.name ?? "hotel"}-${i}`} hotel={h} />
          ))}
        </div>
      )}
    </div>
  );
}

