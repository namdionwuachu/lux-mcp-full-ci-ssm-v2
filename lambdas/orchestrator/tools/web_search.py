"""Provider facade honoring HOTEL_PROVIDER_ORDER (default: amadeus). Scraping is scaffolded but OFF."""

import os
from typing import Any, Dict, List
from .provider_amadeus import search_hotels as _amadeus_search

PREFERRED: List[str] = [p.strip().lower() for p in os.getenv("HOTEL_PROVIDER_ORDER", "amadeus").split(",") if p.strip()]

def search_hotels(stay: Any) -> List[Dict]:
    sd: Dict[str, Any] = stay.__dict__ if hasattr(stay, "__dict__") else dict(stay)
    results: List[Dict] = []
    for provider in PREFERRED or ["amadeus"]:
        if provider == "amadeus":
            results = _amadeus_search(sd)
        elif provider == "scrape":
            pass  # future provider
        if results:
            break
    return results

# Backward-compat (remove after callers are updated)
def search_hotels_marais_with_gym_and_pool(stay: Any) -> List[Dict]:
    return search_hotels(stay)

