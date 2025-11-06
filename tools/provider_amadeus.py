# provider_amadeus.py
import os
import json
import time
import logging
from datetime import datetime, date as _date
from typing import List, Dict, Any, Optional, TypedDict, NotRequired
import urllib.parse
import random
import requests
import boto3

logger = logging.getLogger(__name__)

# ---- Currency mode (force GBP vs local) ----
REQUEST_CURRENCY = os.getenv("HOTELS_CURRENCY", "GBP")  # "GBP" to force; empty to use local

# ---- Config from environment ----
REGION = os.getenv("AWS_REGION", "us-east-1")
SECRET_NAME = os.getenv("AMADEUS_SECRET_NAME", "/lux/amadeus/credentials")
GOOGLE_SECRET_NAME = os.getenv("GOOGLE_SECRET_NAME", "/lux/google/api_key")

BASE_URL = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com")

# Optional: central London geocode fallback
USE_FALLBACK_GEO = os.getenv("AMADEUS_USE_FALLBACK", "1").lower() in {"1","true","yes"}
FALLBACK_LAT = float(os.getenv("AMADEUS_FALLBACK_LAT", "51.5074"))
FALLBACK_LON = float(os.getenv("AMADEUS_FALLBACK_LON", "-0.1278"))
FALLBACK_RADIUS_KM = float(os.getenv("AMADEUS_FALLBACK_RADIUS_KM", "8"))

# Offer batching + limits
OFFERS_CHUNK_SIZE = int(os.getenv("AMADEUS_OFFERS_CHUNK_SIZE", "12"))
AMADEUS_MAX_CHUNKS = int(os.getenv("AMADEUS_MAX_CHUNKS", "4"))
LUX_HOTEL_CAP = int(os.getenv("LUX_HOTEL_CAP", "36"))
INTER_CHUNK_SLEEP = float(os.getenv("AMADEUS_INTER_CHUNK_SLEEP", "0.10"))
MAX_RETRIES = int(os.getenv("AMADEUS_MAX_RETRIES", "5"))
BASE_BACKOFF = float(os.getenv("AMADEUS_BASE_BACKOFF", "1.0"))

# Deadline handling
TIME_BUFFER_MS = int(os.getenv("TIME_BUFFER_MS", "3000"))
TARGET_RESULTS = int(os.getenv("AMADEUS_TARGET_RESULTS", "30"))

# Search defaults
LUX_RADIUS_KM_DEFAULT = float(os.getenv("LUX_RADIUS_KM_DEFAULT", "8.0"))

# ---- Optional Google Places ----
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
ENABLE_PLACES_PHOTOS = os.getenv("ENABLE_PLACES_PHOTOS", "1").lower() in {"1", "true", "yes"}
MAX_PHOTOS_PER_HOTEL = int(os.getenv("MAX_PHOTOS_PER_HOTEL", "4"))
PHOTO_PROXY_BASE = (os.getenv("PHOTO_PROXY_BASE") or "").rstrip("/")

def _hostname_from_base_url(url: str) -> str:
    return "test" if "test.api.amadeus.com" in url else "production"

# ---- Deadline + chunking helpers ----
def _remaining_ms(context) -> int:
    try:
        return context.get_remaining_time_in_millis()
    except Exception:
        return 999_999

def _chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i+size]

# ---- Optional Amadeus SDK ----
HAVE_SDK = True
try:
    from amadeus import Client, ResponseError
except Exception:
    HAVE_SDK = False
    Client = None

    class ResponseError(Exception):
        pass

def _load_google_api_key() -> Optional[str]:
    if GOOGLE_PLACES_API_KEY:
        return GOOGLE_PLACES_API_KEY

    try:
        sm = boto3.client("secretsmanager", region_name=REGION)
        resp = sm.get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        payload = resp.get("SecretString")
        if payload:
            data = json.loads(payload)
            return data.get("api_key") or data.get("maps_api_key")
    except Exception as e:
        logger.info("No Google key from Secrets (%s): %s", GOOGLE_SECRET_NAME, e)

    return None

# ---- Secrets Manager helpers ----
def _load_amadeus_secrets() -> Dict[str, str]:
    sm = boto3.client("secretsmanager", region_name=REGION)
    sec = sm.get_secret_value(SecretId=SECRET_NAME)["SecretString"]
    data = json.loads(sec)
    return {"client_id": data["client_id"], "client_secret": data["client_secret"]}

def _get_secret_dict(secret_name: str, region_name: str = None) -> dict:
    region = region_name or REGION
    sm = boto3.client("secretsmanager", region_name=region)
    resp = sm.get_secret_value(SecretId=secret_name)
    raw = resp.get("SecretString") or (resp.get("SecretBinary") and resp["SecretBinary"].decode("utf-8"))
    return json.loads(raw) if raw else {}

if not GOOGLE_PLACES_API_KEY:
    try:
        _g = _get_secret_dict(GOOGLE_SECRET_NAME)
        GOOGLE_PLACES_API_KEY = _g.get("api_key") or _g.get("maps_api_key") or _g.get("GOOGLE_PLACES_API_KEY")
        if GOOGLE_PLACES_API_KEY:
            logger.info("Loaded Google API key from Secrets Manager: %s", GOOGLE_SECRET_NAME)
        else:
            logger.warning("Google API key not found in secret %s", GOOGLE_SECRET_NAME)
    except Exception as e:
        logger.warning("Failed to load Google API key from Secrets Manager %s: %s", GOOGLE_SECRET_NAME, e)

if ENABLE_PLACES_PHOTOS and not GOOGLE_PLACES_API_KEY:
    logger.warning("ENABLE_PLACES_PHOTOS is true but no Google API key available; disabling photos.")
    ENABLE_PLACES_PHOTOS = False

# ---- SDK client ----
_amadeus_sdk_client: Optional["Client"] = None
if HAVE_SDK:
    try:
        creds = _load_amadeus_secrets()
        _amadeus_sdk_client = Client(
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            hostname=_hostname_from_base_url(BASE_URL),
        )
    except Exception as e:
        logger.warning(f"[amadeus] SDK unavailable or init failed; will use REST fallback: {e}")
        _amadeus_sdk_client = None
        HAVE_SDK = False

# ---- REST helpers ----
_session = None
_token_cache = {"access_token": None, "expires_at": 0.0}

def _http():
    global _session
    if _session is None:
        _session = requests.Session()
    return _session

def _get_oauth_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    creds = _load_amadeus_secrets()
    url = f"{BASE_URL}/v1/security/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
    }
    r = _http().post(url, headers=headers, data=data, timeout=20)
    logger.info({"stage": "amadeus_oauth", "status": r.status_code})
    r.raise_for_status()
    payload = r.json()
    token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 1800))
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + max(60, expires_in - 60)
    return token

def _rest_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    for attempt in range(MAX_RETRIES):
        token = _get_oauth_token()
        headers = {"Authorization": f"Bearer {token}"}
        logger.info({"stage": "amadeus_rest_get", "url": url, "params": params, "attempt": attempt + 1})
        r = _http().get(url, headers=headers, params=params, timeout=30)

        if r.status_code < 400:
            logger.info({"stage": "amadeus_rest_status", "status": r.status_code})
            return r.json()

        if r.status_code in (429, 500, 502, 503, 504, 408):
            logger.warning({
                "stage": "amadeus_retry",
                "status": r.status_code,
                "retry_after": r.headers.get("Retry-After"),
                "x_rl_limit": r.headers.get("X-RateLimit-Limit"),
                "x_rl_remaining": r.headers.get("X-RateLimit-Remaining"),
                "attempt": attempt + 1,
            })
            _sleep_with_retry_after(r, attempt, base=BASE_BACKOFF)
            continue

        try:
            body = r.text
        except Exception:
            body = "<no body available>"
        logger.error({"stage": "amadeus_rest_error", "status": r.status_code, "url": url, "body": body})
        r.raise_for_status()

    r = _http().get(url, headers={"Authorization": f"Bearer {_get_oauth_token()}"}, params=params, timeout=30)
    try:
        body = r.text
    except Exception:
        body = "<no body available>"
    logger.error({"stage": "amadeus_rest_gave_up", "status": r.status_code, "url": url, "body": body})
    r.raise_for_status()
    return {}

def _resolve_city(name: str, country_code: Optional[str] = None) -> tuple[Optional[str], Optional[tuple[float, float]]]:
    try:
        params = {"keyword": name, "subType": "CITY"}
        if country_code:
            params["countryCode"] = country_code

        if HAVE_SDK and _amadeus_sdk_client:
            resp = _amadeus_sdk_client.reference_data.locations.get(**params)
            data = getattr(resp, "data", []) or []
        else:
            data = (_rest_get("/v1/reference-data/locations", params) or {}).get("data", []) or []

        if not data:
            return None, None

        best = data[0]
        code = best.get("iataCode") or best.get("cityCode")
        geo = best.get("geoCode") or {}
        lat = geo.get("latitude")
        lon = geo.get("longitude")
        return code, ((lat, lon) if lat is not None and lon is not None else None)
    except Exception as e:
        logger.warning({"stage": "amadeus_city_resolve_failed", "error": str(e), "name": name, "cc": country_code})
        return None, None

def _sleep_with_retry_after(resp, attempt, base=1.0):
    ra = resp.headers.get("Retry-After")
    if ra:
        try:
            wait = float(ra)
        except ValueError:
            wait = base * (2 ** attempt)
    else:
        wait = base * (2 ** attempt)
    wait += random.uniform(0, 0.25)
    logger.warning("429/5xx: backing off for %.2fs (attempt %d)", wait, attempt)
    time.sleep(wait)

def _throttled_get(url: str, headers: Dict[str, str], params: Dict[str, Any]) -> requests.Response:
    sess = _http()
    for attempt in range(MAX_RETRIES):
        resp = sess.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code < 400:
            return resp
        if resp.status_code in (429, 500, 502, 503, 504):
            _sleep_with_retry_after(resp, attempt, base=BASE_BACKOFF)
            continue
        resp.raise_for_status()
    resp.raise_for_status()
    return resp

def fetch_offers_chunked(access_token: str, hotel_ids: List[str], common_params: Dict[str, Any]) -> List[Dict[str, Any]]:
    base_url = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com")
    url = f"{base_url}/v3/shopping/hotel-offers"
    headers = {"Authorization": f"Bearer {access_token}"}

    all_offers = []
    for i in range(0, len(hotel_ids), OFFERS_CHUNK_SIZE):
        chunk = hotel_ids[i : i + OFFERS_CHUNK_SIZE]
        params = dict(common_params)
        params["hotelIds"] = ",".join(chunk)

        time.sleep(float(os.getenv("AMADEUS_INTER_CHUNK_SLEEP", "0.15")))

        resp = _throttled_get(url, headers, params)
        data = resp.json()
        if "data" in data:
            if isinstance(data["data"], list):
                all_offers.extend(data["data"])
            else:
                all_offers.append(data["data"])
    return all_offers

def _nights(ci: Optional[str], co: Optional[str]) -> int:
    try:
        return max((_date.fromisoformat(co) - _date.fromisoformat(ci)).days, 1)
    except Exception:
        return 1

def _pick_best_offer_any_currency(offers: List[dict]) -> Optional[dict]:
    """Return the lowest-total offer regardless of currency."""
    best_offer, best_val = None, None
    for off in offers or []:
        p = (off.get("price") or {})
        amt = p.get("total") or p.get("base")
        try:
            v = float(amt)
            if v > 0 and (best_val is None or v < best_val):
                best_val = v
                best_offer = off
        except Exception:
            continue
    return best_offer

def _extract_amount_currency(offer: Optional[dict]) -> tuple[Optional[float], Optional[str]]:
    if not offer:
        return None, None
    p = offer.get("price") or {}
    amt = p.get("total") or p.get("base")
    try:
        val = float(amt) if amt is not None else None
    except Exception:
        val = None
    curr = (p.get("currency") or "").upper() or None
    return val, curr



def _norm_amenities(hotel: dict, offers: List[dict]) -> List[str]:
    am = (hotel.get("amenities") or [])[:]
    for off in offers or []:
        am += off.get("amenities", []) or []
    seen, out = set(), []
    for a in am:
        s = str(a)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:20]

def _list_hotel_ids_by_city(city_code: str, radius_km: int | None = None, hotel_source: str = "ALL") -> List[str]:
    params: Dict[str, Any] = {"cityCode": city_code, "hotelSource": hotel_source}
    if radius_km is not None:
        params["radius"] = radius_km
        params["radiusUnit"] = "KM"
    resp = _rest_get("/v1/reference-data/locations/hotels/by-city", params)
    data = resp.get("data", []) or []
    ids = [h.get("hotelId") for h in data if h.get("hotelId")]
    logger.info({"stage": "amadeus_hotel_list_city", "city": city_code, "count": len(ids), "sample": ids[:5]})
    return ids

def _hotel_meta_by_city(city_code: str, radius_km: int | None = None, hotel_source: str = "ALL") -> Dict[str, Dict[str, Any]]:
    params: Dict[str, Any] = {"cityCode": city_code, "hotelSource": hotel_source}
    if radius_km is not None:
        params["radius"] = radius_km
        params["radiusUnit"] = "KM"
    resp = _rest_get("/v1/reference-data/locations/hotels/by-city", params)
    meta: Dict[str, Dict[str, Any]] = {}
    for h in (resp.get("data") or []):
        hid = h.get("hotelId")
        if not hid:
            continue
        geo = h.get("geoCode") or {}
        meta[hid] = {
            "lat": geo.get("latitude"),
            "lon": geo.get("longitude"),
            "rating": h.get("rating"),
            "name": h.get("name"),
        }
    logger.info({"stage": "amadeus_city_meta", "count": len(meta)})
    return meta

def _list_hotel_ids_by_geocode(lat: float, lon: float, radius_km: int, hotel_source: str = "ALL") -> List[str]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "radius": radius_km,
        "radiusUnit": "KM",
        "hotelSource": hotel_source,
    }
    resp = _rest_get("/v1/reference-data/locations/hotels/by-geocode", params)
    data = resp.get("data", []) or []
    ids = [h.get("hotelId") for h in data if h.get("hotelId")]
    logger.info({"stage": "amadeus_hotel_list_geocode", "count": len(ids), "sample": ids[:5]})
    return ids

def _offers_by_hotel_ids_rest(
    hotel_ids: List[str],
    params_base: Dict[str, Any],
    target_results: Optional[int] = None,
    deadline_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    deduped = list(dict.fromkeys(hotel_ids))
    for i in range(0, len(deduped), OFFERS_CHUNK_SIZE):
        if (i // OFFERS_CHUNK_SIZE) >= AMADEUS_MAX_CHUNKS:
            logger.info({"stage": "amadeus_chunk_cap_hit", "chunks": AMADEUS_MAX_CHUNKS})
            break

        if deadline_ts and time.time() >= deadline_ts:
            logger.info({"stage": "amadeus_deadline_rest", "collected": len(results)})
            break

        chunk_ids = ",".join(deduped[i : i + OFFERS_CHUNK_SIZE])
        params = dict(params_base)
        
        #Ensure we never pass unsupported keys to /v3/shopping/hotel-offers
        for bad in ("cityCode", "city_code", "latitude", "longitude", "radius", "radiusUnit"):
            params.pop(bad, None)
 

        if isinstance(params.get("bestRateOnly"), bool):
            params["bestRateOnly"] = "true" if params["bestRateOnly"] else "false"
        if isinstance(params.get("adults"), int):
            params["adults"] = str(params["adults"])
        if isinstance(params.get("roomQuantity"), int):
            params["roomQuantity"] = str(params["roomQuantity"])

        params["hotelIds"] = chunk_ids
        
        time.sleep(INTER_CHUNK_SLEEP)
        
        # Extra visibility on the exact query we send
        logger.info({
            "stage": "amadeus_offers_call",
            "path": "/v3/shopping/hotel-offers",
            "hotelIds_count": len(chunk_ids.split(",")),
            "params_sample": {
                k: params[k]
                for k in ("adults", "checkInDate", "checkOutDate", "currency",
                  "roomQuantity", "bestRateOnly", "hotelIds")
                if k in params
            }
        })

        resp = _rest_get("/v3/shopping/hotel-offers", params)
        part = resp.get("data", []) or []
        logger.info({"stage": "amadeus_offers_chunk", "chunk_size": len(chunk_ids.split(",")), "returned": len(part)})
        results.extend(part)

        if target_results and len(results) >= target_results:
            logger.info({"stage": "amadeus_target_hit_rest", "target": target_results})
            break

    logger.info({"stage": "amadeus_offers_total_rest", "count": len(results)})
    return results

def _maps_url(name: Optional[str], city_for_url: str, lat: Optional[float], lon: Optional[float]) -> str:
    if lat is not None and lon is not None:
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    q_parts = [p for p in [name, city_for_url] if p]
    q = urllib.parse.quote_plus(", ".join(q_parts) if q_parts else "hotel")
    return f"https://www.google.com/maps/search/?api=1&query={q}"

def _extract_images_from_offers(offers: List[Dict[str, Any]]) -> List[str]:
    seen, out = set(), []
    for o in offers or []:
        hotel_blk = o.get("hotel") or {}
        media = hotel_blk.get("media") or o.get("media") or []
        for m in media:
            u = m.get("uri") or m.get("url")
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    return out[:6]


def _places_photos(name: Optional[str], city_for_url: str, lat: Optional[float], lon: Optional[float]) -> List[str]:
    """
    Server-side Places lookup → returns PROXY URLs (or photo_ref tokens).
    Never returns Google URLs with &key=.
    """
    if not ENABLE_PLACES_PHOTOS or not GOOGLE_PLACES_API_KEY:
        return []
    try:
        if lat is not None and lon is not None:
            url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            params = {
                "key": GOOGLE_PLACES_API_KEY,
                "location": f"{lat},{lon}",
                "radius": "500",
                "keyword": f"{name}, {city_for_url}" if name else city_for_url,
            }
            r = requests.get(url, params=params, timeout=2.5)
            j = r.json()
            results = j.get("results", [])
        else:
            url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
            params = {
                "key": GOOGLE_PLACES_API_KEY,
                "input": f"{name}, {city_for_url}" if name else city_for_url,
                "inputtype": "textquery",
                "fields": "photos,place_id",
            }
            r = requests.get(url, params=params, timeout=2.5)
            j = r.json()
            results = j.get("candidates", [])

        if not results:
            return []
        photos = results[0].get("photos", []) or []
        out: List[str] = []
        for ph in photos[:MAX_PHOTOS_PER_HOTEL]:
            pref = ph.get("photo_reference")
            if not pref:
                continue
            if PHOTO_PROXY_BASE:
                out.append(f"{PHOTO_PROXY_BASE}?ref={urllib.parse.quote_plus(pref)}&maxwidth=1600")
            else:
                out.append(f"photo_ref:{pref}")
        return out
    except Exception as e:
        logger.warning({"stage": "places_photos_failed", "error": str(e)})
        return []

def _offers_by_hotel_ids_sdk(
    amadeus_client: "Client",
    hotel_ids: List[str],
    params_base: Dict[str, Any],
    target_results: Optional[int] = None,
    deadline_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    deduped = list(dict.fromkeys(hotel_ids))
    for i in range(0, len(deduped), OFFERS_CHUNK_SIZE):
        if deadline_ts and time.time() >= deadline_ts:
            logger.info({"stage": "amadeus_deadline_sdk", "collected": len(results)})
            break

        chunk = ",".join(deduped[i : i + OFFERS_CHUNK_SIZE])

        # Build safe kwargs (stringify where Amadeus expects strings)
        kwargs = {
            "hotelIds": chunk,
            "adults": str(params_base["adults"]),
            "checkInDate": params_base["checkInDate"],
            "checkOutDate": params_base["checkOutDate"],
            "roomQuantity": str(params_base.get("roomQuantity", 1)),
            "bestRateOnly": "true" if params_base.get("bestRateOnly", True) else "false",
        }
        # Only include currency if set
        if params_base.get("currency"):
            kwargs["currency"] = params_base["currency"]

        resp = amadeus_client.shopping.hotel_offers_search.get(**kwargs)
        part = resp.data or []
        logger.info({"stage": "amadeus_offers_chunk_sdk", "chunk_size": len(chunk.split(",")), "returned": len(part)})
        results.extend(part)

        if target_results and len(results) >= target_results:
            logger.info({"stage": "amadeus_target_hit_sdk", "target": target_results})
            break

    logger.info({"stage": "amadeus_offers_total_sdk", "count": len(results)})
    return results



# ================== Public functions ==================
logger.info(f"[amadeus] provider_loaded v2 BASE_URL={BASE_URL} HAVE_SDK={HAVE_SDK} SECRET_NAME={SECRET_NAME}")

logger.info({
  "stage": "amadeus_boot",
  "BASE_URL": BASE_URL,
  "USE_FALLBACK_GEO": USE_FALLBACK_GEO,
  "ENABLE_PLACES_PHOTOS": ENABLE_PLACES_PHOTOS,
  "OFFERS_CHUNK_SIZE": OFFERS_CHUNK_SIZE,
  "AMADEUS_MAX_CHUNKS": AMADEUS_MAX_CHUNKS,
})

class HotelCard(TypedDict, total=False):
    id: str
    name: str
    stars: float
    url: str
    images: List[str]
    location_note: str
    amenities: List[str]
    est_price: Optional[float]  # per-night numeric
    currency: Optional[str]      # ISO 4217 e.g., GBP/EUR/JPY
    lat: NotRequired[Optional[float]]
    lon: NotRequired[Optional[float]]

class SearchResult(TypedDict, total=False):
    status: str
    hotels: List[HotelCard]
    error: str
    meta: NotRequired[Dict[str, Any]]

def search_hotels(params: Dict[str, Any], *, context=None) -> SearchResult:
    logger.info(f"[amadeus] 🔧 hotel search started @ {datetime.now().isoformat()}")

    stay = params.get("stay") or {}
    check_in = stay.get("check_in") or params.get("check_in") or params.get("checkInDate")
    check_out = stay.get("check_out") or params.get("check_out") or params.get("checkOutDate")
    if not check_in or not check_out:
        return {"status": "error", "hotels": [], "error": "missing stay.check_in/check_out"}

    loc = params.get("location") or {}
    lat = loc.get("lat", params.get("lat"))
    lon = loc.get("lon", params.get("lon"))
    radius_km = int(loc.get("radius_km", params.get("radius_km", LUX_RADIUS_KM_DEFAULT)))

    city_code  = (params.get("city_code") or params.get("cityCode") or
              stay.get("city_code") or stay.get("cityCode"))
    city_name  = (params.get("city") or params.get("city_name") or
                stay.get("city")   or stay.get("city_name"))
    adults     = int((params.get("adults") or stay.get("adults") or 2))
    rooms      = int((params.get("roomQuantity") or stay.get("roomQuantity") or 1))
    currency   = (params.get("currency") or stay.get("currency") or "GBP").upper()
    country_code = (
    params.get("country_code")
    or stay.get("country_code")
    or params.get("country")      # tolerate "country"
    or stay.get("country")
)
    
    resolved_center = None
    if not city_code and city_name:
        city_code, resolved_center = _resolve_city(city_name, country_code)

    if (lat is None or lon is None) and resolved_center:
        lat, lon = resolved_center

    logger.info({
        "stage": "amadeus_search_params",
        "city": city_name, "country": country_code, "city_code": city_code,
        "lat": lat, "lon": lon, "radius_km": radius_km,
        "adults": adults, "rooms": rooms, "currency": currency
    })

    params_base: Dict[str, Any] = {
        "adults": adults,
        "checkInDate": check_in,
        "checkOutDate": check_out,
        "roomQuantity": rooms,
        "bestRateOnly": True,
    }
    
    # NEW: only add currency if REQUEST_CURRENCY is set (GBP by default)
    if REQUEST_CURRENCY:
        params_base["currency"] = REQUEST_CURRENCY

    hotel_ids: List[str] = []
    try:
        if city_code:
            hotel_ids = _list_hotel_ids_by_city(city_code, radius_km=None, hotel_source="ALL")
    except Exception as e:
        logger.warning({"stage": "amadeus_by_city_failed", "error": str(e)})

    if not hotel_ids:
        if (lat is None or lon is None) and not USE_FALLBACK_GEO:
            logger.info("[amadeus] no lat/lon provided and fallback disabled -> no results")
            return {"status": "ok", "hotels": []}

        use_lat = float(lat) if isinstance(lat, (int, float)) else FALLBACK_LAT
        use_lon = float(lon) if isinstance(lon, (int, float)) else FALLBACK_LON
        try:
            hotel_ids = _list_hotel_ids_by_geocode(use_lat, use_lon, radius_km, hotel_source="ALL")
        except Exception as e:
            logger.warning({"stage": "amadeus_by_geocode_failed", "error": str(e)})

    if not hotel_ids:
        logger.info("[amadeus] no hotels found after city+geocode lookups")
        return {"status": "ok", "hotels": []}

    hotel_ids = list(dict.fromkeys(hotel_ids))[:LUX_HOTEL_CAP]
    logger.info({"stage": "amadeus_hotel_ids_capped", "count": len(hotel_ids)})

    meta_map: Dict[str, Dict[str, Any]] = {}
    try:
        if city_code:
            meta_map = _hotel_meta_by_city(city_code, radius_km=None, hotel_source="ALL")
    except Exception as e:
        logger.warning({"stage": "amadeus_city_meta_failed", "error": str(e)})

    if context:
        ms_left = _remaining_ms(context)
        sec_left = max(0.5, (ms_left - TIME_BUFFER_MS) / 1000.0)
        deadline_ts = time.time() + sec_left
    else:
        fallback_budget_sec = int(os.getenv("AMADEUS_TIME_BUDGET_SEC", "45"))
        deadline_ts = time.time() + fallback_budget_sec

    try:
        if HAVE_SDK and _amadeus_sdk_client:
            offers = _offers_by_hotel_ids_sdk(
                _amadeus_sdk_client,
                hotel_ids,
                params_base,
                target_results=TARGET_RESULTS,
                deadline_ts=deadline_ts,
            )
        else:
            offers = _offers_by_hotel_ids_rest(
                hotel_ids,
                params_base,
                target_results=TARGET_RESULTS,
                deadline_ts=deadline_ts,
            )

        logger.info({"stage": "amadeus_offers_total", "count": len(offers)})

        nights = _nights(check_in, check_out)
        cards: List[Dict[str, Any]] = []
        for item in offers:
            hotel = item.get("hotel") or {}
            offer_list = item.get("offers") or []
            geo = hotel.get("geoCode") or {}
            hid = hotel.get("hotelId") or hotel.get("id") or ""

            
            best_offer = _pick_best_offer_any_currency(offer_list)
            total_amt, total_curr = _extract_amount_currency(best_offer)
            per_night = (total_amt / nights) if (total_amt and nights > 0) else None


            lat_val = geo.get("latitude") or (meta_map.get(hid) or {}).get("lat")
            lon_val = geo.get("longitude") or (meta_map.get(hid) or {}).get("lon")
            rating = hotel.get("rating")
            if rating is None:
                rating = (meta_map.get(hid) or {}).get("rating")
            try:
                stars = float(rating) if rating is not None else 0.0
            except Exception:
                stars = 0.0

            city_for_url = (params.get("city") or city_name or city_code or "") or ""
            name_val = hotel.get("name") or (meta_map.get(hid) or {}).get("name")
            maps_url = _maps_url(name_val, city_for_url, lat_val, lon_val)

            images = _extract_images_from_offers(offer_list)
            if not images:
                images = _places_photos(name_val, city_for_url, lat_val, lon_val)

            cards.append({
                "id": hid,
                "name": name_val,
                "stars": stars,
                "url": maps_url,
                "images": images or [],
                "location_note": (
                    params.get("neighborhood")
                    or params.get("city")
                    or city_code
                    or ""
                ),
                "amenities": _norm_amenities(hotel, offer_list),
                "est_price": per_night,
                "currency": total_curr,
                "lat": lat_val,
                "lon": lon_val,
            })

        cards.sort(key=lambda x: (float("inf") if x["est_price"] is None else x["est_price"]))
        debug_meta = {
            "city_code": city_code,
            "city_name": city_name,
            "listed_hotel_ids": len(hotel_ids),
            "offers_returned": len(offers),
            "cards_built": len(cards),
        }
        logger.info({"stage": "amadeus_debug_counts", **debug_meta})
        return {"status": "ok", "hotels": cards, "meta": {"debug": debug_meta}}
    

    except Exception as e:
        logger.warning({"stage": "amadeus_offers_by_ids_failed", "error": str(e)})
        return {"status": "error", "hotels": [], "error": str(e)}

def _amadeus_search(search_data: Dict[str, Any]):
    return search_hotels(search_data)

def get_hotel_ratings(hotel_id: str) -> Dict[str, Any]:
    try:
        if HAVE_SDK and _amadeus_sdk_client:
            resp = _amadeus_sdk_client.e_reputation.hotel_sentiments.get(hotelIds=hotel_id)
            return resp.data or {}
        resp = _rest_get("/v2/e-reputation/hotel-sentiments", {"hotelIds": hotel_id})
        return resp.get("data", {})
    except Exception as e:
        logger.error(f"[amadeus] get_hotel_ratings failed for {hotel_id}: {e}")
        return {}

def search_activities(latitude: float, longitude: float) -> List[Dict[str, Any]]:
    try:
        if HAVE_SDK and _amadeus_sdk_client:
            resp = _amadeus_sdk_client.shopping.activities.get(latitude=latitude, longitude=longitude)
            return resp.data or []
        resp = _rest_get("/v1/shopping/activities", {"latitude": latitude, "longitude": longitude})
        return resp.get("data", [])
    except Exception as e:
        logger.error(f"[amadeus] search_activities failed: {e}")
        return []