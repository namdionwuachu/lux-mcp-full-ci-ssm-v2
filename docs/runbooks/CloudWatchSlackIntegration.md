# CloudWatch → Slack Integration

This guide explains how to integrate a **CloudWatch → SNS → Slack** alerting pipeline, either **alongside** or **instead of** email notifications.

---

## 🧭 1. How the Current Setup Works

Your current CloudFormation stack connects CloudWatch alarms to an SNS topic, which then delivers email notifications.

**Flow:**
CloudWatch Alarm → SNS Topic → Email

The email subscription (`SNSEmail`) is optional and is triggered only if you specify an address.

---

## 💬 2. Slack Integration Overview

Slack cannot subscribe directly to SNS, but there are two recommended integration methods:

### **Option A — AWS Chatbot (Recommended)**

AWS Chatbot provides a native, no-code integration for Slack and Microsoft Teams.

**Flow:**
CloudWatch Alarm → SNS Topic → AWS Chatbot → Slack Channel

**Steps:**
1. Go to the [AWS Chatbot Console](https://console.aws.amazon.com/chatbot/home#/).
2. Under **Slack workspaces**, click **Configure new client**, connect your Slack workspace, and authorize AWS Chatbot.
3. Create a **Slack channel configuration**:
   - Give it a name (e.g., `bedrock-alerts`).
   - Choose the same region and SNS topic used by your CloudWatch alarms.
   - Select your Slack channel (e.g., `#bedrock-observability`).
4. Save the configuration.

Once configured, CloudWatch alarm notifications will appear directly in your Slack channel — no template or stack change required.

**✅ Pros**
- No Lambda or webhook maintenance  
- Structured CloudWatch alarm details shown directly in Slack  
- Supports multiple workspaces or channels  

---

### **Option B — SNS → Lambda → Slack Webhook (Custom)**

If you prefer full control or want to customize alert formatting, deploy a small Lambda function that posts messages to a Slack **Incoming Webhook**.

**Flow:**
CloudWatch Alarm → SNS → Lambda (→ Slack Webhook URL)

**Example Lambda Function (Python):**
```python
import json, os, urllib.request

def lambda_handler(event, context):
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    message = json.loads(event["Records"][0]["Sns"]["Message"])
    text = f"🚨 *{message['AlarmName']}* is in state *{message['NewStateValue']}*\nReason: {message['NewStateReason']}"
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(webhook_url, data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    return {"statusCode": 200}
Attach this Lambda function as an additional subscription to your existing SNS topic.
✅ Pros
Full control over message format
Add colors, emojis, or buttons
Easily extendable to other systems

⚙️ 3. Optional CloudFormation Additions
If using AWS Chatbot, no stack modification is needed — reuse your existing SNS topic.
If using the Lambda webhook method, you can extend your CloudFormation template with the following resources:
SlackNotifier:
  Type: AWS::Lambda::Function
  Properties:
    ...
    Environment:
      Variables:
        SLACK_WEBHOOK_URL: https://hooks.slack.com/services/...
SlackSubscription:
  Type: AWS::SNS::Subscription
  Properties:
    Protocol: lambda
    Endpoint: !GetAtt SlackNotifier.Arn
    TopicArn: !Ref OnCallTopic

🧩 4. TL;DR Summary
Integration Option	Effort	Recommended?	Notes
AWS Chatbot (Slack)	⭐ Easy	✅ Yes	Fully managed and native Slack integration
Lambda → Webhook	Medium	For advanced users	Flexible, custom formatting
Email	Low	OK	Simple, reliable fallback

📘 References
AWS Chatbot Documentation
CloudWatch Alarm Actions
Slack Incoming Webhooks
Author: CloudWatch–Slack Integration Guide
Version: 1.0
License: MIT
