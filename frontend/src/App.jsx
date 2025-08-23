import "./index.css";
import { useState } from "react";
import SearchResults from "./components/SearchResults";
import { searchHotels } from "./api/searchHotels";

export default function App() {
  const [city, setCity] = useState("London");
  const [checkIn, setCheckIn] = useState("2025-09-01");
  const [checkOut, setCheckOut] = useState("2025-09-05");
  const [budget, setBudget] = useState(200);
  const [indoorPool, setIndoorPool] = useState(true);
  const [useResponder, setUseResponder] = useState(true);

  const [data, setData] = useState({ hotels: [] });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const doSearch = async () => {
    try {
      setLoading(true);
      setErr("");
      const result = await searchHotels({
        city,
        stay: { check_in: checkIn, check_out: checkOut },
        budget_max: Number(budget),
        use_responder: useResponder,
        preferences: indoorPool ? ["indoor_pool"] : [],
      });
      setData(result); // normalized -> {hotels, narrative, notes, use_responder}
    } catch (e) {
      setErr(e.message || "Search failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="p-6 max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Lux Search — Hotels</h1>

      {/* Controls */}
      <section className="rounded-xl border bg-white p-4 shadow-sm grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">City</span>
          <input className="border rounded-lg p-2" value={city} onChange={(e) => setCity(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">Check-in</span>
          <input type="date" className="border rounded-lg p-2" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">Check-out</span>
          <input type="date" className="border rounded-lg p-2" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">Max nightly budget</span>
          <input type="number" min="0" className="border rounded-lg p-2" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={indoorPool} onChange={(e) => setIndoorPool(e.target.checked)} />
          <span>Prefer indoor pool</span>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={useResponder} onChange={(e) => setUseResponder(e.target.checked)} />
          <span>Use AI narrative (Responder)</span>
        </label>

        <div className="sm:col-span-3">
          <button onClick={doSearch} className="mt-1 inline-flex items-center justify-center rounded-lg bg-black px-4 py-2 text-white hover:opacity-90">
            Search
          </button>
          {!import.meta.env.VITE_LUX_API && (
            <span className="ml-3 text-red-600 text-sm">Set VITE_LUX_API in .env.local</span>
          )}
        </div>
      </section>

      {err && <div className="rounded-md border border-red-300 bg-red-50 px-4 py-2 text-red-800">{err}</div>}

      <SearchResults data={data} isLoading={loading} />
    </main>
  );
}

