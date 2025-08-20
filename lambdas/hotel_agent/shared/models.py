from dataclasses import dataclass
from typing import Optional

@dataclass
class Stay:
    # required
    check_in: str
    check_out: str

    # optional / search params
    city_code: Optional[str] = None   # e.g. "LON"
    adults: int = 1
    wants_indoor_pool: bool = False

    # pricing
    max_price_gbp: Optional[float] = None

