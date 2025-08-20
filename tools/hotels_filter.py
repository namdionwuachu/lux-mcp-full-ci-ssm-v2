"""Amenity helpers + 4★+gym filter with optional indoor-pool bonus tagging."""
from typing import List, Dict, Any

GYM_TERMS = {
    "gym","fitness center","fitness centre","fitness room","health club",
    "fitness","workout room","wellness center","wellness centre"
}

def _norm(am) -> List[str]:
    if am is None: return []
    if isinstance(am, str): am = [am]
    out=[]
    for x in am:
        s=str(x).strip().lower()
        if s: out.append(s)
    return out

def has_gym(am: List[str]) -> bool:
    a = _norm(am)
    return any(t in x for x in a for t in GYM_TERMS)

def has_pool(am: List[str]) -> bool:
    return any("pool" in x for x in _norm(am))

def has_indoor_pool(am: List[str]) -> bool:
    a = _norm(am)
    return any(("indoor" in x and "pool" in x) or "indoor pool" in x for x in a)

def _stars(val) -> float:
    try: return float(val)
    except: return 0.0

def filter_four_star_with_gym(
    cands: List[Dict[str, Any]],
    *,
    wants_indoor_pool: bool | None = None,
    min_stars: float = 4.0
) -> List[Dict[str, Any]]:
    out=[]
    for h in cands or []:
        if _stars(h.get("stars")) >= min_stars and has_gym(h.get("amenities", [])):
            h2 = dict(h)  # don't mutate input
            if wants_indoor_pool is True:
                h2["pool_bonus"] = has_indoor_pool(h2.get("amenities", []))
            elif wants_indoor_pool is False:
                h2["pool_bonus"] = False
            else:
                h2["pool_bonus"] = has_pool(h2.get("amenities", []))
            out.append(h2)
    return out

