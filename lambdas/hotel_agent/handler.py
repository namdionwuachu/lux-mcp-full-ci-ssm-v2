"""Lambda shim for hotel agent."""
import os
import json
import logging
import base64
from typing import Any, Dict
from agent import run # keep available as a fallback/flag
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
    if isinstance(event, dict) and ("stay" in event or "hotels" in event):
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

def _response(status: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status, "headers": CORS, "body": json.dumps(payload)}

def lambda_handler(event, context):
    try:
        task = parse_task(event)
    except Exception as e:
        logger.exception("Failed to parse request")
        return _response(400, {"status": "error", "message": f"Bad request: {e}"})
    
    try:
        if USE_DIRECT:
            # ---- Normalize inputs (city/country_code OR lat/lon) + stay
            stay = task.get("stay", {}) if isinstance(task, dict) else {}
            city = (task.get("city") or task.get("destination") or "").strip()
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
                "country_code": country_code or None,
                "budget_max": task.get("budget_max"),
                "preferences": task.get("preferences") or [],
            }
            
            # Clean out Nones
            query["location"] = {k: v for k, v in (query["location"] or {}).items() if v is not None} or None
            
            hotels = amadeus.search_hotels(query) # already-normalized cards
            logger.info({"stage": "handler_hotels_count", "count": len(hotels)})
            return _response(200, {"status": "ok", "hotels": hotels})
        else:
            # Legacy pipeline, if you need it
            result = run(task or {})
            return _response(200, result)
    except Exception as e:
        logger.exception("Hotel agent error")
        return _response(200, {"status": "ok", "hotels": []})