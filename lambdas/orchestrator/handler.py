"""API entry: plan -> hotel_search -> budget_filter; optional responder narrative; CORS on."""
import json
import logging
import os
from typing import Any, Dict
import urllib.request

import boto3

from mcp import MCP
from agents import planner
from agents.responder import narrate

logger = logging.getLogger()
logger.setLevel(logging.INFO)

mcp = MCP()

# --- Feature flag: route via MCP HTTP instead of direct Lambda invokes ---
USE_MCP_HTTP = os.getenv("USE_MCP_HTTP", "false").lower() == "true"
MCP_URL = os.getenv("MCP_URL")  # e.g. https://<api-id>.execute-api.<region>.amazonaws.com/prod/mcp

# Invoke child agents via Lambda (names injected by CDK env vars)
LAM = boto3.client("lambda")
HOTEL_FN = os.getenv("HOTEL_FN")
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


def _invoke_mcp_http(tool_name: str, args: dict) -> dict:
    """Call MCP server over HTTP (JSON-RPC). No external deps; uses urllib."""
    if not MCP_URL:
        return {"status": "error", "error": "MCP_URL not set"}
    body = {
        "jsonrpc": "2.0",
        "id": f"orchestrator-{tool_name}",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args or {}},
    }
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            resp_text = r.read().decode("utf-8")
            envelope = json.loads(resp_text)
            result = envelope.get("result") or {}
            content = result.get("content") or []
            # Find first JSON content block
            for block in content:
                if isinstance(block, dict) and block.get("type") == "json":
                    return block.get("json") or {}
            # If error was flagged as content error
            if result.get("isError"):
                return {"status": "error", "error": "mcp_tool_error"}
            return {}
    except Exception as e:
        logger.exception("MCP HTTP call failed: %s", tool_name)
        return {"status": "error", "error": str(e)}


# Register routes -> either via MCP HTTP (flag) or direct Lambda
if USE_MCP_HTTP and MCP_URL:
    mcp.register("hotel_search", lambda t: _invoke_mcp_http("hotel_search", {"stay": t.get("stay")}))
    mcp.register(
        "budget_filter",
        lambda t: _invoke_mcp_http(
            "budget_filter",
            {
                "hotels": t.get("hotels", []),
                "max_price_gbp": t.get("max_price_gbp"),
                "check_in": t.get("check_in"),
                "check_out": t.get("check_out"),
                "top_n": t.get("top_n", 5),
            },
        ),
    )
else:
    mcp.register("hotel_search", lambda t: _invoke_lambda(HOTEL_FN, t))
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
        r2 = mcp.route(
            {
                "agent": "budget_filter",
                "hotels": candidates,
                "max_price_gbp": stay.get("max_price_gbp"),
                "check_in": stay["check_in"],
                "check_out": stay["check_out"],
            }
        )
        top = r2.get("ranked", []) or []

        # Assemble base result
        result = {"plan": plan, "candidates": candidates, "top": top}

        # Optional, context-aware narrative
        if use_responder:
            try:
                # Build responder context from the request (facts only)
                context = {
                    "query": query,
                    "city": stay.get("city") or stay.get("city_name") or stay.get("city_code"),
                    "city_code": stay.get("city_code"),
                    "check_in": stay.get("check_in") or stay.get("checkInDate"),
                    "check_out": stay.get("check_out") or stay.get("checkOutDate"),
                    "adults": stay.get("adults"),
                    "rooms": stay.get("roomQuantity", 1),
                    "currency": stay.get("currency", "GBP"),
                    "max_price_gbp": stay.get("max_price_gbp"),
                    "wants_indoor_pool": stay.get("amenities_pref") == "indoor_pool",
                    "plan_notes": plan.get("notes"),
                }
                result["narrative"] = narrate(top, candidates, context=context)
            except Exception as e:
                logger.warning("Responder failed: %s", e)
                result["narrative"] = None
        else:
            result["narrative"] = None

        return _resp(200, result)

    except Exception as e:
        logger.exception("Orchestrator error")
        return _resp(500, {"error": "server_error", "message": str(e)})

