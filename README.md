# Lux Search — MCP (Planner + Responder) on AWS (SSM + Secrets + CI/CD)

This repo implements a serverless multi-agent “Lux Search” concierge:
- **Orchestrator (MCP)** with **Planner** (fast) and optional **Responder** (polished).
- **Hotel Agent** using **Amadeus** (sandbox) with **AWS Secrets Manager**.
- **Budget Agent** with simple ranking (per-night budget + indoor-pool bonus).
- **Infrastructure** via CDK (API Gateway + Lambdas + S3 + CloudFront).
- **SSM Parameter Store** for model IDs (switch models without redeploy).
- **GitHub Actions** workflow for automatic deploys.

## Required AWS parameters/secrets (you already created these)
- **Amadeus credentials (Secrets Manager):** `/lux/amadeus/credentials` with JSON:
  `{"client_id":"<YOUR_CLIENT_ID>","client_secret":"<YOUR_CLIENT_SECRET>"}`
- **Planner model (SSM):** `/lux/models/planner` (e.g., `ai21.jamba-instruct-v1:0`)
- **Responder model (SSM):** `/lux/models/responder` (e.g., `anthropic.claude-3-5-sonnet-20240620-v2:0`)

## Deploy (local)
```bash
npm i -g aws-cdk@2
cd cdk
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-east-1
cdk deploy LuxStack --require-approval never
cdk deploy LuxFrontendStack --require-approval never
```
Outputs:
- `LuxStack.ApiUrl` (API Gateway URL)
- `LuxFrontendStack.FrontendDomain` (CloudFront domain)

## Frontend (quick test)
Edit `frontend/index.html` → set `API_URL` to your API URL and open in a browser.

## SPA (hosted on CloudFront)
```bash
cd frontend
npm install
echo VITE_LUX_API=https://<api-id>.execute-api.us-east-1.amazonaws.com > .env
npm run build
aws s3 sync dist s3://$(aws cloudformation describe-stacks --stack-name LuxFrontendStack --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" --output text) --delete
aws cloudfront create-invalidation --distribution-id $(aws cloudformation describe-stacks --stack-name LuxFrontendStack --query "Stacks[0].Outputs[?OutputKey=='FrontendDistributionId'].OutputValue" --output text) --paths "/*"
```

## CI/CD (optional)
Add repo **Actions secrets**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Push to `main` to auto-deploy both stacks and publish the SPA (workflow writes `.env` with API URL).

## Phase 2: Optional Web Scraping (OFF by default)
- Env knobs (already wired):
  - `HOTEL_PROVIDER_ORDER=amadeus` (default)
  - `ALLOWLIST_DOMAINS=` (empty → scraper disabled)
- Later, add a `provider_scrape.py` and set `HOTEL_PROVIDER_ORDER=amadeus,scrape` with an allow-list.

## Test request (Responder ON)
`tests/request.json` sets `"use_responder": true`.

---

## 📊 Bedrock LLM Observability

Monitor your Amazon Bedrock Large Language Models (LLMs) in real time with latency, error, and throughput dashboards.
[![Observability Runbook](https://img.shields.io/badge/Runbook-LLM%20Observability-blue?style=flat-square&logo=amazonaws)](docs/runbooks/bedrock-llm-observability.md)
[![CloudWatch Slack Integration Runbook](https://img.shields.io/badge/Runbook-CloudWatch%20Slack%20Integration-green?style=flat-square&logo=amazonaws)](docs/runbooks/CloudWatchSlackIntegration.md)
[![AWS CloudWatch Dashboard](https://img.shields.io/badge/Dashboard-CloudWatch-orange?style=flat-square&logo=amazoncloudwatch)](https://console.aws.amazon.com/cloudwatch/home?#dashboards:)

**Included in this runbook:**
- CloudFormation template for LLM observability  
- SNS-based alerting (latency, error, throttles)
- CloudWatch Slack Integration  
- Log Insights queries for runtime tracing  
- Python load & burst scripts for performance testing  
- Multi-model p95 latency comparison widgets  

> 📘 Run the observability setup in under 10 minutes — fully compatible with Lux Search AI Travel Assistant & CloudAINexus360 deployments.
