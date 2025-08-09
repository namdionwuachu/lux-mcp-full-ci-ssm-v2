"""Amenity helpers + 4★+gym filter with pool bonus tagging."""
from typing import List, Dict
GYM={"gym","fitness center","fitness centre","health club","fitness"}
def has_gym(am: List[str])->bool: a=[(x or '').lower() for x in am or []]; return any(x in GYM for x in a)
def has_pool(am: List[str])->bool: return any("pool" in (x or '').lower() for x in am or [])
def filter_four_star_with_gym(cands: List[Dict])->List[Dict]:
    out=[]; 
    for h in cands:
        if h.get("stars")==4 and has_gym(h.get("amenities",[])):
            h["pool_bonus"]=has_pool(h.get("amenities",[])); out.append(h)
    return out
