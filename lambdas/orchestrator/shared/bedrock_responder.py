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
        body = {"messages":[{"role":"user","content":[{"text":prompt}]}],
                "inferenceConfig":{"temperature":temperature,"maxTokens":max_tokens}}
        resp = client.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
        data = json.loads(resp["body"].read())
        return data.get("outputText") or json.dumps(data)
