"""Shared dataclasses for stay request and hotel result."""
from dataclasses import dataclass
from typing import List, Optional
@dataclass
class Stay:
    city: str; neighborhood: str; check_in: str; check_out: str; adults: int
    site: str = "Hotels.com"; max_price_gbp: Optional[float] = None; wants_indoor_pool: bool = False
@dataclass
class Hotel:
    name: str; stars: int; url: str; location_note: str; amenities: List[str]
    est_price_gbp: Optional[float] = None
