# provider_amadeus.py
import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import boto3

logger = logging.getLogger(__name__)

# ---- Config from environment ----
REGION = os.getenv("AWS_REGION", "us-east-1")
SECRET_NAME = os.getenv("AMADEUS_SECRET_NAME", "/lux/amadeus/credentials")
BASE_URL = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com")

# Determine Amadeus SDK hostname from BASE_URL
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

# ---- Optional SDK client (if available) ----
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
        logger.warning(f"Amadeus SDK unavailable or init failed; will use REST fallback: {e}")
        _amadeus_sdk_client = None
        HAVE_SDK = False

# ---- REST fallback (uses requests) ----
_session = None
def _http():
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
    return _session

def _get_oauth_token() -> str:
    """Fetch a fresh OAuth token (simple version; no caching)."""
    creds = _load_amadeus_secrets()
    url = f"{BASE_URL}/v1/security/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
    }
    r = _http().post(url, headers=headers, data=data, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]

def _rest_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    token = _get_oauth_token()
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    r = _http().get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

# ================== Public functions ==================

def search_hotels(stay_details: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Hotel search flow:
      1) by-city → hotelIds
      2) offers search with hotelIds
    Accepts keys in either snake_case or Amadeus-style camelCase.
    """
    logger.info(f"🔧 hotel search started @ {datetime.now().isoformat()}")
    try:
        # Accept both formats
        city_code = stay_details.get("cityCode") or stay_details.get("city_code") or "PAR"
        adults = str(stay_details.get("adults", 2))
        check_in = stay_details.get("checkInDate") or stay_details.get("check_in") or "2025-09-15"
        check_out = stay_details.get("checkOutDate") or stay_details.get("check_out") or "2025-09-16"
        currency = stay_details.get("currency", "GBP")
        rooms = str(stay_details.get("roomQuantity", 1))

        logger.info(f"Search params city={city_code} adults={adults} {check_in}→{check_out} rooms={rooms}")

        # ---- SDK path ----
        if HAVE_SDK and _amadeus_sdk_client:
            amadeus = _amadeus_sdk_client
            # Step 1: hotel IDs by city
            hotels_in_city = amadeus.reference_data.locations.hotels.by_city.get(cityCode=city_code)
            if not hotels_in_city.data:
                logger.info(f"No hotels found for city {city_code}")
                return []
            hotel_ids = [h.get("hotelId") for h in hotels_in_city.data if h.get("hotelId")]
            hotel_ids = hotel_ids[:20]  # simple cap
            if not hotel_ids:
                return []
            # Step 2: offers by hotelIds
            offers = amadeus.shopping.hotel_offers_search.get(
                hotelIds=",".join(hotel_ids),
                adults=adults,
                checkInDate=check_in,
                checkOutDate=check_out,
                currency=currency,
                roomQuantity=rooms,
                bestRateOnly=True,
            )
            data = offers.data or []
            logger.info(f"Offers found: {len(data)}")
            return data

        # ---- REST fallback ----
        # Step 1: /v1/reference-data/locations/hotels/by-city
        by_city = _rest_get(
            "/v1/reference-data/locations/hotels/by-city",
            {"cityCode": city_code},
        )
        hotels_list = by_city.get("data", [])
        hotel_ids = [h.get("hotelId") for h in hotels_list if h.get("hotelId")]
        hotel_ids = hotel_ids[:20]
        if not hotel_ids:
            logger.info(f"No hotels found for city {city_code} (REST)")
            return []

        # Step 2: /v3/shopping/hotel-offers
        offers = _rest_get(
            "/v3/shopping/hotel-offers",
            {
                "hotelIds": ",".join(hotel_ids),
                "adults": adults,
                "checkInDate": check_in,
                "checkOutDate": check_out,
                "currency": currency,
                "roomQuantity": rooms,
                "bestRateOnly": "true",
            },
        )
        data = offers.get("data", [])
        logger.info(f"Offers found (REST): {len(data)}")
        return data

    except ResponseError as e:
        logger.error(f"Amadeus SDK error: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error in search_hotels: {e}")
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
        logger.error(f"get_hotel_ratings failed for {hotel_id}: {e}")
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
        logger.error(f"search_activities failed: {e}")
        return []

