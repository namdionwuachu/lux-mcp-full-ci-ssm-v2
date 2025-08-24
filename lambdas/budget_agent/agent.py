"""Budget agent: GBP-only, filter under-budget, small pool bonus, rank top N.
Returns top + candidates for responder, and ranked (alias) for back-compat.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime as dt

def _nights(a: Optional[str], b: Optional[str]) -> int:
    try:
        return max((dt.strptime(b, "%Y-%m-%d") - dt.strptime(a, "%Y-%m-%d")).days, 1)
    except Exception:
        return 3

def _to_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None

def _price_gbp(h: dict) -> Optional[float]:
    """Prefer est_price_gbp; accept a couple of legacy fallbacks."""
    for key in ("est_price_gbp", "est_price", "price_gbp", "price"):
        p = _to_float(h.get(key))
        if p is not None:
            return p
    return None

def _has_indoor_pool(h: dict) -> bool:
    ams = h.get("amenities") or []
    if not isinstance(ams, list):
        return False
    for a in ams:
        if not isinstance(a, str):
            continue
        s = a.lower()
        if "indoor pool" in s or ("indoor" in s and "pool" in s):
            return True
    return False

def _sort_key(price: Optional[float], name: str, pool: bool) -> Tuple[int, float, str]:
    """Priced first, cheapest first, tiny tie-break for indoor pool."""
    if price is None:
        return (1, float("inf"), name or "")
    adj = price - 0.01 if pool else price
    return (0, adj, name or "")

def run(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inputs:
      hotels: List[dict]
      max_price_gbp: float | None
      check_in, check_out: YYYY-MM-DD
      top_n: int
    Output:
      { status, top, candidates, ranked, meta }
    """
    hotels: List[dict] = task.get("hotels", []) or []
    max_price = _to_float(task.get("max_price_gbp"))
    n = _nights(task.get("check_in"), task.get("check_out"))
    top_n = int(task.get("top_n", 5) or 5)

    enriched: List[dict] = []
    for h in hotels:
        name = h.get("name") or ""
        price = _price_gbp(h)
        pool = _has_indoor_pool(h)

        passes = (price is not None and max_price is not None and price <= max_price)

        ho = dict(h)
        ho["nights"] = n
        ho["has_indoor_pool"] = pool
        ho["price_gbp_norm"] = price   # normalized numeric price in GBP
        ho["passes_budget"] = bool(passes)
        enriched.append(ho)

    # All candidates sorted by GBP price (unpriced last), with small pool tie-breaker
    candidates = sorted(
        enriched,
        key=lambda x: _sort_key(x.get("price_gbp_norm"), str(x.get("name") or ""), bool(x.get("has_indoor_pool")))
    )

    # Top = under-budget cheapest first
    under_budget = [h for h in candidates if h.get("passes_budget")]
    top = under_budget[: top_n]

    return {
        "status": "ok",
        "top": top,
        "candidates": candidates,
        "ranked": top,  # back-compat alias for any legacy caller
        "meta": {"total_in": len(hotels), "under_budget": len(under_budget), "nights": n},
    }
