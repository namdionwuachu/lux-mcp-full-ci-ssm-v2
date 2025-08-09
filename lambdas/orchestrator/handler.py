"""API entry: plan -> hotel_search -> budget_filter; optional responder narrative; CORS on."""
import json
from lambdas.orchestrator.mcp import MCP
from lambdas.orchestrator.agents import planner
from lambdas.orchestrator.agents.responder import narrate
from lambdas.hotel_agent.agent import run as hotel_run
from lambdas.budget_agent.agent import run as budget_run
mcp=MCP(); mcp.register("hotel_search", lambda t: hotel_run(t)); mcp.register("budget_filter", lambda t: budget_run(t))
def _resp(code,obj,cors=True):
    h={"content-type":"application/json"}; 
    if cors: h.update({"Access-Control-Allow-Origin":"*","Access-Control-Allow-Headers":"*","Access-Control-Allow-Methods":"POST,OPTIONS"})
    return {"statusCode":code,"headers":h,"body":json.dumps(obj)}
def lambda_handler(event, context):
    if event.get("requestContext",{}).get("http",{}).get("method")=="OPTIONS": return _resp(200,{"ok":True})
    body=json.loads(event.get("body") or "{}"); query=body.get("query"); stay=body.get("stay")
    if not stay: return _resp(400,{"error":"missing stay"})
    plan=planner.plan(query or "Find a 4-star in Marais with gym, prefer indoor pool")
    r1=mcp.route({"agent":"hotel_search","stay":stay})
    r2=mcp.route({"agent":"budget_filter","hotels":r1.get("hotels",[]),"max_price_gbp":stay.get("max_price_gbp"),"check_in":stay["check_in"],"check_out":stay["check_out"]})
    result={"plan":plan,"candidates":r1.get("hotels",[]),"top":r2.get("ranked",[])}
    if body.get("use_responder"): result["narrative"]=narrate(result["top"], result["candidates"])
    return _resp(200,result)
