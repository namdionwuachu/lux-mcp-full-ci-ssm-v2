# provider_amadeus.py
import os
import json
import time
import logging
from datetime import datetime, date as _date
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
MAX_HOTELS = int(os.getenv("AMADEUS_MAX_HOTELS", "60"))             # cap hotelIds breadth (3 chunks of 20)
TARGET_RESULTS = int(os.getenv("AMADEUS_TARGET_RESULTS", "30"))     # stop when we’ve got this many hotels-with-offers
TIME_BUDGET_SEC = int(os.getenv("AMADEUS_TIME_BUDGET_SEC", "17"))   # finish before Lambda’s 20s


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


def _nights(ci: Optional[str], co: Optional[str]) -> int:
    try:
        return max((_date.fromisoformat(co) - _date.fromisoformat(ci)).days, 1)
    except Exception:
        return 1


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
        if deadline_ts and time.time() >= deadline_ts:
            logger.info({"stage": "amadeus_deadline_rest", "collected": len(results)})
            break
        chunk_ids = ",".join(deduped[i : i + OFFERS_CHUNK_SIZE])
        params = dict(params_base)
        params["hotelIds"] = chunk_ids
        resp = _rest_get("/v3/shopping/hotel-offers", params)
        part = resp.get("data", []) or []
        logger.info({"stage": "amadeus_offers_chunk", "chunk_size": len(chunk_ids.split(",")), "returned": len(part)})
        results.extend(part)
        if target_results and len(results) >= target_results:
            logger.info({"stage": "amadeus_target_hit_rest", "target": target_results})
            break
    logger.info({"stage": "amadeus_offers_total_rest", "count": len(results)})
    return results


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
        if target_results and len(results) >= target_results:
            logger.info({"stage": "amadeus_target_hit_sdk", "target": target_results})
            break
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

    # 1) Try by-city first
    hotel_ids: List[str] = []
    try:
        if city_code:
            hotel_ids = _list_hotel_ids_by_city(city_code, radius_km=None, hotel_source="ALL")
    except Exception as e:
        logger.warning({"stage": "amadeus_by_city_failed", "error": str(e)})

    # 2) Fallback to geocode
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

    # ✅ Dedupe & cap breadth to stay under ~20s
    hotel_ids = list(dict.fromkeys(hotel_ids))[:MAX_HOTELS]
    logger.info({"stage": "amadeus_hotel_ids_capped", "count": len(hotel_ids)})

    # ✅ Enrichment map (lat/lon/rating) from by-city
    meta_map: Dict[str, Dict[str, Any]] = {}
    try:
        if city_code:
            meta_map = _hotel_meta_by_city(city_code, radius_km=None, hotel_source="ALL")
    except Exception as e:
        logger.warning({"stage": "amadeus_city_meta_failed", "error": str(e)})

    # ✅ Early-exit budget
    deadline_ts = time.time() + TIME_BUDGET_SEC

    # 3) Fetch offers (SDK if available, else REST)
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

        # Normalize raw Amadeus offers → hotel cards expected downstream
        nights = _nights(check_in, check_out)
        cards: List[Dict[str, Any]] = []
        for item in offers:
            hotel = item.get("hotel") or {}
            offer_list = item.get("offers") or []
            geo = hotel.get("geoCode") or {}
            hid = hotel.get("hotelId") or hotel.get("id") or ""

            # best GBP total across returned offers for this hotel
            total_gbp = _best_total_gbp(offer_list)
            per_night = (total_gbp / nights) if (total_gbp and nights > 0) else None

            # enrich from meta if missing
            lat_val = geo.get("latitude") or (meta_map.get(hid) or {}).get("lat")
            lon_val = geo.get("longitude") or (meta_map.get(hid) or {}).get("lon")
            rating = hotel.get("rating")
            if rating is None:
                rating = (meta_map.get(hid) or {}).get("rating")
            try:
                stars = float(rating) if rating is not None else 0.0
            except Exception:
                stars = 0.0

            cards.append({
                "name": hotel.get("name") or (meta_map.get(hid) or {}).get("name"),
                "stars": stars,
                "url": "",
                "location_note": (
                    stay_details.get("neighborhood")
                    or stay_details.get("city")
                    or city_code
                    or ""
                ),
                "amenities": _norm_amenities(hotel, offer_list),
                "est_price_gbp": per_night,
                "lat": lat_val,
                "lon": lon_val,
            })

        # Sort cheapest-first (optional)
        cards.sort(key=lambda x: (float("inf") if x["est_price_gbp"] is None else x["est_price_gbp"]))
        logger.info({"stage": "amadeus_cards_total", "count": len(cards)})
        return cards

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
