# orchestrator/mcp_server.py
import os, json, boto3, traceback
from typing import Dict, Any

LAM = boto3.client("lambda")
HOTEL_FN  = os.getenv("HOTEL_FN")   # arn or name of your hotel_agent lambda
BUDGET_FN = os.getenv("BUDGET_FN")  # arn or name of your budget_agent lambda
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

def _resp(code: int, body: Dict[str, Any]):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type":"application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers":"Content-Type,Authorization,x-correlation-id",
            "Access-Control-Allow-Methods":"OPTIONS,POST",
            "Access-Control-Max-Age":"600",
        },
        "body": json.dumps(body),
    }

def _invoke(fn: str, payload: dict) -> dict:
    r = LAM.invoke(FunctionName=fn, InvocationType="RequestResponse",
                   Payload=json.dumps(payload).encode("utf-8"))
    raw = r["Payload"].read()
    try:
        j = json.loads(raw or b"{}")
        if isinstance(j, dict) and "statusCode" in j and "body" in j:
            return json.loads(j.get("body") or "{}")
        return j if isinstance(j, dict) else {}
    except Exception:
        return {"status":"error","error":"invalid_lambda_response"}

# ---- MCP handlers ----

def _initialize(_req):
    return {
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name":"lux-mcp-server","version":"0.1.0"},
    }

def _tools_list(_req):
    return {"tools":[
        {"name":"hotel_search","description":"Find hotels",
         "inputSchema":{"type":"object","properties":{
           "stay":{"type":"object","properties":{
             "check_in":{"type":"string"},"check_out":{"type":"string"},
             "city_code":{"type":"string"},"adults":{"type":"number"},
             "wants_indoor_pool":{"type":"boolean"},"max_price_gbp":{"type":"number"}
           },"required":["check_in","check_out"]}},"required":["stay"]}},
        {"name":"budget_filter","description":"Rank hotels under budget with pool bonus",
         "inputSchema":{"type":"object","properties":{
           "hotels":{"type":"array","items":{"type":"object"}},
           "max_price_gbp":{"type":"number"},
           "check_in":{"type":"string"},"check_out":{"type":"string"},
           "top_n":{"type":"number"}
         },"required":["hotels","check_in","check_out"]}},
        {"name":"responder_narrate","description":"Summarize results (plain text)",
         "inputSchema":{"type":"object","properties":{
           "top":{"type":"array","items":{"type":"object"}},
           "candidates":{"type":"array","items":{"type":"object"}}
         },"required":["top","candidates"]}},
        {"name":"planner_plan","description":"Produce ordered agent plan",
         "inputSchema":{"type":"object","properties":{"query":{"type":"string"}}}}
    ]}

def _tools_call(req):
    p = req.get("params",{}) or {}
    name = p.get("name")
    args = p.get("arguments") or {}
    rid  = args.get("request_id")

    try:
        if name == "hotel_search":
            out = _invoke(HOTEL_FN, {"stay": args.get("stay"), "task_id": rid})
        elif name == "budget_filter":
            out = _invoke(BUDGET_FN, {
                "hotels": args.get("hotels", []),
                "max_price_gbp": args.get("max_price_gbp"),
                "check_in": args.get("check_in"),
                "check_out": args.get("check_out"),
                "top_n": args.get("top_n", 5),
                "task_id": rid,
            })
        elif name == "responder_narrate":
            from agents.responder import narrate
            out = {"status":"ok","text": narrate(args.get("top",[]), args.get("candidates",[]))}
        elif name == "planner_plan":
            from agents import planner
            out = planner.plan(args.get("query") or "")
        else:
            return {"content":[{"type":"text","text": f"unknown tool: {name}"}], "isError": True}

        if isinstance(out, dict) and out.get("status") == "error":
            return {"content":[{"type":"text","text": out.get("error","agent_error")}], "isError": True}

        blocks = [{"type":"json","json": out if isinstance(out, dict) else {"data": out}}]
        if rid:
            blocks.append({"type":"text","text": f"request_id={rid}"})
        return {"content": blocks}

    except Exception as e:
        return {"content":[{"type":"text","text": f"error: {e}"}], "isError": True}

HANDLERS = {"initialize": _initialize, "tools/list": _tools_list, "tools/call": _tools_call}

def lambda_handler(event, context):
    method = (event.get("requestContext",{}).get("http",{}) or {}).get("method") or event.get("httpMethod")
    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    try:
        body = event.get("body")
        req  = json.loads(body) if isinstance(body, str) else (body or {})
        if not isinstance(req, dict):
            return _resp(400, {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Invalid Request"}})

        fn = HANDLERS.get(req.get("method"))
        if not fn:
            return _resp(400, {"jsonrpc":"2.0","id":req.get("id"),"error":{"code":-32601,"message":"Method not found"}})

        result = fn(req)
        return _resp(200, {"jsonrpc":"2.0","id":req.get("id"),"result": result})

    except Exception as e:
        return _resp(500, {"jsonrpc":"2.0","id":None,"error":{"code":-32000,"message":str(e),"data":traceback.format_exc()}})

