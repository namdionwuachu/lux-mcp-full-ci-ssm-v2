import HotelCard from "./HotelCard";

/**
 * Renders the Responder Summary (if present), Planner notes, and a grid of hotels.
 * Expects data shape: { hotels: Hotel[], narrative?, notes?, use_responder? }
 */
export default function SearchResults({ data, isLoading }) {
  if (isLoading) return <div>Loading…</div>;
  const hotels = data?.hotels ?? data?.results ?? [];

  return (
    <div className="space-y-4">
      {/* Summary (Responder) */}
      {data?.use_responder && data?.narrative && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="text-xl font-semibold mb-2">Summary</h2>
          <p className="text-gray-800 whitespace-pre-wrap">{data.narrative}</p>
        </section>
      )}

      {/* Planner notes */}
      {Array.isArray(data?.notes) && data.notes.length > 0 && (
        <div className="text-sm text-gray-600">
          <span className="font-medium">Planner notes: </span>
          {data.notes.join(" • ")}
        </div>
      )}

      {/* Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {hotels.map((h) => (
          <HotelCard key={h.id} hotel={h} />
        ))}
      </div>
    </div>
  );
}

