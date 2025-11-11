import os, time, json, random
import concurrent.futures as cf
import boto3

REGION  = os.getenv("REGION", "us-east-1")
MODEL_A = os.getenv("MODEL_A")
MODEL_B = os.getenv("MODEL_B")
brt = boto3.client("bedrock-runtime", region_name=REGION)

def converse(model_id, prompt, max_tokens=1024, temperature=0.7):
    return brt.converse(
        modelId=model_id,
        messages=[{"role":"user","content":[{"text":prompt}]}],
        inferenceConfig={"maxTokens":max_tokens,"temperature":temperature}
    )

# ---- Phase helpers ----

def phase_high_tokens_per_invoke(duration_sec=180):
    """Drives Tokens/Invoke alarm: long outputs + big inputs."""
    print("Phase: High Tokens/Invoke")
    end = time.time() + duration_sec
    long_prompt = "Write a detailed 2000-word tutorial on event-driven serverless design. Include code blocks and diagrams in ASCII."
    def once(model):
        r = converse(model, long_prompt, max_tokens=4096, temperature=0.3)
        return len(json.dumps(r))
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        while time.time() < end:
            futs = [ex.submit(once, m) for m in (MODEL_A, MODEL_B)]
            for f in cf.as_completed(futs): print("bytes:", f.result())

def phase_latency_pressure(duration_sec=300):
    """Increases p95 latency: bigger payloads repeatedly."""
    print("Phase: Latency Pressure")
    end = time.time() + duration_sec
    base = "Summarize this text in 10 bullets:\n" + ("lorem ipsum " * 3000)
    def once(model):
        r = converse(model, base, max_tokens=1024, temperature=0.2)
        return "ok"
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        while time.time() < end:
            futs = [ex.submit(once, random.choice([MODEL_A, MODEL_B])) for _ in range(12)]
            for f in cf.as_completed(futs): f.result()

def phase_client_errors(burst=50):
    """Triggers client error % by sending invalid params."""
    print("Phase: Client Errors")
    # Send a bogus parameter via raw invoke to elicit 4xx
    low = boto3.client("bedrock-runtime", region_name=REGION)
    payload = {"messages":[{"role":"user","content":[{"text":"hi"}]}]}
    for _ in range(burst):
        try:
            # invalid field name 'max_tokens' (should be maxTokens in converse)
            low.invoke_model(
                modelId=MODEL_A,
                body=json.dumps({"max_tokens": 1, **payload}).encode("utf-8"),
                contentType="application/json",
                accept="application/json",
            )
        except Exception as e:
            print("expected-4xx")

def phase_throttles(rate_per_sec=20, duration_sec=120):
    """Attempts to exceed TPS to create throttles."""
    print("Phase: Throttles Attempt")
    end = time.time() + duration_sec
    def once(model):
        try:
            converse(model, "Say 'pong' once.", max_tokens=20, temperature=0)
            return "ok"
        except Exception as e:
            if "Throttling" in str(e) or "Rate exceeded" in str(e):
                print("throttle!")
            return "err"
    with cf.ThreadPoolExecutor(max_workers=64) as ex:
        while time.time() < end:
            futs = [ex.submit(once, random.choice([MODEL_A, MODEL_B])) for _ in range(rate_per_sec)]
            for f in cf.as_completed(futs): f.result()
            time.sleep(1)

if __name__ == "__main__":
    # Toggle phases as needed:
    phase_high_tokens_per_invoke(duration_sec=180)  # expect Tokens/Invoke alarm
    phase_latency_pressure(duration_sec=300)        # expect p95 latency alarm (if threshold 1500ms)
    phase_client_errors(burst=80)                   # expect Error% alarm
    phase_throttles(rate_per_sec=40, duration_sec=180)  # may elicit throttles depending on quotas
