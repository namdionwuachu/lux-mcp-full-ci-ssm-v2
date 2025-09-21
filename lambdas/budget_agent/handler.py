"""Lambda shim for budget agent."""
import json
import logging
import base64
from datetime import date
from typing import Any, Dict, List, Optional
from agent import run
import re

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def _parse_task(event: Dict[str, Any]) -> Dict[str, Any]:
    # Direct invoke (dict from orchestrator)
    if isinstance(event, dict) and ("hotels" in event or "stay" in event or "check_in" in event or "check_out" in event):
        return event

    # API Gateway / Lambda proxy
    body = event.get("body")
    if body is not None:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", "ignore")
        return json.loads(body) if body else {}

    # SQS
    records = event.get("Records")
    if isinstance(records, list) and records:
        b = records[0].get("body")
        return json.loads(b) if b else {}

    return {}

def _response(status: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
        },
        "body": json.dumps(payload),
    }

# ---------- helpers for budget enforcement ----------
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Add/keep this near the top with your other helpers

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM_RE.search(str(v))
    if not m:
        return None
    s = m.group(0)
    if "," in s and "." not in s:
        s = s.replace(",", ".")   # 90,80 -> 90.80
    else:
        s = s.replace(",", "")    # 1,234.56 -> 1234.56
    try:
        return float(s)
    except Exception:
        return None

def _per_night(h: Dict[str, Any], nights: int) -> Optional[float]:
    # 1) Explicit per-night/average nightly
    for k in ("per_night","per_night_amount","price_per_night","nightly","rate_per_night",
              "avg_nightly","average_nightly","price_text","est_price_text"):
        v = h.get(k)
        f = _to_float(v)
        if f is not None:
            return f

    # 2) price/pricing dicts (including variations.average)
    for k in ("price","pricing"):
        pv = h.get(k)
        if isinstance(pv, dict):
            avg = ((pv.get("variations") or {}).get("average") or {})
            for kk in ("base","total","amount","value"):
                f = _to_float(avg.get(kk))
                if f is not None:
                    return f
        else:
            f = _to_float(pv)
            if f is not None:
                return f

    # 3) Generic scalars that might already be nightly
    for k in ("est_price","est_price_gbp","price","per_night","total"):
        f = _to_float(h.get(k))
        if f is not None:
            return f

    # 4) Totals → divide by nights
    for tk in ("total","grand_total","stay_total"):
        f = _to_float(h.get(tk))
        if f is not None and nights > 0:
            return f / nights

    # 5) Look inside a nested 'raw' block if present
    raw = h.get("raw")
    if isinstance(raw, dict):
        for k in ("price","price_text","est_price","est_price_gbp","total","grand_total","stay_total"):
            v = raw.get(k)
            f = _to_float(v)
            if f is not None:
                # if it’s a total, normalize by nights
                if k in ("total","grand_total","stay_total") and nights > 0:
                    return f / nights
                return f

    return None


def _filter_hotels(hotels: List[Dict[str, Any]],
                   max_price: Optional[float],
                   currency: Optional[str],
                   nights: int) -> List[Dict[str, Any]]:
    if not hotels:
        return hotels
    if max_price is None:
        # No cap → return as-is
        return hotels

    kept: List[Dict[str, Any]] = []
    priced = 0

    for h in hotels:
        pn = _per_night(h, nights)
        if pn is not None:
            priced += 1
        if pn is not None and pn <= max_price:
            out = dict(h)
            out.setdefault("est_price", pn)
            out.setdefault("price_per_night_norm", pn)
            out["passes_budget"] = True
            if currency:
                out["currency"] = str(currency).upper()
            kept.append(out)

    logger.info("[FILTER] budget=%s priced=%d/%d kept=%d",
                max_price, priced, len(hotels), len(kept))
    return kept

# ---------------------------------------------------

def lambda_handler(event, context):
    # Parse
    try:
        task = _parse_task(event)
    except Exception as e:
        logger.exception("Failed to parse request")
        return _response(400, {"status": "error", "message": f"Bad request: {e}"})

    # Normalize, pre-filter, call agent, post-filter
    try:
        task = task or {}

        # Back-compat: prefer max_price over legacy
        if "max_price" not in task and "max_price_gbp" in task:
            task["max_price"] = task.get("max_price_gbp")

        stay = task.get("stay") or {}
        task.setdefault("max_price", stay.get("max_price") or stay.get("max_price_gbp"))
        task.setdefault("check_in",  stay.get("check_in"))
        task.setdefault("check_out", stay.get("check_out"))
        # ✅ standardize currency to uppercase
        cur = stay.get("currency") or task.get("currency")
        task["currency"] = (str(cur).upper() if cur else None)

        nights = _nights(task.get("check_in"), task.get("check_out"))
        max_price = _to_float(task.get("max_price"))

        logger.info(
            "Budget shim IN: city=%s currency=%s max_price=%s nights=%s hotels_in=%s",
            (stay.get("city_code") or task.get("city_code")),
            task.get("currency"),
            max_price,
            nights,
            len(task.get("hotels") or []),
        )

        # Pre-filter inline hotels (if orchestrator attached them)
        if isinstance(task.get("hotels"), list) and task["hotels"]:
            task["hotels"] = _filter_hotels(task["hotels"], max_price, task.get("currency"), nights)

        # Agent
        result = run(task)

        # Post-filter (defensive): enforce on common shapes
        try:
            logger.info("[POST-FILTER] enforcing budget on direct & JSON-RPC shapes")
            def _filter_in_place(lst):
                return _filter_hotels(lst, max_price, task.get("currency"), nights)

            # Direct shapes
            if isinstance(result, dict) and isinstance(result.get("hotels"), list):
                result["hotels"] = _filter_in_place(result["hotels"])
            if isinstance(result, dict) and isinstance(result.get("candidates"), list):
                result["candidates"] = _filter_in_place(result["candidates"])
            if isinstance(result, dict) and isinstance(result.get("top"), list):
                result["top"] = _filter_in_place(result["top"])

            # JSON-RPC shape
            content = result.get("result", {}).get("content", []) if isinstance(result, dict) else []
            if content and isinstance(content[0], dict):
                j = content[0].get("json") or {}

                # a) j["hotels"] is a list
                if isinstance(j.get("hotels"), list):
                    j["hotels"] = _filter_in_place(j["hotels"])

                # b) j["hotels"] is a dict with nested ["hotels"] list
                elif isinstance(j.get("hotels"), dict) and isinstance(j["hotels"].get("hotels"), list):
                    j["hotels"]["hotels"] = _filter_in_place(j["hotels"]["hotels"])

                # Also filter optional fields if present
                if isinstance(j.get("candidates"), list):
                    j["candidates"] = _filter_in_place(j["candidates"])
                if isinstance(j.get("top"), list):
                    j["top"] = _filter_in_place(j["top"])

                content[0]["json"] = j
                result["result"]["content"][0] = content[0]
        except Exception:
            logger.exception("Post-filter failed; returning unfiltered result")