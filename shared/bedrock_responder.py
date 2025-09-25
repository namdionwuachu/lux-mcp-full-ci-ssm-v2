"""Bedrock client for the RESPONDER model (reads SSM /lux/models/responder)."""

import os
import json
import boto3
from functools import lru_cache

REGION = os.getenv("AWS_REGION", "us-east-1")
_ssm   = boto3.client("ssm", region_name=REGION)


def _get(name, default):
    try:
        return _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return os.getenv("BEDROCK_MODEL_ID_RESPONDER", default)


MODEL_ID = _get("/lux/models/responder", "anthropic.claude-3-5-sonnet-20240620-v2:0")
client   = boto3.client("bedrock-runtime", region_name=REGION)

# --- Guardrail resolution (env → SSM) -----------------------------------------
@lru_cache(maxsize=1)
def _guardrail_ids():
    """
    Resolve guardrail ID/version in this precedence:
      1) Direct env: GUARDRAIL_ID + GUARDRAIL_VERSION
      2) SSM params named by env: GUARDRAIL_ID_PARAM + GUARDRAIL_VERSION_PARAM
         (defaults to /lux/bedrock/guardrail_id and /lux/bedrock/guardrail_version)
    Returns (id, version) or (None, None).
    """
    gr_id = os.getenv("GUARDRAIL_ID")
    gr_ver = os.getenv("GUARDRAIL_VERSION")
    if gr_id and gr_ver:
        return gr_id, gr_ver

    id_param = os.getenv("GUARDRAIL_ID_PARAM", "/lux/bedrock/guardrail_id")
    ver_param = os.getenv("GUARDRAIL_VERSION_PARAM", "/lux/bedrock/guardrail_version")
    try:
        gr_id = _ssm.get_parameter(Name=id_param)["Parameter"]["Value"]
        gr_ver = _ssm.get_parameter(Name=ver_param)["Parameter"]["Value"]
        if gr_id and gr_ver:
            return gr_id, gr_ver
    except Exception as e:
        print(f"[guardrail] SSM read failed: {e}")
    return None, None



# Consolidated invoke so every call attaches guardrail if configured
def _invoke_with_guardrail(model_id: str, body: dict,
                           content_type="application/json",
                           accept="application/json"):
    kwargs = {
        "modelId": model_id,
        "contentType": content_type,
        "accept": accept,
        "body": json.dumps(body),
    }
    gr = _guardrail_ids()
    if gr and all(gr):
        kwargs["guardrailIdentifier"] = gr[0]   # NEW
        kwargs["guardrailVersion"] = gr[1]      # NEW
    return client.invoke_model(**kwargs)


class LLMResponder:
    @staticmethod
    def generate(prompt: str, max_tokens: int = 800, temperature: float = 0.2) -> str:
        # Anthropic Claude 3/3.5 (Messages API)
        if MODEL_ID.startswith("anthropic."):
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": prompt}]}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            resp = _invoke_with_guardrail(
                model_id=MODEL_ID,
                body=body,
                content_type="application/json",
                accept="application/json",
                
            )
            data = json.loads(resp["body"].read())
            content = data.get("content") or []
            return (content[0] or {}).get("text", "").strip() if content else ""

        # AI21 Jamba (Messages API on Bedrock)
        if MODEL_ID.startswith("ai21.jamba"):
            body = {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": prompt}]}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            resp = _invoke_with_guardrail(
                model_id=MODEL_ID,
                body=body,
                content_type="application/json",
                accept="application/json",
              
            )
            data = json.loads(resp["body"].read())
            content = data.get("content") or []
            return (content[0] or {}).get("text", "").strip() if content else ""

        # Fallback for older prompt-style models
        body = {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
        resp = _invoke_with_guardrail(
            model_id=MODEL_ID,
            body=body,
            content_type="application/json",
            accept="application/json",
            
        )
        data = json.loads(resp["body"].read())
        return (
            data.get("generation")
            or data.get("output_text")
            or data.get("text")
            or json.dumps(data)
        )

