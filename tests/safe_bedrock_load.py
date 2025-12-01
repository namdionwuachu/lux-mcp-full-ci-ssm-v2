#!/usr/bin/env python3
"""
Bedrock Budget-Safe Load Tester
- Caps runtime, calls, tokens, and estimated spend
- Conservative defaults; use CLI flags to adjust
"""

import os, time, json, random, argparse, sys
import concurrent.futures as cf
import boto3
from botocore.exceptions import ClientError

# ---------- Config via env (with safe defaults) ----------
REGION   = os.getenv("REGION", "us-east-1")
MODEL_A  = os.getenv("MODEL_A", "ai21.jamba-1-5-mini-v1:0")  # cheaper default
MODEL_B  = os.getenv("MODEL_B", "ai21.jamba-1-5-mini-v1:0")  # use same if unset
SAFE_BUDGET_USD = float(os.getenv("SAFE_BUDGET_USD", "1.00"))  # hard cap per run

# Approx output $/1K tokens (tune as needed)
PRICE_OUT_PER_1K = [
    # (matcher, price_per_1k_output_tokens_usd)
    ("anthropic.claude-3-5-sonnet", 0.015),
    ("ai21.jamba-1-5-mini",         0.0008),
    ("jamba",                        0.0008),
    ("mistral",                      0.0010),
]
DEFAULT_PRICE_OUT = 0.002  # safe fallback if no match

def price_for_model(model_id: str) -> float:
    mid = model_id.lower()
    for key, price in PRICE_OUT_PER_1K:
        if key in mid:
            return price
    return DEFAULT_PRICE_OUT

# ---------- Safety guard ----------
class Safety:
    def __init__(self, max_runtime_s: int, max_calls: int, est_budget_usd: float,
                 max_tokens_per_call: int):
        self.start = time.time()
        self.max_runtime_s = max_runtime_s
        self.max_calls = max_calls
        self.est_budget_usd = est_budget_usd
        self.max_tokens_per_call = max_tokens_per_call
        self.succ_calls = 0
        self.est_cost_usd = 0.0

    def add_call(self, model_id: str, out_tokens_requested: int):
        # Estimate cost *conservatively* using requested max tokens
        price = price_for_model(model_id)
        self.est_cost_usd += (out_tokens_requested / 1000.0) * price
        self.succ_calls += 1

    def should_stop(self) -> str | None:
        if time.time() - self.start >= self.max_runtime_s:
            return f"Reached max runtime {self.max_runtime_s}s"
        if self.succ_calls >= self.max_calls:
            return f"Reached max successful calls {self.max_calls}"
        if self.est_cost_usd >= self.est_budget_usd:
            return f"Reached budget cap ${self.est_budget_usd:.2f} (est ${self.est_cost_usd:.2f})"
        return None

# ---------- Bedrock client ----------
brt = boto3.client("bedrock-runtime", region_name=REGION)

def converse(model_id, prompt, max_tokens=256, temperature=0.5, retry=3):
    """Polite wrapper with light throttle handling."""
    base = 0.25
    for attempt in range(retry):
        try:
            return brt.converse(
                modelId=model_id,
                messages=[{"role":"user","content":[{"text":prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException","Throttling","TooManyRequestsException"):
                time.sleep(base * (2**attempt) + random.uniform(0, 0.2))
                continue
            raise

# ---------- Phases (budget-safe defaults) ----------
def phase_high_tokens_per_invoke(safety: Safety, models: list[str],
                                 duration_sec=30, workers=2, max_tokens=512):
    """Longer outputs (but capped)."""
    print("Phase: High Tokens/Invoke (safe mode)")
    end = time.time() + duration_sec
    long_prompt = "Write ~300 words about event-driven serverless design. One code block."
    def once(model):
        if (reason := safety.should_stop()):
            return ("stop", reason)
        r = converse(model, long_prompt, max_tokens=max_tokens, temperature=0.3)
        safety.add_call(model, max_tokens)
        return ("ok", len(json.dumps(r)) if r else 0)

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        while time.time() < end:
            if (reason := safety.should_stop()):
                print("Stopping:", reason); return
            futs = [ex.submit(once, m) for m in models]
            for f in cf.as_completed(futs):
                status, info = f.result()
                if status == "stop":
                    print("Stopping:", info); return

def phase_latency_pressure(safety: Safety, models: list[str],
                           duration_sec=45, workers=3, batch=6, max_tokens=256):
    """Large-ish inputs, moderate outputs."""
    print("Phase: Latency Pressure (safe mode)")
    end = time.time() + duration_sec
    base = "Summarize in 5 bullets:\n" + ("lorem ipsum " * 800)
    def once(model):
        if (reason := safety.should_stop()):
            return ("stop", reason)
        r = converse(model, base, max_tokens=max_tokens, temperature=0.2)
        safety.add_call(model, max_tokens)
        return ("ok", "done")

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        while time.time() < end:
            if (reason := safety.should_stop()):
                print("Stopping:", reason); return
            futs = [ex.submit(once, random.choice(models)) for _ in range(batch)]
            for f in cf.as_completed(futs):
                status, info = f.result()
                if status == "stop":
                    print("Stopping:", info); return

def phase_client_errors(safety: Safety, model: str, burst=10):
    """Intentional 4xx — not billed for tokens."""
    print("Phase: Client Errors (safe mode)")
    low = boto3.client("bedrock-runtime", region_name=REGION)
    payload = {"messages":[{"role":"user","content":[{"text":"hi"}]}]}
    for _ in range(burst):
        if (reason := safety.should_stop()):
            print("Stopping:", reason); return
        try:
            low.invoke_model(
                modelId=model,
                body=json.dumps({"max_tokens": 1, **payload}).encode("utf-8"),
                contentType="application/json",
                accept="application/json",
            )
        except Exception:
            print("expected-4xx")

def phase_throttles(safety: Safety, models: list[str],
                    rate_per_sec=8, duration_sec=30, max_tokens=20):
    """Try to elicit some throttles without going wild."""
    print("Phase: Throttles Attempt (safe mode)")
    end = time.time() + duration_sec
    def once(model):
        if (reason := safety.should_stop()):
            return ("stop", reason)
        try:
            converse(model, "Say 'pong' once.", max_tokens=max_tokens, temperature=0)
            safety.add_call(model, max_tokens)
            return ("ok", None)
        except Exception as e:
            if "Throttling" in str(e) or "Rate exceeded" in str(e):
                print("throttle!")
            return ("err", None)

    with cf.ThreadPoolExecutor(max_workers=min(rate_per_sec, 16)) as ex:
        while time.time() < end:
            if (reason := safety.should_stop()):
                print("Stopping:", reason); return
            futs = [ex.submit(once, random.choice(models)) for _ in range(rate_per_sec)]
            for f in cf.as_completed(futs):
                status, info = f.result()
                if status == "stop":
                    print("Stopping:", info); return
            time.sleep(1)

# ---------- CLI ----------
# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser(description="Budget-safe Bedrock load tester")
    parser.add_argument("--max-runtime", type=int, default=120, help="Hard stop in seconds (all phases)")
    parser.add_argument("--max-calls", type=int, default=60, help="Max successful calls across run")
    parser.add_argument("--budget", type=float, default=SAFE_BUDGET_USD, help="Estimated USD budget cap")
    parser.add_argument("--max-tokens", type=int, default=512, help="Max output tokens per call")
    parser.add_argument("--models", nargs="*", default=[MODEL_A, MODEL_B], help="Model IDs to use")
    parser.add_argument("--phases", nargs="*", default=["throttles","client_errors","latency","tokens"],
                        choices=["tokens","latency","client_errors","throttles"],
                        help="Which phases to run (order applied)")
    # new knobs to align with CloudWatch windows
    parser.add_argument("--tokens-duration", type=int, default=360, help="seconds to run tokens phase")
    parser.add_argument("--latency-duration", type=int, default=360, help="seconds to run latency phase")
    parser.add_argument("--throttles-duration", type=int, default=150, help="seconds to run throttles phase")
    parser.add_argument("--throttles-rate", type=int, default=12, help="requests/sec in throttles phase")
    parser.add_argument("--client-errors-burst", type=int, default=10, help="4xx requests to send per minute")
    args = parser.parse_args()

    models = [m for m in args.models if m]
    if not models:
        print("No models configured. Set MODEL_A/MODEL_B or pass --models.", file=sys.stderr)
        sys.exit(2)

    safety = Safety(
        max_runtime_s=args.max_runtime,
        max_calls=args.max_calls,
        est_budget_usd=args.budget,
        max_tokens_per_call=args.max_tokens
    )

    print(f"Region={REGION} | Models={models}")
    print(f"Caps: runtime={args.max_runtime}s, calls={args.max_calls}, "
          f"max_tokens/call={args.max_tokens}, budget=${args.budget:.2f}")

    # Run selected phases in order
    for ph in args.phases:
        stop_reason = safety.should_stop()
        if stop_reason:
            print("Global stop:", stop_reason)
            break

        if ph == "tokens":
            # needs 5 consecutive minutes > threshold
            phase_high_tokens_per_invoke(
                safety, models,
                duration_sec=args.tokens_duration,
                workers=2,
                max_tokens=args.max_tokens
            )

        elif ph == "latency":
            # needs 3 of last 5 minutes breaching
            phase_latency_pressure(
                safety, models,
                duration_sec=args.latency_duration,
                workers=3, batch=6,
                max_tokens=min(256, args.max_tokens)
            )

        elif ph == "client_errors":
            # needs 3 of last 5 minutes with errors; spread bursts
            end = time.time() + 300  # 5 minutes
            while time.time() < end:
                phase_client_errors(safety, models[0], burst=args.client_errors_burst)
                if (reason := safety.should_stop()):
                    print("Stopping:", reason); break
                time.sleep(30)  # spread across periods

        elif ph == "throttles":
            # needs 2 consecutive minutes with throttles > 0
            phase_throttles(
                safety, models,
                rate_per_sec=args.throttles_rate,
                duration_sec=args.throttles_duration,
                max_tokens=min(20, args.max_tokens)
            )

    print(f"\n== Run summary ==")
    print(f"Successful calls: {safety.succ_calls}")
    print(f"Estimated cost:  ${safety.est_cost_usd:.4f} (cap ${safety.est_budget_usd:.2f})")
    print("Done.")


if __name__ == "__main__":
    main()


