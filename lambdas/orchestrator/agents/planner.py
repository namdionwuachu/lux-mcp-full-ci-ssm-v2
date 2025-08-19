"""Planner agent using SSM-configured planner model (hardened)."""
from typing import List, Dict, Any
from shared.bedrock_planner import LLMPlanner as LLM
import json, re

ALLOWED_AGENTS = ["hotel_search", "budget_filter"]
DEFAULT_PLAN = {"agents": ["hotel_search", "budget_filter"], "notes": "default plan"}

PROMPT_TMPL = """You are a planner.
Return ONLY valid, minified JSON matching this schema:
{{
  "agents": ["hotel_search","budget_filter"],  // ordered list; hotel_search must come before budget_filter
  "notes": "one short line"
}}
Rules:
- No markdown or prose, JSON only.
- If unsure, return {default_json}.

Request: {query}
JSON:
"""

def _sanitize(plan: Dict[str, Any]) -> Dict[str, Any]:
    agents = plan.get("agents", [])
    if not isinstance(agents, list):
        agents = []
    # Keep only allowed, preserve order, dedupe
    seen = set()
    agents = [a for a in agents if a in ALLOWED_AGENTS and (a not in seen and not seen.add(a))]
    # Ensure required order (hotel_search first if present)
    if "hotel_search" in agents:
        agents = ["hotel_search"] + [a for a in agents if a != "hotel_search"]
    # Ensure budget_filter appears (it’s required for your flow)
    if "budget_filter" not in agents:
        agents.append("budget_filter")
    notes = plan.get("notes") if isinstance(plan.get("notes"), str) else "auto plan"
    return {"agents": agents or DEFAULT_PLAN["agents"], "notes": notes}

def plan(query: str) -> Dict[str, Any]:
    prompt = PROMPT_TMPL.format(query=query or "", default_json=json.dumps(DEFAULT_PLAN, separators=(",", ":")))
    raw = LLM.generate(prompt, max_tokens=256, temperature=0.0)  # deterministic

    # Extract first JSON object
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return DEFAULT_PLAN

    try:
        candidate = json.loads(m.group(0))
        return _sanitize(candidate)
    except Exception:
        return DEFAULT_PLAN

