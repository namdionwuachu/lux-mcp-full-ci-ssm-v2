"""Lambda shim for hotel agent."""
import os
import json
import logging
import base64
from typing import Any, Dict
from agent import run  # keep available as a fallback/flag
from tools import provider_amadeus as amadeus

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "OPTIONS,POST",
}

# Feature flag: default to direct provider (normalized hotel cards)
USE_DIRECT = os.getenv("HOTEL_AGENT_DIRECT", "true").lower() == "true"

def parse_task(event: Dict[str, Any]) -> Dict[str, Any]:
    # Direct Lambda invoke (from CLI or another lambda)
    if isinstance(event, dict) and ("stay" in event or "hotels" in event or "method" in event):
        return event
    
    # API Gateway (HTTP/API) proxy events
    body = event.get("body")
    if body is not None:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", "ignore")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}
    
    # SQS-style events
    records = event.get("Records")
    if isinstance(records, list) and records:
        b = records[0].get("body")
        try:
            parsed = json.loads(b) if b else {}
        except Exception:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}
    
    return {}

# >>> added: helper to safely extract narrator text from an agent.run tool response
def _extract_narrative(tool_result: Dict[str, Any]) -> str:
    try:
        content0 = (tool_result.get("content") or [{}])[0]
        j = content0.get("json") or {}
        return j.get("text") or content0.get("text") or ""
    except Exception:
        return ""

def _response(status: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status, "headers": CORS, "body": json.dumps(payload)}

def lambda_handler(event, context):
    try:
        task = parse_task(event)
    except Exception as e:
        logger.exception("Failed to parse request")
        return _response(400, {"status": "error", "message": f"Bad request: {e}"})

    # >>> added: if the request arrived as JSON‑RPC, unwrap to just the arguments
    # supports: {"jsonrpc":"2.0","method":"tools/call","params":{"name":"hotel_search","arguments":{...}}}
    if isinstance(task, dict) and task.get("method") == "tools/call":
        params = task.get("params") or {}
        # only unwrap if it's for this tool
        if (params.get("name") or "").strip() == "hotel_search":
            task = params.get("arguments") or {}

    try:
        if USE_DIRECT:
            # ---- Normalize inputs (city/country_code OR lat/lon) + stay
            stay = task.get("stay", {}) if isinstance(task, dict) else {}

            # allow city or city_code — provider can decide what to use
            city = (task.get("city") or task.get("destination") or "").strip()
            city_code = (task.get("city_code") or "").strip().upper()  # >>> added (non‑breaking)
            country_code = (task.get("country_code") or "").strip().upper()
            loc = task.get("location") or {}

            query = {
                "stay": stay,
                "location": {
                    "lat": float(loc["lat"]) if isinstance(loc, dict) and "lat" in loc else None,
                    "lon": float(loc["lon"]) if isinstance(loc, dict) and "lon" in loc else None,
                    "radius_km": int(loc.get("radius_km", 15)) if isinstance(loc, dict) else None,
                },
                "city": city or None,
                "city_code": city_code or None,   # >>> added (passed through)
                "country_code": country_code or None,
                "budget_max": task.get("budget_max"),
                "preferences": task.get("preferences") or [],
                "neighborhood": task.get("neighborhood"),  # >>> optional pass‑through
                "currency": (stay or {}).get("currency"),  # >>> ensure currency flows through
            }

            # Clean out Nones
            query["location"] = {k: v for k, v in (query["location"] or {}).items() if v is not None} or None
            query = {k: v for k, v in query.items() if v not in (None, {}, [])}

            hotels = amadeus.search_hotels(query)  # already-normalized cards (list)
            logger.info({"stage": "handler_hotels_count", "count": len(hotels)})

            
            # --- Normalize provider output to a list (some adapters return {"status":"ok","hotels":[...]})
            hotel_list = None
            if isinstance(hotels, dict):
                hotel_list = hotels.get("hotels") or hotels.get("data") or []
            elif isinstance(hotels, list):
                hotel_list = hotels
            else:
                hotel_list = []

            # --- Always return the wrapped envelope that the frontend expects
            resp = {
                "status": "ok",
                "hotels": {"status": "ok", "hotels": hotel_list},
                "meta": {"path": "direct"}  # breadcrumb so you can verify route in curl
            }

            # --- If empty, don't call narrator; add a clear reason
            if not hotel_list:
                resp["meta"]["reason"] = "provider_zero"
                resp["narrative"] = "No live availability from suppliers for those dates/location."
                return _response(200, resp)

            # --- Only call the responder if explicitly requested and we have hotels
            use_responder = bool(task.get("use_responder"))
            if use_responder:
                top = [
                    {"name": h.get("name"), "id": h.get("id"), "est_price_gbp": h.get("est_price_gbp")}
                    for h in hotel_list[:5]
                ]
                narr_env = {
                    "jsonrpc": "2.0",
                    "id": "rn",
                    "method": "tools/call",
                    "params": {"name": "responder_narrate", "arguments": {"top": top, "candidates": []}},
                }
                try:
                    narr_out = run(narr_env) or {}
                    narr_result = narr_out.get("result") or narr_out
                    narrative_text = _extract_narrative(narr_result)
                    if narrative_text:
                        resp["narrative"] = narrative_text
                        resp["use_responder"] = True
                except Exception as narr_e:
                    logger.warning("Narrator failed: %s", narr_e)

            return _response(200, resp)

        else:
            # Legacy pipeline, if you need it
            result = run(task or {})
            return _response(200, result)

    except Exception as e:
        logger.exception("Hotel agent error")
        # keep 200 to avoid frontend hard errors; return empty list
        return _response(200, {"status": "ok", "hotels": []})
