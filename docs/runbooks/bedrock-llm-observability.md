# 🧭 Runbook: Amazon Bedrock LLM Observability & Performance Testing  
_CloudAINexus360 / Lux Search AI Travel Assistant Series_

---

## 📘 Objective
Implement full observability for Amazon Bedrock-hosted Large Language Models (LLMs) to monitor:

- ✅ Latency (p50 / p95 / p99)
- ✅ Throughput (invocations, tokens)
- ✅ Errors & throttles
- ✅ Multi-model comparison
- ✅ Real-time alerting & visualization

---

## ⚙️ Prerequisites

| Requirement | Description |
|--------------|--------------|
| IAM privileges | CloudFormation, CloudWatch, SNS, Bedrock |
| AWS CLI configured | `aws configure` with region + credentials |
| Python 3.8+ with `boto3` | For test scripts |
| Bedrock access | Target models must be **enabled** |
| Example region | `us-east-1` (adjust for your deployment) |

---

## 🧩 1. Deploy the Observability Stack

### 🔹 Template
Save locally as:  
`bedrock-llm-observability-2models.yaml`

This CloudFormation template:
- Creates a CloudWatch dashboard and metrics for two models  
- Sets up alarms (latency, error rate, throttles)  
- Optionally configures an SNS topic for email alerts  

### 🔹 Deploy
```bash
STACK="bedrock-obs-2models"
REGION="us-east-1"

aws cloudformation deploy \
  --region $REGION \
  --stack-name $STACK \
  --template-file bedrock-llm-observability-2models.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ModelIdA="ai21.jamba-1-5-mini-v1:0" \
    ModelIdB="anthropic.claude-3-5-sonnet-20240620-v1:0" \
    DashboardName="bedrock-llm-observability" \
    CreateSNSTopic=true \
    SNSEmail="you@example.com" \
    AlarmLatencyP95Ms=200 \
    AlarmErrorRatePct=0.5
Outcome
Dashboard created → bedrock-llm-observability
Alarms active (3 per model)
SNS topic subscription email sent

📊 2. Enable Bedrock Invocation Logging
CloudFormation doesn’t yet manage Bedrock logging. Enable manually:
REGION="us-east-1"
STACK="bedrock-obs-2models"
LOG_GROUP="/aws/bedrock/model-invocations"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_NAME=$(aws cloudformation list-stack-resources \
  --stack-name "$STACK" --region "$REGION" \
  --query "StackResourceSummaries[?ResourceType=='AWS::IAM::Role'].[PhysicalResourceId]" \
  --output text)
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

aws bedrock put-model-invocation-logging-configuration \
  --region "$REGION" \
  --logging-config "{
    \"cloudWatchConfig\": {\"logGroupName\": \"${LOG_GROUP}\", \"roleArn\": \"${ROLE_ARN}\"},
    \"textDataDeliveryEnabled\": true
  }"
Outcome:
Invocation logs appear under /aws/bedrock/model-invocations.

🧠 3. Verify Dashboard Metrics
Path: CloudWatch → Dashboards → bedrock-llm-observability
You’ll see:

Latency per model (p50/p95/p99)
Multi-model p95 comparison
Error & Throttle rates
Error % metric (use fixed expression)
Log group summary

🧪 4. Generate Load for Testing
🟢 Gentle Load (populate graphs)
import boto3, time, random
b = boto3.client("bedrock-runtime", region_name="us-east-1")
models = ["ai21.jamba-1-5-mini-v1:0","anthropic.claude-3-5-sonnet-20240620-v1:0"]
for _ in range(20):
    mid = random.choice(models)
    b.converse(
        modelId=mid,
        messages=[{"role":"user","content":[{"text":"Say hello from Lux Search"}]}],
        inferenceConfig={"maxTokens":128,"temperature":0.5}
    )
    time.sleep(1.2)
🔴 Controlled Burst (trigger alarms)
import boto3, time, random, threading, queue
from botocore.exceptions import ClientError

b = boto3.client("bedrock-runtime", region_name="us-east-1")
models = ["ai21.jamba-1-5-mini-v1:0","anthropic.claude-3-5-sonnet-20240620-v1:0"]

def worker(q):
    while not q.empty():
        mid = q.get()
        try:
            b.converse(
                modelId=mid,
                messages=[{"role":"user","content":[{"text":"Simulate high load"}]}],
                inferenceConfig={"maxTokens":128,"temperature":0.7}
            )
        except ClientError as e:
            print(f"{mid} ERROR: {e}")
        time.sleep(0.3)
        q.task_done()

q = queue.Queue()
for i in range(40): q.put(random.choice(models))
threads = [threading.Thread(target=worker, args=(q,)) for _ in range(3)]
[t.start() for t in threads]
q.join()

🕵️ 5. Inspect Logs (CloudWatch Logs Insights)
📈 Model usage summary
fields @timestamp, modelId
| stats count() as invocations, max(@timestamp) as last_invoked_at by modelId
| sort last_invoked_at desc
📋 Detailed invocations
fields @timestamp, modelId, latencyMs, inputTokenCount, outputTokenCount, requestId
| sort @timestamp desc
| limit 50
⏱ Trend over time
fields @timestamp, modelId
| stats count() as invokes by bin(1m), modelId
| sort bin(1m) desc

🔔 6. Validate Alarms
Path: CloudWatch → Alarms → All alarms
Expected alarms:

HighLatency-P95-*
ErrorRate-*
Throttles-*
Each will turn:
🟢 OK – Normal
🔴 ALARM – Threshold exceeded
Email notifications arrive via SNS when state changes.

🧰 7. Cleanup (optional)
aws cloudformation delete-stack \
  --stack-name bedrock-obs-2models \
  --region us-east-1

📈 8. Performance Evaluation Checklist
Metric	Description	Target
InvocationLatency p95	95th percentile latency	< 1000 ms
InvocationThrottles	Rate limiting	0
ErrorRate %	Client / server errors	< 2 %
Invocations	Request volume	As expected
Tokens per call	Efficiency & cost	Within budget

💡 9. Optional Enhancements
Add Tokens / Invocation & Invocations / Minute widgets
Export metrics to QuickSight for trend analysis
Enable X-Ray tracing in Lambda for model-level spans
Use CloudWatch Synthetics Canaries to monitor LLM endpoints automatically

✅ Summary
Step	Purpose	Output
1	Deploy template	Dashboard + alarms
2	Enable logging	Log group active
3	Verify dashboard	Visual metrics
4	Run load tests	Live data
5	Inspect logs	Invocation proof
6	Validate alerts	SNS email OK
7	Cleanup	Stack removed
8	Evaluate	Performance baselines
9	Enhance	Advanced observability

📎 Reference
CloudWatch Metrics: AWS/Bedrock namespace
Log Group: /aws/bedrock/model-invocations
Dashboard: bedrock-llm-observability
Source: AWS Bedrock Docs

Authored by CloudAINexus360 / Lux Search Engineering — 2025

---

Would you like me to generate a small **`README.md` badge and link block** (e.g. “📊 View LLM Observability Runbook”) so you can include this in your main GitHub repository homepage?
