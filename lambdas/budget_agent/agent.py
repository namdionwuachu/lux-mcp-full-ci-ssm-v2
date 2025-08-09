"""Budget agent: compute nights, check per-night budget, add pool bonus, rank top N."""
from typing import Dict, Any, List
def run(task: Dict[str, Any]) -> Dict[str, Any]:
    hotels: List[dict] = task.get("hotels", []); max_price = task.get("max_price_gbp"); ci=task.get("check_in"); co=task.get("check_out")
    def nights(a,b):
        try: 
            from datetime import datetime as dt; return max((dt.strptime(b,"%Y-%m-%d")-dt.strptime(a,"%Y-%m-%d")).days,1)
        except: return 3
    n=nights(ci,co)
    for h in hotels:
        price=h.get("est_price_gbp"); h["passes_budget"]=(price is None) or (max_price is None) or (price/max(n,1) <= max_price)
        h["score"]=(2 if h.get("pool_bonus") else 0) + (1 if h["passes_budget"] else 0); h["nights"]=n
    ranked=sorted(hotels, key=lambda x:x["score"], reverse=True); return {"status":"ok","ranked":ranked[:5]}
