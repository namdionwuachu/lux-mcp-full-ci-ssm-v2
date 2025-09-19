// src/App.jsx
import "./index.css";
import { useState } from "react";
import SearchResults from "./components/SearchResults";
import { searchHotels } from "./api/searchHotels";

// ADD THIS FUNCTION at the top
const getCurrencyForCityCode = (cityCode) => {
  const cityToCurrencyMap = {
    // Europe
    'LON': 'GBP',  // London
    'PAR': 'EUR',  // Paris  
    'ROM': 'EUR',  // Rome
    'BCN': 'EUR',  // Barcelona
    'AMS': 'EUR',  // Amsterdam
    'BER': 'EUR',  // Berlin
    'VIE': 'EUR',  // Vienna
    'ZUR': 'CHF',  // Zurich
    
    // Middle East
    'DXB': 'AED',  // Dubai
    'DOH': 'QAR',  // Doha
    'RUH': 'SAR',  // Riyadh
    
    // North America  
    'NYC': 'USD',  // New York
    'LAX': 'USD',  // Los Angeles
    'MIA': 'USD',  // Miami
    'YYZ': 'CAD',  // Toronto
    
    // Asia
    'NRT': 'JPY',  // Tokyo
    'SIN': 'SGD',  // Singapore
    'HKG': 'HKD',  // Hong Kong
    'BKK': 'THB',  // Bangkok
  };
  
  return cityToCurrencyMap[cityCode?.toUpperCase()] || 'GBP';
};

export default function App() {
  const [city, setCity] = useState("London");       // Planner: city name ok. Structured: expects IATA city code (e.g., LON, PAR).
  const [checkIn, setCheckIn] = useState("2025-09-01");
  const [checkOut, setCheckOut] = useState("2025-09-05");
  const [budget, setBudget] = useState(200);
  const [indoorPool, setIndoorPool] = useState(true);

  // Toggle: true = Planner (agentic), false = Structured (direct)
  const [usePlanner, setUsePlanner] = useState(true);

  const [data, setData] = useState({ hotels: [], narrative: "" });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const doSearch = async () => {
    try {
      setLoading(true);
      setErr("");

      if (usePlanner) {
        // ---- Planner route: send ONLY { query }
        const parts = [
          `Find a 4-star hotel in ${city}`.trim(),
          `${checkIn} to ${checkOut}`,
          `2 adults`,
          Number.isFinite(Number(budget)) && Number(budget) > 0 ? `under £${Number(budget)}/night` : "",
          indoorPool ? "prefer indoor pool" : ""
        ].filter(Boolean);

        const query = parts.join(", ").replace(/\s+,/g, ",");

        const result = await searchHotels({
          stay: {
            check_in: checkIn,
            check_out: checkOut,
            city_code: city.toUpperCase(),      // searchHotels.js will normalize with toCityCode()
            adults: 2,
            currency: getCurrencyForCityCode(city.toUpperCase()), // CHANGED: was "GBP"
            max_price_gbp: Number(budget) || null,
            wants_indoor_pool: !!indoorPool,
          },
          topN: 5,
        });

        // normalizeSearchResponse returns { hotels, narrative }
        setData({
          hotels: result.hotels || [],
          narrative: result.narrative || ""
        });
        return;
      }

      // ---- Structured route: send { stay:{...}, currency }
      // NOTE: Structured path requires an IATA city code (e.g., LON, PAR).
      const city_code = (city || "").trim().toUpperCase();
      const isIataCityCode = /^[A-Z]{3}$/.test(city_code);
      if (!isIataCityCode) {
        throw new Error(
          "Structured mode requires a 3‑letter IATA city code (e.g., LON for London, PAR for Paris). Switch to Planner mode or enter a valid code."
        );
      }

      const payload = {
        stay: {
          check_in: checkIn,
          check_out: checkOut,
          city_code,
          adults: 2,
          max_price_gbp: Number(budget) || undefined,
          wants_indoor_pool: !!indoorPool
        },
        currency: getCurrencyForCityCode(city_code) // CHANGED: was "GBP"
      };

      const result = await searchHotels(payload);
      setData({
        hotels: result.hotels || [],
        narrative: result.narrative || ""
      });
    } catch (e) {
      setErr(e?.message || "Search failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="p-6 max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Lux Search — Hotels</h1>

      {/* Controls */}
      <section className="rounded-xl border bg-white p-4 shadow-sm grid gap-3 sm:grid-cols-3">
        {/* Mode toggle */}
        <label className="flex items-center gap-2 sm:col-span-3">
          <input
            type="checkbox"
            checked={usePlanner}
            onChange={(e) => setUsePlanner(e.target.checked)}
          />
          <span>
            Use <b>AI Planner</b> (agentic). Off = <b>Structured</b> (IATA city code).
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">
            {usePlanner ? "City (name)" : "City code (IATA, e.g., LON, PAR)"}
          </span>
          <input
            className="border rounded-lg p-2"
            value={city}
            onChange={(e) => setCity(e.target.value)}
            placeholder={usePlanner ? "Paris" : "PAR"}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">Check-in</span>
          <input
            type="date"
            className="border rounded-lg p-2"
            value={checkIn}
            onChange={(e) => setCheckIn(e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">Check-out</span>
          <input
            type="date"
            className="border rounded-lg p-2"
            value={checkOut}
            onChange={(e) => setCheckOut(e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-gray-600">Max nightly budget (£)</span>
          <input
            type="number"
            min="0"
            className="border rounded-lg p-2"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
          />
        </label>

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={indoorPool}
            onChange={(e) => setIndoorPool(e.target.checked)}
          />
          <span>Prefer indoor pool</span>
        </label>

        <div className="sm:col-span-3">
          <button
            onClick={doSearch}
            className="mt-1 inline-flex items-center justify-center rounded-lg bg-black px-4 py-2 text-white hover:opacity-90"
            disabled={loading}
          >
            {loading ? "Searching…" : "Search"}
          </button>
          {!import.meta.env.VITE_LUX_API && (
            <span className="ml-3 text-red-600 text-sm">Set VITE_LUX_API in .env.local</span>
          )}
        </div>
      </section>

      {err && (
        <div className="rounded-md border border-red-300 bg-red-50 px-4 py-2 text-red-800">
          {err}
        </div>
      )}

      <SearchResults data={data} isLoading={loading} />
    </main>
  );
}

