"""Budget agent: currency-agnostic, PER-NIGHT compare (no FX).
Filters under-budget, small pool bonus, rank top N.
Returns top + candidates for responder, and ranked (alias) for back-compat.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime as dt
import re

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

# ---------- amount extraction + per-night normalization ----------
# Allow comma decimals (e.g., "90,80")
_CLEAN_NUM = re.compile(r"[^\d,\.\-]")

def _num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = _CLEAN_NUM.sub("", x).strip()   # <- Python: .strip(), not .trim()
        # If it uses comma as decimal and no dot, convert comma to dot
        if "," in s and "." not in s:
            s = s.replace(",", ".")         # "90,80" -> "90.80"
        else:
            # Drop thousands separators: "1,234.56" -> "1234.56"
            s = s.replace(",", "")
        try:
            return float(s)
        except Exception:
            return None
    return None

def _dict_amount(d: dict):
    """Supports {'amount': 120, 'currency':'EUR'} or {'value':'120.00'}."""
    if not isinstance(d, dict):
        return None, None
    amt = _num(d.get("amount") if "amount" in d else d.get("value"))
    cur = d.get("currency") or d.get("curr") or d.get("code")
    return amt, (str(cur).upper() if cur else None)

def _first_amount(obj):
    if obj is None:
        return None, None

    # Prefer explicit nightly fields
    for k in ("per_night","per_night_amount","price_per_night","nightly","rate_per_night",
              "avg_nightly","average_nightly"):
        v = obj.get(k)
        if isinstance(v, dict):
            a,c = _dict_amount(v);  if a is not None: return a,c
        else:
            a = _num(v);            if a is not None: return a, obj.get("currency")

    # Text forms commonly emitted by providers / responders
    for k in ("price_text","est_price_text"):
        a = _num(obj.get(k))
        if a is not None:
            return a, obj.get("currency")

    # Average under price/pricing.variations.average
    for k in ("price","pricing"):
        pv = obj.get(k)
        if isinstance(pv, dict):
            avg = (((pv.get("variations") or {}).get("average") or {}))
            for kk in ("base","total","amount","value"):
                if kk in avg:
                    a = _num(avg.get(kk))
                    if a is not None:
                        return a, pv.get("currency")
        else:
            # price as scalar text/number
            a = _num(pv)
            if a is not None:
                return a, obj.get("currency")

    # Generic scalars (may be nightly or total)
    for k in ("est_price","est_price_gbp","price","per_night","total"):
        v = obj.get(k)
        if isinstance(v, dict):
            a,c = _dict_amount(v);  if a is not None: return a,c
        else:
            a = _num(v);            if a is not None: return a, obj.get("currency")

    # Explicit totals (use ÷ nights later)
    for tk in ("total","grand_total","stay_total"):
        v = obj.get(tk)
        if isinstance(v, dict):
            a,c = _dict_amount(v);  if a is not None: return a,c
        else:
            a = _num(v);            if a is not None: return a, obj.get("currency")

    # Look inside a nested 'raw' block if present
    raw = obj.get("raw")
    if isinstance(raw, dict):
        for k in ("price","price_text","est_price","est_price_gbp","total","grand_total","stay_total"):
            v = raw.get(k)
            if isinstance(v, dict):
                a,c = _dict_amount(v);  if a is not None: return a,c
            else:
                a = _num(v);            if a is not None: return a, raw.get("currency") or obj.get("currency")

    return None, None


def _per_night_amount(h: dict, nights: int) -> Optional[float]:
    """
    Returns a per-night numeric amount:
      1) Use explicit per-night/average if present.
      2) Else divide any total by nights.
    """
    if nights <= 0:
        nights = 1
    amt, _ = _first_amount(h)
    if amt is not None:
        return amt
    # Try nested totals
    for k in ("price","pricing"):
        pv = h.get(k)
        if isinstance(pv, dict):
            for tk in ("total","grand_total","stay_total"):
                tv = pv.get(tk)
                tamt = _num(tv) if not isinstance(tv, dict) else _dict_amount(tv)[0]
                if tamt is not None:
                    return tamt / max(nights,1)
    # Try top-level totals
    for tk in ("total","grand_total","stay_total"):
        tv = h.get(tk)
        tamt = _num(tv) if not isinstance(tv, dict) else _dict_amount(tv)[0]
        if tamt is not None:
            return tamt / max(nights,1)
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
    hotels: List[dict] = task.get("hotels", []) or []
    max_price = _to_float(task.get("max_price", task.get("max_price_gbp")))
    n = _nights(task.get("check_in"), task.get("check_out"))
    top_n = int(task.get("top_n", 5) or 5)

    enriched: List[dict] = []
    for h in hotels:
        price = _per_night_amount(h, n)
        pool = _has_indoor_pool(h)
        passes = (price is not None and (max_price is None or price <= max_price))

        ho = dict(h)
        ho["nights"] = n
        ho["has_indoor_pool"] = pool
        ho["price_per_night_norm"] = price
        ho["passes_budget"] = bool(passes)
        ho["budget_gap"] = (None if (price is None or max_price is None) else round(max_price - price, 2))
        ho["budget_reason"] = (
            "no_max_price" if max_price is None
            else "no_price" if price is None
            else "under" if price <= max_price
            else "over"
        )
        enriched.append(ho)

    # Full sorted list (for debugging)
    candidates_all = sorted(
        enriched,
        key=lambda x: _sort_key(x.get("price_per_night_norm"), str(x.get("name") or ""), bool(x.get("has_indoor_pool")))
    )

    # Under-budget only for outward-facing fields
    under_budget = [h for h in candidates_all if h.get("passes_budget")]
    top = under_budget[: top_n]

    return {
        "status": "ok",
        "top": top,                        # under-budget
        "candidates": under_budget,        # under-budget ONLY (responder uses this)
        "ranked": top,                     # back-compat
        "meta": {
            "total_in": len(hotels),
            "under_budget": len(under_budget),
            "nights": n,
            "unit": "per_night"
        },
        "debug_all_candidates": candidates_all,  # full list for logs/debug
    }
