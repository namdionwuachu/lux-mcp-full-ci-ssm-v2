# lambdas/hotel_agent/agent.py
"""Hotel agent: provider search (city/neighborhood/geo), 4★+gym filter, per-night price."""
from typing import Dict, Any, List
from datetime import date
from shared.models import Stay
# ❌ from tools.web_search import search_hotels
# ✅ use the real provider
from tools.provider_amadeus import search_hotels
from tools.hotels_filter import filter_four_star_with_gym

def _nights(ci: str, co: str) -> int:
    try:
        return max((date.fromisoformat(co) - date.fromisoformat(ci)).days, 1)
    except Exception:
        return 3

def _normalize_hotel(h: Dict[str, Any], nights: int) -> Dict[str, Any]:
    out = dict(h)
    out.setdefault("name", out.get("hotel_name", "Hotel"))
    out.setdefault("location_note", out.get("neighborhood", ""))

    stars = out.get("stars", out.get("rating", 0))
    try:
        stars = float(stars)
    except Exception:
        stars = 0.0
    out["stars"] = stars

    am = out.get("amenities") or out.get("amenity_list") or []
    if isinstance(am, str):
        am = [am]
    out["amenities"] = am

    if out.get("est_price_gbp") is None:
        if out.get("price_per_night_gbp") is not None:
            try:
                out["est_price_gbp"] = float(out["price_per_night_gbp"])
            except Exception:
                out["est_price_gbp"] = None
        elif out.get("total_price_gbp") is not None:
            try:
                out["est_price_gbp"] = float(out["total_price_gbp"]) / max(nights, 1)
            except Exception:
                out["est_price_gbp"] = None
    return out

def run(task: Dict[str, Any]) -> Dict[str, Any]:
    stay = Stay(**task["stay"])
    nights = _nights(stay.check_in, stay.check_out)

    candidates: List[Dict[str, Any]] = search_hotels(stay)

    hotels = filter_four_star_with_gym(
        candidates,
        wants_indoor_pool=bool(getattr(stay, "wants_indoor_pool", False)),
        min_stars=4.0,
    )
    out = [_normalize_hotel(h, nights) for h in hotels]
    return {"status": "ok", "hotels": out}



      
  
