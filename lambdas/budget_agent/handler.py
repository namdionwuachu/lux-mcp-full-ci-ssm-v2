"""Lambda shim for budget agent."""
import json
import logging
import base64
from typing import Any, Dict
from agent import run

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def _parse_task(event: Dict[str, Any]) -> Dict[str, Any]:
    # Direct Lambda invoke from the orchestrator (plain dict)
    # Orchestrator sends: {"hotels": [...], "max_price_gbp": ..., "check_in": ..., "check_out": ...}
    if isinstance(event, dict) and (
        "hotels" in event or "stay" in event or "check_in" in event or "check_out" in event
    ):
        return event

    # API Gateway (HTTP/API) proxy events
    body = event.get("body")
    if body is not None:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", "ignore")
        return json.loads(body) if body else {}

    # SQS-style events
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

def lambda_handler(event, context):
    try:
        task = _parse_task(event)
    except Exception as e:
        logger.exception("Failed to parse request")
        return _response(400, {"status": "error", "message": f"Bad request: {e}"})

    try:
        result = run(task or {})
        return _response(200, result)
    except Exception as e:
        logger.exception("Budget agent error")
        return _response(500, {"status": "error", "message": str(e)})

