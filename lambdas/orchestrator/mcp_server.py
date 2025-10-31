# orchestrator/mcp_server.py
import os, json, boto3, traceback, re
from typing import Dict, Any
from datetime import datetime

from agents.planner import plan as planner_agent_plan  # robust planner

LAM = boto3.client("lambda")
HOTEL_FN  = os.getenv("HOTEL_FN")   # arn or name of your hotel_agent lambda
BUDGET_FN = os.getenv("BUDGET_FN")  # arn or name of your budget_agent lambda
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")
INCLUDE_RESPONDER = os.getenv("INCLUDE_RESPONDER", "true").lower() == "true"


def _resp(code: int, body: Dict[str, Any]):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "Content-Type,Authorization,x-correlation-id",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
            "Access-Control-Max-Age": "600",
        },
        "body": json.dumps(body),
    }


def _invoke(fn: str, payload: dict) -> dict:
    r = LAM.invoke(
        FunctionName=fn,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = r["Payload"].read()
    try:
        j = json.loads(raw or b"{}")
        if isinstance(j, dict) and "statusCode" in j and "body" in j:
            return json.loads(j.get("body") or "{}")
        return j if isinstance(j, dict) else {}
    except Exception:
        return {"status": "error", "error": "invalid_lambda_response"}

def _normalize_date(d):
    """Accept DD/MM/YYYY, YYYY-MM-DD, or ISO strings; return YYYY-MM-DD."""
    if not d:
        return None
    s = str(d).strip()
    try:
        # UK style: 31/10/2025
        if "/" in s:
            return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
        # ISO-like: 2025-10-31 or 2025-10-31T00:00:00Z
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        # Fallback: first 10 chars as YYYY-MM-DD
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:
            return s  # last resort: pass through

# ---- MCP handlers ----

def _initialize(_req):
    return {
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "lux-mcp-server", "version": "0.1.2"},
    }


def _tools_list(_req):
    return {
        "tools": [
            {
                "name": "hotel_search",
                "description": "Find hotels",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "stay": {
                            "type": "object",
                            "properties": {
                                "check_in": {"type": "string"},
                                "check_out": {"type": "string"},
                                "city_code": {"type": "string"},
                                "adults": {"type": "number"},
                                "wants_indoor_pool": {"type": "boolean"},
                                "max_price_gbp": {"type": "number"},
                            },
                            "required": ["check_in", "check_out"],
                        }
                    },
                    "required": ["stay"],
                },
            },
            {
                "name": "budget_filter",
                "description": "Rank hotels under budget with pool bonus",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hotels": {"type": "array", "items": {"type": "object"}},
                        "max_price_gbp": {"type": "number"},
                        "check_in": {"type": "string"},
                        "check_out": {"type": "string"},
                        "top_n": {"type": "number"},
                    },
                    "required": ["hotels", "check_in", "check_out"],
                },
            },
            {
                "name": "responder_narrate",
                "description": "Summarize results (plain text)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "top": {"type": "array", "items": {"type": "object"}},
                        "candidates": {"type": "array", "items": {"type": "object"}},
                        "context": {"type": "object"}
                    },
                    "required": ["top", "candidates"],
                },
            },
            {
                "name": "planner_plan",
                "description": "Produce ordered agent plan",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
            {
                "name": "plan",  # convenience alias
                "description": "Alias of planner_plan",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
            {
                "name": "planner_execute",
                "description": "Plan + search + filter + (optionally) narrate in one call",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "stay": {"type": "object"},
                        "top_n": {"type": "number"}
                    }
                },
            },
        ]
    }


def _planner_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Thin adapter around agents.planner.plan. Always returns a stable shape."""
    q = (args.get("query") or "") if isinstance(args, dict) else ""
    try:
        out = planner_agent_plan(q) if isinstance(q, str) else planner_agent_plan(query=q)
        if not isinstance(out, dict):
            out = {}
    except Exception as e:
        out = {"agents": ["hotel_search", "budget_filter"], "notes": f"fallback plan (planner exception: {e})"}
    agents = out.get("agents") or ["hotel_search", "budget_filter"]
    notes = out.get("notes") or "auto plan"
    return {"status": "ok", "agents": agents, "notes": notes}


def _parse_stay_from_query(q: str) -> Dict[str, Any]:
    """Light parser so execute works with just a query string."""
    def _dates(s):
        m = re.search(r'(\d{1,2})\s*[–-]\s*(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})', s)
        if m:
            d1, d2, mon, yr = m.groups()
            ci = datetime.strptime(f"{d1} {mon} {yr}", "%d %b %Y").strftime("%Y-%m-%d")
            co = datetime.strptime(f"{d2} {mon} {yr}", "%d %b %Y").strftime("%Y-%m-%d")
            return ci, co
        m = re.search(r'(\d{4})-(\d{2})-(\d{2}).*?(\d{4})-(\d{2})-(\d{2})', s)
        if m:
            y1, m1, d1, y2, m2, d2 = m.groups()
            return f"{y1}-{m1}-{d1}", f"{y2}-{m2}-{d2}"
        return None, None

    ci, co = _dates(q or "")
    m_city = re.search(r'\(([A-Z]{3})\)', q or "")
    m_adults = re.search(r'(\d+)\s+adults?', q or "", re.I)
    m_price = re.search(r'under\s*£?\s*(\d+)', q or "", re.I)
    wants_pool = bool(re.search(r'indoor\s+pool', q or "", re.I))
    return {
        "check_in": ci, "check_out": co,
        "city_code": m_city.group(1) if m_city else None,
        "adults": int(m_adults.group(1)) if m_adults else 2,
        "wants_indoor_pool": wants_pool,
        "max_price_gbp": float(m_price.group(1)) if m_price else None,
    }


def _planner_execute_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run planner -> hotel_search -> budget_filter -> (optional) responder, in one call."""
    query = (args or {}).get("query", "") or ""
    stay = (args or {}).get("stay") or _parse_stay_from_query(query)
    if not (stay.get("check_in") and stay.get("check_out") and stay.get("city_code")):
        return {"status":"error","error":"need stay {check_in, check_out, city_code} or a parseable query"}

    # Normalize dates so child lambdas always get YYYY-MM-DD
    stay["check_in"] = _normalize_date(stay.get("check_in"))
    stay["check_out"] = _normalize_date(stay.get("check_out"))

    # ➜ run planner and capture planner_meta
    plan_result  = planner_agent_plan(query) # Use the properly imported function
    planner_meta = plan_result.get("planner_meta", {"used_llm": False})
    agents       = plan_result.get("agents", [])
    notes        = plan_result.get("notes", "")

    # hotel search
    if not HOTEL_FN:
        return {"status":"error","error":"HOTEL_FN env not set"}
    hs = _invoke(HOTEL_FN, {"stay": stay, "task_id": args.get("request_id")})
    hotels = (((hs or {}).get("hotels") or {}).get("hotels")) or []

    # budget filter
    if not BUDGET_FN:
        return {"status":"error","error":"BUDGET_FN env not set"}
    bf_in = {
        "hotels": hotels,
        "max_price_gbp": stay.get("max_price_gbp"),
        "check_in": _normalize_date(stay.get("check_in")),
        "check_out": _normalize_date(stay.get("check_out")),
        "top_n": int(args.get("top_n", 5) or 5),
        "task_id": args.get("request_id"),
    }
    top_n = int(args.get("top_n", 5) or 5)

    bf = _invoke(BUDGET_FN, bf_in) or {}
    candidates = bf.get("candidates") or []                # <- never fallback to raw
    top = (bf.get("top") or bf.get("ranked") or [])[:top_n]

    meta = {
        **(bf.get("meta") or {}),
        "total_in": len(hotels),
        "budget_applied": True,
        "no_under_budget": len(top) == 0,
    }

    print(json.dumps({
       "stage": "mcp.budget_filter.result",
       "task_id": args.get("request_id"),
       "top": len(top),
       "candidates": len(candidates),
       "no_under_budget": len(top) == 0,
    }))
    
    # --- DEBUG: peek the narration prompt (LLM input) without calling the LLM ---
    if (args or {}).get("debug_narration_prompt") is True:
        from agents.responder import narrate
        peek = narrate(
            top=top,
            candidates=candidates,
            context={"stay": stay, "notes": notes, "__debug_build_only": True},
        )
        return {
            "status": "ok",
            "notes": notes,
            "agents": agents,
            "stay": stay,
            "top": top,
            "candidates": candidates,
            "narration_prompt": (peek.get("prompt_text") if isinstance(peek, dict) else None),
            "meta": meta,
            "planner_meta": planner_meta,
        }
    
                
    # responder (optional)
    narrative = None
    try:
        from agents.responder import narrate
        narrative = narrate(top=top, candidates=candidates, context={"stay": stay, "notes": notes})
    except Exception:
        pass

    return {
        "status": "ok",
        "notes": notes,
        "agents": agents,
        "stay": stay,
        "top": top,
        "candidates": candidates,
        "narrative": narrative,
        "meta": meta,
        "planner_meta": planner_meta,  # ➜ include it in the response
    }

def _tools_call(req):
    p = req.get("params", {}) or {}
    name = p.get("name")
    args = p.get("arguments") or {}
    # Use request_id if provided, else fall back to JSON-RPC id
    rid = args.get("request_id") or req.get("id")

    try:   
        if name == "hotel_search":
            if not HOTEL_FN:
                return {"content": [{"type": "text", "text": "HOTEL_FN env not set"}], "isError": True}

            # Normalize: allow both shapes — top-level fields OR inside 'stay'
            stay = dict(args.get("stay") or {})
            for k in ("city_code", "adults", "wants_indoor_pool", "max_price_gbp", "currency"):
                if args.get(k) is not None and stay.get(k) is None:
                    stay[k] = args[k]

            # Normalize dates so downstream lambdas don’t choke on DD/MM/YYYY
            if "check_in" in stay:
                stay["check_in"] = _normalize_date(stay.get("check_in"))
            if "check_out" in stay:
                stay["check_out"] = _normalize_date(stay.get("check_out"))

            # ---- Step 1: Hotel search
            payload = {"stay": stay, "task_id": (args.get("request_id") or req.get("id"))}
            if args.get("currency") is not None:
                payload["currency"] = args["currency"]  # harmless if ignored by Hotel
            print(json.dumps({"stage": "mcp.hotel_search.invoke", "stay_keys": sorted(list(stay.keys())), "task_id": rid}))
            hs = _invoke(HOTEL_FN, payload) or {}
            hotels = (((hs or {}).get("hotels") or {}).get("hotels")) or []

            
            # ---- Step 2: (conditional) budget filter; never leak raw hotels
            top_n = int(args.get("top_n", 5) or 5)
            max_price = stay.get("max_price_gbp")

            if max_price is not None:
                if not BUDGET_FN:
                    return {"content": [{"type": "text", "text": "BUDGET_FN env not set"}], "isError": True}

                bf_in = {
                    "hotels": hotels,
                    "max_price_gbp": max_price,
                    "check_in": stay.get("check_in"),
                    "check_out": stay.get("check_out"),
                    "top_n": top_n,
                    "task_id": rid,
                }

                print(json.dumps({
                "stage": "mcp.budget_filter.invoke",
                "task_id": rid,
                "max_price_gbp": max_price,
                "hotels_in": len(hotels),
                "check_in": stay.get("check_in"),
                "check_out": stay.get("check_out"),
                }))

                bf = _invoke(BUDGET_FN, bf_in) or {}

                # ✅ Enforce budget strictly (no fallback to raw hotels)
                candidates = bf.get("candidates") or []
                top = (bf.get("top") or candidates)[:top_n]
                meta = {
                    **(bf.get("meta") or {}),
                    "total_in": len(hotels),
                    "budget_applied": True,
                    "no_under_budget": len(top) == 0,
                }

                print(json.dumps({
                "stage": "mcp.budget_filter.result",
                "task_id": rid,
                "top": len(top),
                "candidates": len(candidates),
                "no_under_budget": len(top) == 0,
                }))
            else:
                # No budget provided → pass through unchanged
                candidates = hotels
                top = hotels[:top_n]
                meta = {"total_in": len(hotels), "budget_applied": False}


            result = {
                "status": "ok",
                "hotels": {"status": "ok", "hotels": top},
                "meta": {
                    "budget_filter": {"under_budget": len([h for h in candidates if h.get('passes_budget')])},
                    **meta
                },
            }

            
            # ---- Step 3: Optional responder (in-process)
            if INCLUDE_RESPONDER:
                try:
                    from agents.responder import narrate
                    context = {"stay": stay}
                    narration = narrate(top=top, candidates=candidates, context=context)
                    # unify field for GUI
                    result["narrative"] = narration.get("narrative") if isinstance(narration, dict) else (narration or "")
                except Exception as e:
                    result["narrative_error"] = str(e)

            out = result                  

        elif name == "budget_filter":
            if not BUDGET_FN:
                return {"content": [{"type": "text", "text": "BUDGET_FN env not set"}], "isError": True}
            out = _invoke(
                BUDGET_FN,
                {
                    "hotels": args.get("hotels", []),
                    "max_price_gbp": args.get("max_price_gbp"),
                    "check_in": args.get("check_in"),
                    "check_out": args.get("check_out"),
                    "top_n": args.get("top_n", 5),
                    "task_id": rid,
                },
            )
                
        elif name == "responder_narrate":
            try:
                from agents.responder import narrate
                text = narrate(args.get("top", []),
                               args.get("candidates", []),
                               args.get("context", {}))
                if isinstance(text, dict):
                    out = {
                        "status": "ok",
                        "narrative": text.get("narrative") or "",
                        "prompt_text": text.get("prompt_text"),  # <-- pass through for debugging
                    }
                else:
                    out = {"status": "ok", "narrative": text}
            except Exception:
                out = {"status": "ok", "narrative": "Responder not available in this build."}        
        
        
        elif name in ("planner_plan", "plan"):
            out = _planner_handler(args)

        elif name == "planner_execute":
            out = _planner_execute_handler(args)

        else:
            return {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}

        if isinstance(out, dict) and out.get("status") == "error":
            return {"content": [{"type": "text", "text": out.get("error", "agent_error")}], "isError": True}

        blocks = [{"type": "json", "json": out if isinstance(out, dict) else {"data": out}}]
        if rid:
            blocks.append({"type": "text", "text": f"request_id={rid}"})
        return {"content": blocks}

    except Exception as e:
        tb = traceback.format_exc(limit=1)
        return {"content": [{"type": "text", "text": f"error: {e}\n{tb}"}], "isError": True}


HANDLERS = {"initialize": _initialize, "tools/list": _tools_list, "tools/call": _tools_call}


def lambda_handler(event, context):
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method") or event.get("httpMethod")
    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    try:
        body = event.get("body")
        req = json.loads(body) if isinstance(body, str) else (body or {})
        if not isinstance(req, dict):
            return _resp(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})

        fn = HANDLERS.get(req.get("method"))
        if not fn:
            return _resp(400, {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "Method not found"}})

        result = fn(req)
        return _resp(200, {"jsonrpc": "2.0", "id": req.get("id"), "result": result})

    except Exception as e:
        return _resp(
            500,
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32000, "message": str(e), "data": traceback.format_exc()},
            },
        )
