import { normalizeSearchResponse } from "./normalize";

const BASE_URL = import.meta.env.VITE_LUX_API; // from .env.local or CI env

export async function searchHotels(payload = {}) {
  if (!BASE_URL) throw new Error("VITE_LUX_API is not set");

  const res = await fetch(`${BASE_URL}/hotels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const text = await res.text();
  if (!res.ok) throw new Error(`Search failed: ${res.status} ${text}`);

  const json = text ? JSON.parse(text) : {};
  return normalizeSearchResponse(json);
}

