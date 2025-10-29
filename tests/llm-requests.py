import boto3, time, random
from botocore.config import Config
from botocore.exceptions import ClientError

b = boto3.client("bedrock-runtime", region_name="us-east-1",
                 config=Config(retries={"max_attempts": 2, "mode": "standard"}))

MODELS = ["ai21.jamba-1-5-mini-v1:0", "anthropic.claude-3-5-sonnet-20240620-v1:0"]

def call_with_retry(mid, prompt):
    base = 0.5
    for attempt in range(5):  # up to ~5 retries with backoff+jitter
        try:
            return b.converse(
                modelId=mid,
                messages=[{"role":"user","content":[{"text":prompt}]}],
                inferenceConfig={"maxTokens":128,"temperature":0.5}
            )
        except ClientError as e:
            code = e.response.get("Error",{}).get("Code","")
            if code in ("ThrottlingException","Throttling","TooManyRequestsException"):
                sleep = base * (2 ** attempt) + random.uniform(0, 0.4)  # jitter
                time.sleep(sleep)
            else:
                raise

for _ in range(20):
    mid = random.choice(MODELS)
    call_with_retry(mid, "Say hello from Lux Search")
    time.sleep(0.8 + random.uniform(0, 0.5))  # pace requests
