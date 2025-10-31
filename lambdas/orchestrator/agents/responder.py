"""Responder agent: turns structured hotel results into a concise narrative."""
from typing import List, Dict, Any, Optional
from shared.bedrock_responder import LLMResponder as LLM
import json

TEMPLATE = """You are a helpful travel concierge.
Write a concise, friendly summary in 4–6 sentences about the hotel options.
Rules:
- Plain text only (no markdown, no bullet points).
- Do NOT invent prices, links, amenities, or details that aren't in the data.
- If CONTEXT_JSON indicates the user prefers an indoor pool, highlight any matches.
- Use the currency and dates from CONTEXT_JSON if you refer to them.
- If there are no top picks, acknowledge that and summarize the broader candidates.

CONTEXT_JSON:
{context}

TOP_PICKS_JSON:
{top}

CANDIDATES_JSON:
{candidates}
"""

def _compact(obj: Any, max_chars: int = 4000) -> str:
    """Minify JSON and hard-cap length to avoid overly long prompts."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s[:max_chars]

def narrate(
    top: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
) -> Any:  # allow returning dict in debug modes
    top = top or []
    candidates = candidates or []
    context = context or {}

    # If nothing to talk about, return a friendly fallback without calling the LLM.
    if not top and not candidates:
        return ("I couldn’t find suitable hotels yet. Try widening the area, adjusting dates, "
                "or increasing the nightly budget, and I’ll search again.")

    prompt = TEMPLATE.format(
        context=_compact(context, 1500),
        top=_compact(top, 2500),
        candidates=_compact(candidates, 2500),
    )
    
    # --- DEBUG: return prompt without calling the LLM ---
    if context.get("__debug_build_only") is True:
        return {"prompt_text": prompt}

    try:
        # Lower temperature for consistency; 600 tokens is usually plenty for 4–6 sentences.
        out = LLM.generate(prompt, max_tokens=600, temperature=0.15).strip()
        # --- DEBUG: include prompt alongside normal narrative ---
        if context.get("__include_prompt") is True:
            return {"narrative": out, "prompt_text": prompt}
        return out
    
    except Exception:
        # Safe fallback narrative
        if top:
            names = [h.get("name") or "a hotel" for h in top[:3]]
            return ("Top picks include " + ", ".join(names) +
                    ". Each meets your preferences. I can refine the search if you’d like to adjust budget or location.")
        return ("Here are some options that partially match your preferences. "
                "If you specify a tighter neighborhood or adjust the nightly budget, I can refine the list further.")
