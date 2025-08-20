
"""Lambda shim for hotel agent."""
import json
import logging
from typing import Any, Dict, Optional
from agent import run

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def _parse_task(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # API Gateway (HTTP/API) proxy events
    if "body" in event:
        body = event["body"]
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode("utf-8", "ignore")
        return json.loads(body) if body else {}
    # SQS-style events
    if isinstance(event.get("Records"), list) and event["Records"]:
        body = event["Records"][0].get("body")
        return json.loads(body) if body else {}
    # Fallback
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
        logger.exception("Hotel agent error")
        return _response(500, {"status": "error", "message": str(e)})
