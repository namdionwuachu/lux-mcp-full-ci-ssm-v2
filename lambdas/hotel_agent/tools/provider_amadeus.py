# tools/provider_amadeus.py
"""Amadeus API client via Secrets Manager OAuth; generic city/geo search; per-night normalization."""
import os
import time
import json
import requests
import boto3
from typing import Dict, Any, List, Optional
from datetime import date as _date

BASE_URL = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com")
SECRET_NAME = os.getenv("AMADEUS_SECRET_NAME", "/lux/amadeus/credentials")

_secrets = boto3.client("secretsmanager")
_tok = {"t": None, "exp": 0}


def _creds() -> Dict[str, str]:
    d = json.loads(_secrets.get_secret_value(SecretId=SECRET_NAME)["SecretString"])
    return {"id": d["client_id"], "sec": d["client_secret"]}


def _token() -> str:
    now = time.time()
    if _tok["t"] and now < _tok["exp"] - 30:
        return _tok["t"]
    c = _creds()
    r = requests.post(
        f"{BASE_URL}/v1/security/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": c["id"], "client_secret": c["sec"]},
        timeout=12,
    )
    r.raise_for_status()
    j = r.json()
    _tok.update({"t": j["access_token"], "exp": now + int(j.get("expires_in", 1800))})
    return _tok["t"]


def _hdrs() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Accept": "application/json"}


def _nights(ci: Optional[str], co: Optional[str]) -> int:
    try:
        return max((_date.fromisoformat(co) - _date.fromisoformat(ci)).days, 1)
    except Exception:
        return 3


# Small fallback map; expand as needed or pass stay.city_code directly.
CITY_TO_IATA = {
    "paris": "PAR",
    "london": "LON",
    "rome": "ROM",
    "new york": "NYC",
    "barcelona": "BCN",
    "amsterdam": "AMS",
}


def _city_code(city: Optional[str], default: str = "PAR") -> str:
    if not city:
        return default
    return CITY_TO_IATA.get(str(city).strip().lower(), default)


def _best_total_gbp(offers: List[dict]) -> Optional[float]:
    best = None
    for off in offers or []:
        p = off.get("price", {})
        if p.get("currency") == "GBP":
            amt = p.get("total") or p.get("base")
            try:
                v = float(amt)
                if v > 0 and (best is None or v < best):
                    best = v
            except Exception:
                pass
    return best


def _norm_amenities(hotel: dict, offers: List[dict]) -> List[str]:
    am = hotel.get("amenities") or []
    for off in offers or []:
        am += off.get("amenities", []) or []
    seen, out = set(), []
    for a in am:
        s = str(a)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:20]


def search_hotels(stay: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Inputs used:
      - stay.city (str) or stay.city_code (str)
      - Optional: stay.lat, stay.lon, stay.radius_km (float)  # for neighborhood targeting
      - stay.check_in, stay.check_out (YYYY-MM-DD)
      - stay.adults (int)
    Filtering (4★ + gym, etc.) is done in tools.hotels_filter.
    """
    ci, co = stay.get("check_in"), stay.get("check_out")
    nights = _nights(ci, co)
    adults = stay.get("adults", 2)

    params: Dict[str, Any] = {
        "adults": adults,
        "checkInDate": ci,
        "checkOutDate": co,
        "currency": "GBP",
        "roomQuantity": 1,
        "bestRateOnly": "true",
    }

    # Prefer geo (neighborhood) if provided; else use city code.
    lat = stay.get("lat")
    lon = stay.get("lon")
    radius_km = stay.get("radius_km", 5)
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        params.update({"latitude": lat, "longitude": lon, "radius": radius_km})
    else:
        params["cityCode"] = stay.get("city_code") or _city_code(stay.get("city"))

    r = requests.get(f"{BASE_URL}/v3/shopping/hotel-offers", headers=_hdrs(), params=params, timeout=15)
    print(f"Amadeus request URL: {r.url}")
    print(f"Amadeus response status: {r.status_code}")
    print(f"Amadeus response headers: {dict(r.headers)}")
    print(f"Amadeus response body: {r.text}")

    r.raise_for_status()
    data = r.json()

    out: List[Dict[str, Any]] = []
    for item in data.get("data", []):
        hotel = item.get("hotel", {}) or {}
        geo = hotel.get("geoCode", {}) or {}
        offers = item.get("offers", []) or []

        total_gbp = _best_total_gbp(offers)
        per_night = (total_gbp / nights) if (total_gbp is not None and nights > 0) else None

        rating = hotel.get("rating")
        try:
            stars = float(rating) if rating is not None else 0.0
        except Exception:
            stars = 0.0

        out.append({
            "name": hotel.get("name"),
            "stars": stars,  # let filters enforce >=4
            "url": "",       # map provider URLs here if available
            "location_note": stay.get("neighborhood") or stay.get("city") or "",
            "amenities": _norm_amenities(hotel, offers),
            "est_price_gbp": per_night,  # PER-NIGHT normalized for UI & budget agent
            "lat": geo.get("latitude"),
            "lon": geo.get("longitude"),
            # pool_bonus is determined later by hotels_filter based on user preference
        })

    return out

