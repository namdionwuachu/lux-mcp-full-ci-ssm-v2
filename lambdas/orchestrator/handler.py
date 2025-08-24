"""MCP JSON-RPC entrypoint: tools/call only."""
import json
import logging
from typing import Any, Dict

from mcp import MCP
from agents import planner
from agents.responder import narrate

# ---- In-process tool registration (no downstream Lambdas/HTTP) ----
from tools.hotel_search import run as hotel_search_run
from tools.budget_filter import run as budget_filter_run

logger = logging.getLogger()
logger.setLevel(logging.INFO)

mcp = MCP()
mcp.register("hotel_search", lambda t: hotel_search_run(t))
mcp.register("budget_filter", lambda t: budget_filter_run(t))

# ---- CORS ----
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "ALLOW_ORIGIN",  # tighten 
    "Access-Control-Allow-Headers": "Content-Type,Authorization,x-correlation-id",
    "Access-Control-Allow-Methods": "OPTIONS,POST",
    "Access-Control-Max-Age": "600",
    "Vary": "Origin",
    "Content-Type": "application/json",
}

def _resp(code: int, obj: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "statusCode": code,
        "headers": CORS_HEADERS,                # <-- always include
        "body": "" if obj is None else json.dumps(obj),
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

def _wrap_ok(rid: Any, payload: Any) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "result": {
            "content": [
                {"type": "json", "json": payload}
            ]
        }
    }

def lambda_handler(event, context):
    method = _http_method(event)


    # CORS preflight
    if method == "OPTIONS":
    # No body for preflight; headers do the work
    return _resp(204)  # <- empty body, same CORS headers
    
    
    if method != "POST":
        return _resp(405, {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Invalid Request"}})

    # Parse JSON
    try:
        body = _parse_body(event)
    except Exception as e:
        return _resp(400, {"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":f"Parse error: {e}"}})

    rid = body.get("id")
    if body.get("jsonrpc") != "2.0":
        return _resp(400, {"jsonrpc":"2.0","id":rid,"error":{"code":-32600,"message":"Invalid Request"}})

    if body.get("method") != "tools/call":
        return _resp(400, {"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"Method not found"}})

    params = body.get("params") or {}
    name = params.get("name")
    arguments = params.get("arguments") or {}

    if not name:
        return _resp(400, {"jsonrpc":"2.0","id":rid,"error":{"code":-32602,"message":"Missing params.name"}})

    try:
        # ---- Dispatch supported tools ----
        if name == "plan":
            q = arguments.get("query") or ""
            payload = planner.plan(q)

        elif name == "hotel_search":
            stay = arguments.get("stay") or arguments
            payload = mcp.route({"agent": "hotel_search", "stay": stay})

        elif name == "budget_filter":
            hotels = arguments.get("candidates") or arguments.get("hotels") or []
            payload = mcp.route({
                "agent": "budget_filter",
                "hotels": hotels,
                "max_price_gbp": arguments.get("budget_max") or arguments.get("max_price_gbp"),
                "check_in": arguments.get("check_in") or (arguments.get("stay") or {}).get("check_in"),
                "check_out": arguments.get("check_out") or (arguments.get("stay") or {}).get("check_out"),
                "top_n": arguments.get("top_n", 5),
            })

        elif name == "responder_narrate":
            top = arguments.get("top") or []
            candidates = arguments.get("candidates") or []
            context = arguments.get("context") or {}
            payload = {"text": narrate(top, candidates, context=context)}

        else:
            return _resp(400, {"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":f"Unknown tool: {name}"}})

        return _resp(200, _wrap_ok(rid, payload))

    except Exception as e:
        logger.exception("tools/call failed")
        return _resp(500, {"jsonrpc":"2.0","id":rid,"error":{"code":-32000,"message":str(e)}})
