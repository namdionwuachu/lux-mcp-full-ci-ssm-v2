"""Provider facade honoring HOTEL_PROVIDER_ORDER (default: amadeus). Scraping is scaffolded but OFF."""
import os
from typing import List, Dict
from .provider_amadeus import search_hotels as amadeus_search
PREFERRED = [p.strip() for p in os.getenv("HOTEL_PROVIDER_ORDER", "amadeus").split(",")]
def search_hotels_marais_with_gym_and_pool(stay) -> List[Dict]:
    sd = stay.__dict__ if hasattr(stay, "__dict__") else dict(stay)
    results: List[Dict] = []
    for provider in PREFERRED:
        if provider == "amadeus":
            results = amadeus_search(sd)
        elif provider == "scrape":
            # Not implemented yet (Phase 2). Safe no-op.
            continue
        if results:
            break
    return results
