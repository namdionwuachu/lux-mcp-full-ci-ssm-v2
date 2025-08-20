"""Bedrock client for the PLANNER model (reads SSM /lux/models/planner)."""
import os, json, boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
_ssm   = boto3.client("ssm", region_name=REGION)

def _get(name, default):
    try:
        return _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return os.getenv("BEDROCK_MODEL_ID_PLANNER", default)

MODEL_ID = _get("/lux/models/planner", "ai21.jamba-instruct-v1:0")
client   = boto3.client("bedrock-runtime", region_name=REGION)

class LLMPlanner:
    @staticmethod
    def generate(prompt: str, max_tokens: int = 512, temperature: float = 0.2) -> str:
        # Debug so you can confirm which code/model is live
        print(f"[planner] MODEL_ID={MODEL_ID} FILE={__file__}")

        # Anthropic Claude 3/3.5 → Messages API
        if MODEL_ID.startswith("anthropic."):
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": prompt}]}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            print("[planner] sending keys:", list(body.keys()))
            resp = client.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            data = json.loads(resp["body"].read())
            content = data.get("content") or []
            return (content[0] or {}).get("text", "").strip() if content else ""

        # AI21 Jamba on Bedrock → Messages API (NOT prompt)
        elif MODEL_ID.startswith("ai21.jamba"):
            body = {
                "messages": [
                    {"role": "user", "content": prompt}  # Jamba accepts string content
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            print("[planner] sending keys:", list(body.keys()))
            resp = client.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            data = json.loads(resp["body"].read())
            # Prefer provider’s direct text fields; fall back gracefully
            if "output_text" in data:
                return (data["output_text"] or "").strip()
            content = data.get("content") or []
            if content:
                return (content[0] or {}).get("text", "").strip()
            completions = data.get("completions")
            if completions:
                try:
                    return completions[0]["data"]["text"].strip()
                except Exception:
                    pass
            return (
                data.get("generation")
                or data.get("text")
                or json.dumps(data)
            )

        # Fallback for legacy prompt-style models (Llama/Mistral/etc.)
        else:
            body = {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
            print("[planner] sending keys:", list(body.keys()))
            resp = client.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            data = json.loads(resp["body"].read())
            return (
                data.get("generation")
                or data.get("output_text")
                or data.get("text")
                or json.dumps(data)
            )

