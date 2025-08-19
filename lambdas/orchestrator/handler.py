"""API entry: plan -> hotel_search -> budget_filter; optional responder narrative; CORS on."""
import json
import logging
from typing import Any, Dict
from lambdas.orchestrator.mcp import MCP
from lambdas.orchestrator.agents import planner
from lambdas.orchestrator.agents.responder import narrate
from lambdas.hotel_agent.agent import run as hotel_run
from lambdas.budget_agent.agent import run as budget_run

logger = logging.getLogger()
logger.setLevel(logging.INFO)

mcp = MCP()
mcp.register("hotel_search", lambda t: hotel_run(t))
mcp.register("budget_filter", lambda t: budget_run(t))

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",                # consider restricting to your CF domain
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
    # HTTP API v2
    m = event.get("requestContext", {}).get("http", {}).get("method")
    if m:
        return m
    # REST API v1
    return event.get("httpMethod") or "POST"

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

    # CORS preflight
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
        if key not in stay or not stay[key]:
            return _resp(400, {"error": "missing_field", "message": f"missing stay.{key}"})

    try:
        # Plan (lightweight)
        plan = planner.plan(query or "Find a 4-star hotel with a gym, prefer indoor pool.")

        # Hotel search
        r1 = mcp.route({"agent": "hotel_search", "stay": stay})
        candidates = r1.get("hotels", []) or []

        # Budget filter (expects per-night est_price_gbp; aligned with your UI)
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
                # Don’t fail the whole request if narrative generation hiccups
                logger.warning("Responder failed: %s", e)
                result["narrative"] = None

        return _resp(200, result)

    except Exception as e:
        logger.exception("Orchestrator error")
        return _resp(500, {"error": "server_error", "message": str(e)})

