# lambdas/hotel_agent/places_enrichment.py
import os, json, logging, urllib.parse, requests, boto3

_LOG = logging.getLogger(__name__)
_LOG.setLevel(logging.INFO)

REGION = os.getenv("AWS_REGION", "us-east-1")
SECRET_NAME = os.getenv("GOOGLE_PLACES_SECRET_NAME", "/lux/google/places_api_key")
MAX_PHOTOS = int(os.getenv("MAX_PHOTOS_PER_HOTEL", "4") or "4")
ENABLE_PHOTOS = os.getenv("ENABLE_PLACES_PHOTOS", "0").lower() in ("1", "true", "yes")

# Minimal IATA city-code → city-name mapping (extend as you need)
CITY_CODE_TO_NAME = {
    "LON": "London",
    "PAR": "Paris",
    "NYC": "New York",
    "SFO": "San Francisco",
    "TYO": "Tokyo",
    "ROM": "Rome",
    "MAD": "Madrid",
    "BCN": "Barcelona",
    "AMS": "Amsterdam",
    "BER": "Berlin",
}

_ssm = boto3.client("secretsmanager", region_name=REGION)

def _read_google_key() -> str:
    try:
        s = _ssm.get_secret_value(SecretId=SECRET_NAME).get("SecretString") or ""
        try:
            j = json.loads(s)
            return (j.get("api_key") or "").strip()
        except Exception:
            return s.strip()
    except Exception as e:
        _LOG.error("Cannot read secret %s: %s", SECRET_NAME, e)
        return ""

def _http_get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=6)
    r.raise_for_status()
    return r.json()

def _text_search(query: str, key: str) -> dict | None:
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    data = _http_get(url, {"query": query, "key": key})
    status = data.get("status")
    if status != "OK":
        _LOG.info("TextSearch status=%s query=%s err=%s", status, query, data.get("error_message"))
        return None
    results = data.get("results") or []
    return results[0] if results else None

def _place_details(place_id: str, key: str) -> dict | None:
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = ",".join([
        "url","website","formatted_address","geometry/location",
        "photo","photos","name","business_status","editorial_summary"
    ])
    data = _http_get(url, {"place_id": place_id, "fields": fields, "key": key})
    status = data.get("status")
    if status != "OK":
        _LOG.info("Details status=%s place_id=%s err=%s", status, place_id, data.get("error_message"))
        return None
    return data.get("result") or {}

def _photo_url(photo_ref: str, key: str, max_w: int = 800) -> str:
    base = "https://maps.googleapis.com/maps/api/place/photo"
    qs = urllib.parse.urlencode({"maxwidth": str(max_w), "photo_reference": photo_ref, "key": key})
    return f"{base}?{qs}"

def _to_city_hint(city_code: str | None, fallback_name: str = "London") -> str:
    if not city_code:
        return fallback_name
    code = city_code.strip().upper()
    return CITY_CODE_TO_NAME.get(code, code)  # if unknown, we’ll try the code as-is

def resolve_place(hotel: dict, key: str, city_hint: str) -> dict:
    name = hotel.get("name") or hotel.get("hotel_name") or ""
    if not name:
        return hotel

    query = f"{name}, {city_hint}"
    first = _text_search(query, key)
    if not first:
        # try without the city
        first = _text_search(name, key)
        if not first:
            return hotel

    # lat/lon
    try:
        loc = (first.get("geometry") or {}).get("location") or {}
        hotel["lat"] = loc.get("lat")
        hotel["lon"] = loc.get("lng")
    except Exception:
        pass

    # details for url + photos
    place_id = first.get("place_id")
    details = _place_details(place_id, key) if place_id else None

    # url fallbacks
    url = (details or {}).get("url") or (details or {}).get("website")
    if not url:
        # last resort: keep existing or set a generic search link
        url = hotel.get("url") or f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(name)}"
    hotel["url"] = url

    # photos
    if ENABLE_PHOTOS:
        refs = []
        # take photos from details if present; otherwise textsearch may have one
        for src in ((details or {}).get("photos") or [])[:MAX_PHOTOS]:
            ref = src.get("photo_reference")
            if ref:
                refs.append(ref)
        if not refs:
            ref = ((first.get("photos") or [{}])[0]).get("photo_reference")
            if ref:
                refs.append(ref)
        if refs:
            hotel["images"] = [_photo_url(r, key) for r in refs]

    return hotel

def enrich_hotels_with_places(hotels: list[dict], city_code: str | None = None) -> list[dict]:
    if not ENABLE_PHOTOS:
        return hotels
    key = _read_google_key()
    if not key:
        _LOG.warning("Google key missing or unreadable; skipping enrichment.")
        return hotels

    # Convert IATA code to a usable city name
    city_hint = _to_city_hint(city_code, "London")

    out = []
    for h in hotels:
        try:
            out.append(resolve_place(h, key=key, city_hint=city_hint))
        except Exception as e:
            _LOG.info("resolve_place error for %s: %s", (h.get("name") or "Hotel"), e)
            out.append(h)
    return out

