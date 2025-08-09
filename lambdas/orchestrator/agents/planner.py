"""Planner agent using SSM-configured planner model."""
from shared.bedrock_planner import LLMPlanner as LLM
def plan(query: str) -> dict:
    prompt = f"""
You are a planner. Output JSON with:
- agents: ordered list from ["hotel_search","budget_filter"]
- notes: one short line
Request: {query}
JSON:
"""
    raw = LLM.generate(prompt, max_tokens=256)
    import re, json; m=re.search(r"\{[\s\S]*\}", raw)
    return json.loads(m.group(0)) if m else {"agents":["hotel_search","budget_filter"],"notes":"default plan"}
