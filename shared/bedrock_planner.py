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
        if MODEL_ID.startswith("ai21.jamba"):
            body = {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
            resp = client.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
            data = json.loads(resp["body"].read())
            return data["completions"][0]["data"]["text"].strip()
        body = {"messages":[{"role":"user","content":[{"text":prompt}]}],
                "inferenceConfig":{"temperature":temperature,"maxTokens":max_tokens}}
        resp = client.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
        data = json.loads(resp["body"].read())
        return data.get("outputText") or json.dumps(data)
