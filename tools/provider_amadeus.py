# provider_amadeus.py
import os
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import boto3

logger = logging.getLogger(__name__)

# ---- Config from environment ----
REGION = os.getenv("AWS_REGION", "us-east-1")
SECRET_NAME = os.getenv("AMADEUS_SECRET_NAME", "/lux/amadeus/credentials")
BASE_URL = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com")

# Central London geocode fallback (used when by-city is sparse)
FALLBACK_LAT = float(os.getenv("AMADEUS_FALLBACK_LAT", "51.5074"))
FALLBACK_LON = float(os.getenv("AMADEUS_FALLBACK_LON", "-0.1278"))
FALLBACK_RADIUS_KM = int(os.getenv("AMADEUS_FALLBACK_RADIUS_KM", "20"))

# How many hotelIds per request to the offers endpoint (avoid very long URLs)
OFFERS_CHUNK_SIZE = int(os.getenv("AMADEUS_OFFERS_CHUNK_SIZE", "20"))

def _hostname_from_base_url(url: str) -> str:
    return "test" if "test.api.amadeus.com" in url else "production"

# ---- Optional Amadeus SDK ----
HAVE_SDK = True
try:
    from amadeus import Client, ResponseError  # type: ignore
except Exception:
    HAVE_SDK = False
    Client = None  # type: ignore
    class ResponseError(Exception):  # fallback shim
        pass

# ---- Secrets Manager helpers ----
def _load_amadeus_secrets() -> Dict[str, str]:
    sm = boto3.client("secretsmanager", region_name=REGION)
    sec = sm.get_secret_value(SecretId=SECRET_NAME)["SecretString"]
    data = json.loads(sec)
    # Expect: {"client_id": "...", "client_secret": "..."}
    return {"client_id": data["client_id"], "client_secret": data["client_secret"]}

# ---- SDK client (if available) ----
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

# ---- REST helpers (requests session + lightweight token cache) ----
_session = None
_token_cache = {"access_token": None, "expires_at": 0.0}

def _http():
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
    return _session

def _get_oauth_token() -> str:
    """
    Fetch a fresh OAuth token (with simple in-process caching).
    """
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
    # expire a bit early to be safe
    expires_in = int(payload.get("expires_in", 1800))
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + max(60, expires_in - 60)
    return token

def _rest_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    token = _get_oauth_token()
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    logger.info({"stage": "amadeus_rest_get", "url": url, "params": params})
    r = _http().get(url, headers=headers, params=params, timeout=30)
    if r.status_code >= 400:
        # Log full body so we can see Amadeus error codes/titles
        try:
            body = r.text
        except Exception:
            body = "<no body available>"
        logger.error({"stage": "amadeus_rest_error", "status": r.status_code, "url": url, "body": body})
        r.raise_for_status()
    logger.info({"stage": "amadeus_rest_status", "status": r.status_code})
    return r.json()


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


def _offers_by_hotel_ids_rest(hotel_ids: List[str], params_base: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    deduped = list(dict.fromkeys(hotel_ids))  # preserve order
    for i in range(0, len(deduped), OFFERS_CHUNK_SIZE):
        chunk = ",".join(deduped[i:i + OFFERS_CHUNK_SIZE])
        params = dict(params_base)
        params["hotelIds"] = chunk
        resp = _rest_get("/v3/shopping/hotel-offers", params)
        part = resp.get("data", []) or []
        logger.info({"stage": "amadeus_offers_chunk", "chunk_size": len(chunk.split(",")), "returned": len(part)})
        results.extend(part)
    logger.info({"stage": "amadeus_offers_total", "count": len(results)})
    return results

def _offers_by_hotel_ids_sdk(amadeus_client: "Client", hotel_ids: List[str], params_base: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    deduped = list(dict.fromkeys(hotel_ids))
    for i in range(0, len(deduped), OFFERS_CHUNK_SIZE):
        chunk = ",".join(deduped[i:i + OFFERS_CHUNK_SIZE])
        resp = amadeus_client.shopping.hotel_offers_search.get(
            hotelIds=chunk,
            adults=params_base["adults"],
            checkInDate=params_base["checkInDate"],
            checkOutDate=params_base["checkOutDate"],
            currency=params_base["currency"],
            roomQuantity=params_base["roomQuantity"],
            bestRateOnly=params_base["bestRateOnly"],
        )
        part = resp.data or []
        logger.info({"stage": "amadeus_offers_chunk_sdk", "chunk_size": len(chunk.split(",")), "returned": len(part)})
        results.extend(part)
    logger.info({"stage": "amadeus_offers_total_sdk", "count": len(results)})
    return results

# ================== Public functions ==================

# Module banner to confirm deployed version & path
logger.info(f"[amadeus] provider_loaded v2 BASE_URL={BASE_URL} HAVE_SDK={HAVE_SDK} SECRET_NAME={SECRET_NAME}")

def search_hotels(stay_details: Dict[str, Any]) -> List[Dict[str, Any]]:
    logger.info(f"[amadeus] 🔧 hotel search started @ {datetime.now().isoformat()}")

    city_code = stay_details.get("city_code") or stay_details.get("cityCode")
    adults = str(stay_details.get("adults", 2))
    check_in = stay_details.get("check_in") or stay_details.get("checkInDate")
    check_out = stay_details.get("check_out") or stay_details.get("checkOutDate")
    currency = stay_details.get("currency", "GBP")
    rooms = str(stay_details.get("roomQuantity", 1))
    radius_km = int(stay_details.get("radius_km", FALLBACK_RADIUS_KM))
    lat = stay_details.get("lat")
    lon = stay_details.get("lon")

    logger.info({
        "stage": "amadeus_search_params",
        "city_code": city_code, "adults": adults,
        "check_in": check_in, "check_out": check_out,
        "rooms": rooms, "currency": currency
    })

    params_base: Dict[str, Any] = {
        "adults": adults,
        "checkInDate": check_in,
        "checkOutDate": check_out,
        "currency": currency,
        "roomQuantity": rooms,
        "bestRateOnly": "true",
    }

    # 1) Try by-city first (optionally with a radius and hotelSource)
    hotel_ids: List[str] = []
    try:
        if city_code:
            hotel_ids = _list_hotel_ids_by_city(city_code, radius_km=None, hotel_source="ALL")
    except Exception as e:
        logger.warning({"stage": "amadeus_by_city_failed", "error": str(e)})

    # 2) Fallback to geocode (provided lat/lon or London fallback)
    if not hotel_ids:
        use_lat = float(lat) if isinstance(lat, (int, float)) else FALLBACK_LAT
        use_lon = float(lon) if isinstance(lon, (int, float)) else FALLBACK_LON
        try:
            hotel_ids = _list_hotel_ids_by_geocode(use_lat, use_lon, radius_km, hotel_source="ALL")
        except Exception as e:
            logger.warning({"stage": "amadeus_by_geocode_failed", "error": str(e)})

    if not hotel_ids:
        logger.info("[amadeus] no hotels found after city+geocode lookups")
        return []

    # 3) Fetch offers (SDK if available, else REST)
    try:
        if HAVE_SDK and _amadeus_sdk_client:
            offers = _offers_by_hotel_ids_sdk(_amadeus_sdk_client, hotel_ids, params_base)
        else:
            offers = _offers_by_hotel_ids_rest(hotel_ids, params_base)
        logger.info({"stage": "amadeus_offers_total", "count": len(offers)})
        return offers
    except Exception as e:
        logger.warning({"stage": "amadeus_offers_by_ids_failed", "error": str(e)})
        return []


def _amadeus_search(search_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compatibility wrapper if other code imports this name."""
    return search_hotels(search_data)

def get_hotel_ratings(hotel_id: str) -> Dict[str, Any]:
    """Hotel sentiment/ratings (SDK if available, else REST)."""
    try:
        if HAVE_SDK and _amadeus_sdk_client:
            resp = _amadeus_sdk_client.e_reputation.hotel_sentiments.get(hotelIds=hotel_id)
            return resp.data or {}
        # REST fallback
        resp = _rest_get("/v2/e-reputation/hotel-sentiments", {"hotelIds": hotel_id})
        return resp.get("data", {})
    except Exception as e:
        logger.error(f"[amadeus] get_hotel_ratings failed for {hotel_id}: {e}")
        return {}

def search_activities(latitude: float, longitude: float) -> List[Dict[str, Any]]:
    """Activities near a lat/lon (SDK if available, else REST)."""
    try:
        if HAVE_SDK and _amadeus_sdk_client:
            resp = _amadeus_sdk_client.shopping.activities.get(latitude=latitude, longitude=longitude)
            return resp.data or []
        # REST fallback
        resp = _rest_get("/v1/shopping/activities", {"latitude": latitude, "longitude": longitude})
        return resp.get("data", [])
    except Exception as e:
        logger.error(f"[amadeus] search_activities failed: {e}")
        return []
