import boto3, time, random, queue, threading
from botocore.config import Config
from botocore.exceptions import ClientError

b = boto3.client("bedrock-runtime", region_name="us-east-1",
                 config=Config(retries={"max_attempts": 2, "mode": "standard"}))
MODELS = ["ai21.jamba-1-5-mini-v1:0","anthropic.claude-3-5-sonnet-20240620-v1:0"]

def worker(q):
    while True:
        try: i = q.get_nowait()
        except queue.Empty: return
        mid = random.choice(MODELS)
        try:
            # simple retry-on-throttle with jitter
            base=0.4
            for attempt in range(5):
                try:
                    b.converse(
                        modelId=mid,
                        messages=[{"role":"user","content":[{"text":f"Req {i} from Lux Search"}]}],
                        inferenceConfig={"maxTokens":128,"temperature":0.5}
                    ); break
                except ClientError as e:
                    if e.response.get("Error",{}).get("Code","") in ("ThrottlingException","Throttling","TooManyRequestsException"):
                        time.sleep(base*(2**attempt)+random.uniform(0,0.3))
                    else:
                        raise
        finally:
            time.sleep(0.4 + random.uniform(0, 0.4))  # pace per worker
            q.task_done()

q = queue.Queue()
for i in range(40): q.put(i)
threads = [threading.Thread(target=worker, args=(q,)) for _ in range(3)]  # <= 3 concurrent
[t.start() for t in threads]
q.join()
