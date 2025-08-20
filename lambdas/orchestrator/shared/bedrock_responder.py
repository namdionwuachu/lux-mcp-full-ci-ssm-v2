"""Bedrock client for the RESPONDER model (reads SSM /lux/models/responder)."""
import os, json, boto3

REGION = os.getenv("AWS_REGION", "us-east-1")
_ssm   = boto3.client("ssm", region_name=REGION)

def _get(name, default):
    try:
        return _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return os.getenv("BEDROCK_MODEL_ID_RESPONDER", default)

MODEL_ID = _get("/lux/models/responder", "anthropic.claude-3-5-sonnet-20240620-v2:0")
client   = boto3.client("bedrock-runtime", region_name=REGION)

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
            resp = client.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            data = json.loads(resp["body"].read())
            content = data.get("content") or []
            return (content[0] or {}).get("text", "").strip() if content else ""

        # AI21 Jamba (now also Messages API on Bedrock)
        if MODEL_ID.startswith("ai21.jamba"):
            body = {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": prompt}]}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            resp = client.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            data = json.loads(resp["body"].read())
            content = data.get("content") or []
            return (content[0] or {}).get("text", "").strip() if content else ""

        # Fallback for older prompt-style models
        body = {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
        resp = client.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        data = json.loads(resp["body"].read())
        return data.get("generation") or data.get("output_text") or data.get("text") or json.dumps(data)

