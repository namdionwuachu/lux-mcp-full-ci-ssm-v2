"""Budget agent: compute nights, check per-night budget, add pool bonus, rank top N."""
from typing import Dict, Any, List, Optional

def _nights(a: Optional[str], b: Optional[str]) -> int:
    try:
        from datetime import datetime as dt
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

def run(task: Dict[str, Any]) -> Dict[str, Any]:
    hotels: List[dict] = task.get("hotels", []) or []
    max_price = _to_float(task.get("max_price_gbp"))
    n = _nights(task.get("check_in"), task.get("check_out"))
    top_n = int(task.get("top_n", 5) or 5)

    for h in hotels:
        price = _to_float(h.get("est_price_gbp"))
        passes = (price is None) or (max_price is None) or (price <= max_price)
        h["passes_budget"] = bool(passes)
        h["pool_bonus"] = bool(h.get("pool_bonus"))
        h["nights"] = n
        # 2 points for indoor pool preference bonus, 1 point if within budget
        h["score"] = (2 if h["pool_bonus"] else 0) + (1 if h["passes_budget"] else 0)

    # Stable ordering: score desc, then name asc for consistent UI
    ranked = sorted(
        hotels,
        key=lambda x: (x.get("score", 0), str(x.get("name", ""))),
        reverse=True
    )

    return {"status": "ok", "ranked": ranked[:top_n]}

