"""API entry: plan -> hotel_search -> budget_filter; optional responder narrative; CORS on."""
import json
import logging
import os
from typing import Any, Dict

import boto3

from lambdas.orchestrator.mcp import MCP
from lambdas.orchestrator.agents import planner
from lambdas.orchestrator.agents.responder import narrate

logger = logging.getLogger()
logger.setLevel(logging.INFO)

mcp = MCP()

# Invoke child agents via Lambda (names injected by CDK env vars)
LAM = boto3.client("lambda")
HOTEL_FN  = os.getenv("HOTEL_FN")
BUDGET_FN = os.getenv("BUDGET_FN")

def _invoke_lambda(fn_name: str, payload: dict) -> dict:
    try:
        resp = LAM.invoke(
            FunctionName=fn_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        raw = resp["Payload"].read()
        j = json.loads(raw or b"{}")
        # Unwrap API-style responses from agents if present
        if isinstance(j, dict) and "statusCode" in j and "body" in j:
            return json.loads(j.get("body") or "{}")
        return j if isinstance(j, dict) else {}
    except Exception as e:
        logger.exception("Invoke %s failed", fn_name)
        return {"status": "error", "error": str(e)}

# Register routes -> invoke lambdas
mcp.register("hotel_search",  lambda t: _invoke_lambda(HOTEL_FN,  t))
mcp.register("budget_filter", lambda t: _invoke_lambda(BUDGET_FN, t))

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # tighten to your CF domain later
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "OPTIONS,POST",
    "Vary": "Origin",
}

def _resp(code: int, obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": json.dumps(obj),
    }

def _http_method(event: Dict[str, Any]) -> str:
    m = event.get("requestContext", {}).get("http", {}).get("method")
    return m or event.get("httpMethod") or "POST"

def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if not body:
        return {}
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8", "ignore")
    return json.loads(body)

def lambda_handler(event, context):
    method = _http_method(event)

    # Fast CORS preflight
    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    if method != "POST":
        return _resp(405, {"error": "method_not_allowed", "allowed": ["POST", "OPTIONS"]})

    try:
        body = _parse_body(event)
    except Exception as e:
        logger.exception("Bad JSON")
        return _resp(400, {"error": "bad_request", "message": f"Invalid JSON: {e}"})

    query = body.get("query")
    stay = body.get("stay") or {}
    use_responder = bool(body.get("use_responder"))

    # Basic validation
    for key in ("check_in", "check_out"):
        if not stay.get(key):
            return _resp(400, {"error": "missing_field", "message": f"missing stay.{key}"})

    try:
        # Plan (lightweight LLM)
        plan = planner.plan(query or "Find a 4-star hotel with a gym, prefer indoor pool.")

        # Hotel search
        r1 = mcp.route({"agent": "hotel_search", "stay": stay})
        candidates = r1.get("hotels", []) or []

        # Budget filter
        r2 = mcp.route({
            "agent": "budget_filter",
            "hotels": candidates,
            "max_price_gbp": stay.get("max_price_gbp"),
            "check_in": stay["check_in"],
            "check_out": stay["check_out"],
        })
        top = r2.get("ranked", []) or []

        result = {"plan": plan, "candidates": candidates, "top": top}

        if use_responder:
            try:
                result["narrative"] = narrate(top, candidates)
            except Exception as e:
                logger.warning("Responder failed: %s", e)
                result["narrative"] = None

        return _resp(200, result)

    except Exception as e:
        logger.exception("Orchestrator error")
        return _resp(500, {"error": "server_error", "message": str(e)})

