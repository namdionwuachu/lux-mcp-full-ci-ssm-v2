"""Responder agent: turns structured hotel results into concise narrative."""
from shared.bedrock_responder import LLMResponder as LLM
import json
TEMPLATE = """
Act as a helpful travel concierge. Given "top picks" and "candidates",
write a concise, friendly summary (4–6 sentences). Do not invent prices.
Prefer hotels with indoor pool if present.

TOP_PICKS_JSON:
{top}

CANDIDATES_JSON:
{candidates}
"""
def narrate(top, candidates):
    prompt = TEMPLATE.format(top=json.dumps(top, ensure_ascii=False), candidates=json.dumps(candidates, ensure_ascii=False))
    return LLM.generate(prompt, max_tokens=600, temperature=0.2)
