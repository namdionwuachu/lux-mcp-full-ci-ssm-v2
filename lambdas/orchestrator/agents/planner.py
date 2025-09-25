"""Planner agent using SSM-configured planner model (hardened + safe fallback)."""

from typing import Dict, Any, List, Tuple, Optional
from shared.bedrock_planner import LLMPlanner as LLM
import json, re, os
import time
from datetime import datetime, timezone
from shared.bedrock_planner import MODEL_ID

# Allow a 3-step pipeline if desired (via env)
INCLUDE_RESPONDER = os.getenv("INCLUDE_RESPONDER", "false").lower() in ("1", "true", "yes")

ALLOWED_AGENTS = ["hotel_search", "budget_filter", "responder_narrate"]
REQUIRED_ORDER = ["hotel_search", "budget_filter"]  # hotel search must come before filtering
DEFAULT_AGENTS = ["hotel_search", "budget_filter"] + (["responder_narrate"] if INCLUDE_RESPONDER else [])
DEFAULT_PLAN = {"agents": DEFAULT_AGENTS, "notes": "default plan"}

DATE_PATTERNS = [
    r'(\d{1,2})\s*[–-]\s*(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})',         # 12–15 Sep 2025
    r'(\d{4})-(\d{2})-(\d{2})\s*(?:to|–|-|—)\s*(\d{4})-(\d{2})-(\d{2})'  # 2025-09-12 to 2025-09-15
]

PROMPT_TMPL = """You are a planner.
Return ONLY valid, minified JSON matching this schema:
{{"agents":["hotel_search","budget_filter"{maybe_resp}],"notes":"one short line"}}
Rules:
- No markdown or prose, JSON only.
- "hotel_search" must come before "budget_filter".
- If unsure, return {default_json}.

Request: {query}
JSON:
"""

def _parse_dates(q: str) -> Tuple[Optional[str], Optional[str]]:
    for pat in DATE_PATTERNS:
        m = re.search(pat, q)
        if not m:
            continue
        g = m.groups()
        try:
            if len(g) == 4:
                d1, d2, mon, yr = g
                ci = datetime.strptime(f"{d1} {mon} {yr}", "%d %b %Y").strftime("%Y-%m-%d")
                co = datetime.strptime(f"{d2} {mon} {yr}", "%d %b %Y").strftime("%Y-%m-%d")
                return ci, co
            if len(g) == 6:
                y1, m1, d1, y2, m2, d2 = g
                return f"{y1}-{m1}-{d1}", f"{y2}-{m2}-{d2}"
        except Exception:
            continue
    return None, None

def _parse_query_bits(q: str) -> Dict[str, Any]:
    ci, co = _parse_dates(q)
    m_city = re.search(r'\(([A-Z]{3})\)', q) or re.search(r'\b([A-Z]{3})\b', q)
    city_code = m_city.group(1) if m_city and "(" in m_city.group(0) else (m_city.group(1) if m_city else None)
    m_adults = re.search(r'(\d+)\s+adults?', q, flags=re.I)
    m_price  = re.search(r'under\s*£?\s*(\d+)', q, flags=re.I)
    wants_pool = bool(re.search(r'indoor\s+pool', q, flags=re.I))

    return {
        "check_in": ci,
        "check_out": co,
        "city_code": city_code,
        "adults": int(m_adults.group(1)) if m_adults else 2,
        "wants_indoor_pool": wants_pool,
        "max_price_gbp": float(m_price.group(1)) if m_price else None,
    }

def _build_notes(bits: Dict[str, Any]) -> str:
    parts = []
    if bits.get("city_code"):
        parts.append(bits["city_code"])
    if bits.get("check_in") and bits.get("check_out"):
        parts.append(f'{bits["check_in"]}→{bits["check_out"]}')
    if bits.get("max_price_gbp") is not None:
        parts.append(f'£{int(bits["max_price_gbp"])}/night')
    if bits.get("wants_indoor_pool"):
        parts.append("indoor pool")
    if bits.get("adults"):
        parts.append(f'{bits["adults"]} adults')
    return ", ".join(parts) or "auto plan"

def _extract_first_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end+1])
    except Exception:
        return None
    
    
def _truncate(s: str, n: int = 2000) -> str:
    return s if len(s) <= n else s[:n] + f"... [truncated {len(s)-n} chars]"


def _sanitize(plan: Dict[str, Any]) -> Dict[str, Any]:
    agents = plan.get("agents", [])
    if not isinstance(agents, list):
        agents = []

    # keep only allowed + dedupe while preserving order
    seen = set()
    agents = [a for a in agents if a in ALLOWED_AGENTS and (a not in seen and not seen.add(a))]

    # ensure required order presence
    for req in REQUIRED_ORDER:
        if req not in agents:
            agents.insert(0 if req == "hotel_search" else len(agents), req)

    # enforce ordering: hotel_search first, budget_filter after it
    ordered: List[str] = []
    for req in REQUIRED_ORDER:
        if req in agents and req not in ordered:
            ordered.append(req)
    for a in agents:
        if a not in ordered:
            ordered.append(a)

    # optionally include responder
    if INCLUDE_RESPONDER and "responder_narrate" not in ordered:
        ordered.append("responder_narrate")

    notes = plan.get("notes") if isinstance(plan.get("notes"), str) else "auto plan"
    return {"agents": ordered, "notes": notes}

def plan(query: str) -> Dict[str, Any]:
    """Return a safe plan dict: {"agents":[...], "notes": "..."}"""
    q = (query or "").strip()
    bits = _parse_query_bits(q)
    notes_from_bits = _build_notes(bits)

    maybe_resp = ',"responder_narrate"' if INCLUDE_RESPONDER else ""
    prompt = PROMPT_TMPL.format(
        default_json=json.dumps(DEFAULT_PLAN, separators=(",", ":")),
        query=q,
        maybe_resp=maybe_resp,
    )

    # Telemetry: request
    print(json.dumps({
        "stage": "planner.llm_call",
        "model": MODEL_ID,
        "query": q,
        "prompt": prompt,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }))

    used_llm = False
    raw = ""
    t0 = time.perf_counter()
    try:
        raw = LLM.generate(prompt, max_tokens=256, temperature=0.0)  # deterministic
        used_llm = True
        # Telemetry: response
        print(json.dumps({
            "stage": "planner.llm_response",
            "model": MODEL_ID,
            "raw": raw,
            "response_length": len(raw or ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }))
    except Exception as e:
        # Telemetry: error
        print(json.dumps({
            "stage": "planner.llm_error",
            "model": MODEL_ID,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }))

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    obj = _extract_first_json(raw) if raw else None

    # Telemetry: JSON extraction
    print(json.dumps({
        "stage": "planner.json_extraction",
        "extracted_json": obj,
        "extraction_successful": obj is not None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }))

    if obj is None:
        return {
            "agents": DEFAULT_AGENTS,
            "notes": notes_from_bits or DEFAULT_PLAN["notes"],
            "planner_meta": {
                "used_llm": False,
                "model": MODEL_ID,
                "model_provider": "bedrock",
                "fallback_reason": "no_valid_json",
                "temperature": 0.0,
                "max_tokens": 256,
                "processing_time_ms": elapsed_ms,
            }
        }

    try:
        sanitized = _sanitize(obj)
        if sanitized.get("notes") in (None, "", "auto plan"):
            sanitized["notes"] = notes_from_bits or "auto plan"
        return {
            "agents": sanitized["agents"],
            "notes": sanitized["notes"],
            "planner_meta": {
                "used_llm": used_llm,
                "model": MODEL_ID,
                "model_provider": "bedrock",
                "prompt_sent": prompt,
                "raw_response": raw,
                "extracted_json": obj,
                "temperature": 0.0,
                "max_tokens": 256,
                "processing_time_ms": elapsed_ms,
            }
        }
    except Exception as e:
        print(json.dumps({
            "stage": "planner.sanitize_error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }))
        return {
            "agents": DEFAULT_AGENTS,
            "notes": notes_from_bits or DEFAULT_PLAN["notes"],
            "planner_meta": {
                "used_llm": False,
                "model": MODEL_ID,
                "model_provider": "bedrock",
                "prompt_sent": prompt,
                "raw_response": raw,
                "extracted_json": obj,
                "temperature": 0.0,
                "max_tokens": 256,
                "processing_time_ms": elapsed_ms,
            }
        }
