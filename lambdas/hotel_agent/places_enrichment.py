import os, json, requests, boto3, logging
from typing import Dict, Any, List, Optional

_LOG = logging.getLogger(__name__)
_SECRETS = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))

GOOGLE_SECRET_NAME = os.getenv("GOOGLE_PLACES_SECRET_NAME", "/lux/google/places_api_key")
ENABLE_PHOTOS = (os.getenv("ENABLE_PLACES_PHOTOS", "0") in ("1", "true", "yes"))
MAX_PHOTOS = int(os.getenv("MAX_PHOTOS_PER_HOTEL", "4") or "4")

# --- Google (legacy) endpoints ---
FIND_PLACE = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
TEXT_SEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"
PHOTO = "https://maps.googleapis.com/maps/api/place/photo"


def _get_google_key() -> str:
    """Load Google Places API key from Secrets Manager (supports JSON or plain text)."""
    try:
        val = _SECRETS.get_secret_value(SecretId=GOOGLE_SECRET_NAME).get("SecretString") or ""
    except Exception as e:
        raise RuntimeError(f"Cannot read secret {GOOGLE_SECRET_NAME}: {e}")
    val = val.strip()
    if not val:
        raise RuntimeError("Empty secret string for Google key")

    # JSON? plain?
    if val.startswith("{"):
        try:
            obj = json.loads(val)
            key = (obj.get("api_key") or obj.get("key") or "").strip()
        except Exception:
            key = ""
    else:
        key = val.strip()

    if not key:
        raise RuntimeError("Google Places API key missing/empty after parsing")
    return key


_API_KEY: Optional[str] = None
def _key() -> str:
    global _API_KEY
    if not _API_KEY:
        _API_KEY = _get_google_key()
    return _API_KEY


def _photo_url(photo_ref: str, maxwidth: int = 800) -> str:
    return f"{PHOTO}?maxwidth={maxwidth}&photo_reference={photo_ref}&key={_key()}"


def _first_candidate_from_text(query: str, lat: Optional[float] = None, lon: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Try text search; bias by location if provided."""
    params = {"query": query, "key": _key()}
    if lat is not None and lon is not None:
        params.update({"location": f"{lat},{lon}", "radius": 2500})  # 2.5km bias
    r = requests.get(TEXT_SEARCH, params=params, timeout=8)
    data = r.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        _LOG.warning("TextSearch status=%s, error=%s", data.get("status"), data.get("error_message"))
    results = data.get("results") or []
    return results[0] if results else None


def _find_place_biased(name: str, lat: float, lon: float) -> Optional[str]:
    """Find Place with a circle bias; returns place_id or None."""
    params = {
        "input": name,
        "inputtype": "textquery",
        "fields": "place_id,name,geometry,formatted_address,types,photos",
        "locationbias": f"circle:2000@{lat},{lon}",  # 2km bias
        "key": _key(),
    }
    r = requests.get(FIND_PLACE, params=params, timeout=8)
    data = r.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        _LOG.info("FindPlace status=%s, err=%s", data.get("status"), data.get("error_message"))
    candidates = data.get("candidates") or []
    return (candidates[0] or {}).get("place_id") if candidates else None


def _place_details(place_id: str) -> Optional[Dict[str, Any]]:
    params = {
        "place_id": place_id,
        "fields": "url,website,geometry,photos,formatted_address,name",
        "key": _key(),
    }
    r = requests.get(DETAILS, params=params, timeout=8)
    data = r.json()
    if data.get("status") != "OK":
        _LOG.info("Details status=%s, err=%s", data.get("status"), data.get("error_message"))
        return None
    return data.get("result") or {}


def _address_looks_like_city(addr: str, city_hint: str) -> bool:
    a = (addr or "").lower()
    c = (city_hint or "").lower()
    return (c in a) if c else True


def resolve_place(hotel: Dict[str, Any], city_hint: str) -> Dict[str, Any]:
    """
    Enrich single hotel with Google Place URL, lat/lon, and photos.
    - Tries location-biased 'findplacefromtext' if coords are present.
    - Otherwise falls back to 'textsearch' with '<name>, <city>'.
    - Validates city in address to avoid mismatches (e.g., Rixos in Turkey for London).
    """
    if not ENABLE_PHOTOS:
        return hotel

    name = (hotel.get("name") or "").strip()
    if not name:
        return hotel

    lat = hotel.get("lat")
    lon = hotel.get("lon")
    details: Optional[Dict[str, Any]] = None

    # 1) Try location-biased flow if we have coords
    place_id: Optional[str] = None
    if isinstance(lat, (float, int)) and isinstance(lon, (float, int)):
        try:
            place_id = _find_place_biased(name, float(lat), float(lon))
        except Exception as e:
            _LOG.debug("find_place_biased failed: %s", e)

    # 2) If no place yet, do text search "<name>, <city>"
    if not place_id:
        q = f"{name}, {city_hint}".strip().strip(",")
        try:
            cand = _first_candidate_from_text(q)
            if cand:
                place_id = cand.get("place_id")
                # prime lat/lon if missing from hotel
                if not lat or not lon:
                    geom = (cand.get("geometry") or {}).get("location") or {}
                    hotel["lat"] = hotel.get("lat") or geom.get("lat")
                    hotel["lon"] = hotel.get("lon") or geom.get("lng")
        except Exception as e:
            _LOG.debug("text_search failed: %s", e)

    # 3) If still none, give up (keep generic map URL)
    if not place_id:
        hotel.setdefault("url", f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}")
        hotel.setdefault("images", [])
        return hotel

    # 4) Get details (url, website, photos, geometry)
    try:
        details = _place_details(place_id)
    except Exception as e:
        _LOG.debug("place_details failed: %s", e)
        details = None

    if not details:
        hotel.setdefault("url", f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}")
        hotel.setdefault("images", [])
        return hotel

    # 5) Avoid obvious mismatches: ensure address contains city_hint when provided
    addr = details.get("formatted_address") or ""
    if city_hint and not _address_looks_like_city(addr, city_hint):
        _LOG.info("Skipping details for %s (address mismatch: %s)", name, addr)
        hotel.setdefault("url", f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}")
        hotel.setdefault("images", [])
        return hotel

    # 6) Fill URL, coords, and images
    url = details.get("url") or details.get("website") or f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(name)}"
    geom = (details.get("geometry") or {}).get("location") or {}
    photos = details.get("photos") or []

    hotel["url"] = url
    if geom:
        hotel["lat"] = hotel.get("lat") or geom.get("lat")
        hotel["lon"] = hotel.get("lon") or geom.get("lng")

    imgs: List[str] = []
    for p in photos[:MAX_PHOTOS]:
        ref = p.get("photo_reference")
        if ref:
            imgs.append(_photo_url(ref, maxwidth=1024))
    hotel["images"] = imgs

    return hotel


def enrich_hotels_with_places(hotels: List[Dict[str, Any]], city_code: Optional[str]) -> List[Dict[str, Any]]:
    """
    Enrich a list of hotels. `city_code` like 'LON' is mapped to a human city string.
    """
    if not ENABLE_PHOTOS:
        return hotels

    # Minimal IATA→city mapping. Expand as needed or pass a proper city string from your stay.
    iata_to_city = {
        "LON": "London, UK",
        "NYC": "New York, NY",
        "PAR": "Paris, France",
        "TYO": "Tokyo, Japan",
    }
    city_hint = iata_to_city.get((city_code or "").upper(), city_code or "")

    out = []
    for h in hotels or []:
        try:
            out.append(resolve_place(h, city_hint=city_hint))
        except Exception as e:
            _LOG.debug("resolve_place error for %s: %s", h.get("name"), e)
            # keep original but ensure expected keys exist
            h.setdefault("url", f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(h.get('name',''))}")
            h.setdefault("images", [])
            out.append(h)
    return out

