#!/usr/bin/env python3
"""
Create + publish an Amazon Bedrock Guardrail with:
- High/BLOCK filters for HATE, INSULTS, SEXUAL, VIOLENCE, MISCONDUCT, PROMPT_ATTACK
- PII entities (BLOCK I/O): AWS_ACCESS_KEY, AWS_SECRET_KEY, IP_ADDRESS, URL, EMAIL, PASSWORD, CREDIT_CARD
- Custom regex blocks: GitHub token, Slack token, JWT, PEM private key header, internal hostnames
- Denied topics + denied words lists (policy-style)
Outputs Guardrail ID/ARN/Version.
"""
import boto3, os, json, uuid

REGION = os.getenv("AWS_REGION", "us-east-1")  # change if needed
NAME   = os.getenv("GUARDRAIL_NAME", f"guardrail-{str(uuid.uuid4())[:8]}")
DESC   = "Guardrail with harmful content + prompt-attack protection, secrets/PII blocks, regexes, and deny lists."

blocked_msg_in  = "Sorry, the model cannot answer this question."
blocked_msg_out = "Sorry, the model cannot answer this question."

bedrock = boto3.client("bedrock", region_name=REGION)

# -----------------------------
# Content Filters (HIGH/BLOCK)
# Note: PROMPT_ATTACK can only be applied to inputs, not outputs
# -----------------------------
standard_filter_types = ["HATE","INSULTS","SEXUAL","VIOLENCE","MISCONDUCT"]
filters_config = [
    {
        "type": t,
        "inputStrength": "HIGH",
        "outputStrength": "HIGH",
        "inputModalities": ["TEXT"],
        "outputModalities": ["TEXT"],
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    } for t in standard_filter_types
]

# Add PROMPT_ATTACK filter separately (input only)
filters_config.append({
    "type": "PROMPT_ATTACK",
    "inputStrength": "HIGH",
    "outputStrength": "NONE",  # Must be NONE for PROMPT_ATTACK
    "inputModalities": ["TEXT"],
    "outputModalities": ["TEXT"],
    "inputAction": "BLOCK",
    "outputAction": "NONE",  # Must be NONE for PROMPT_ATTACK
    "inputEnabled": True,
    "outputEnabled": False,  # Disabled for output
})

# -----------------------------
# Sensitive Info (PII entities)
# -----------------------------
pii_entities = [
    {"type": "AWS_ACCESS_KEY", "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "AWS_SECRET_KEY", "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "IP_ADDRESS",     "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "URL",            "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "EMAIL",          "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "PASSWORD",       "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "CREDIT_DEBIT_CARD_NUMBER", "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "CREDIT_DEBIT_CARD_CVV",    "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
    {"type": "CREDIT_DEBIT_CARD_EXPIRY", "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK","inputEnabled":True,"outputEnabled":True},
]

# -----------------------------
# Custom Regex blocks
# -----------------------------
regexes = [
    {
        "name": "InternalHostnames",
        "description": "Block internal/corporate hostnames",
        # Matches e.g., foo.corp.example, api.internal.company, svc.cluster.local
        "pattern": r"(?:[a-zA-Z0-9-]+\.)+(?:corp|internal|intra|lan|local|svc|cluster)\.[a-zA-Z0-9.-]+",
        "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK",
        "inputEnabled": True, "outputEnabled": True,
    },
    {
        "name": "GitHubToken",
        "description": "Block GitHub tokens",
        "pattern": r"gh[pousr]_[A-Za-z0-9]{36,}",
        "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK",
        "inputEnabled": True, "outputEnabled": True,
    },
    {
        "name": "SlackToken",
        "description": "Block Slack tokens",
        "pattern": r"xox[baprs]-[A-Za-z0-9-]{10,48}",
        "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK",
        "inputEnabled": True, "outputEnabled": True,
    },
    {
        "name": "JWT",
        "description": "Block JSON Web Tokens",
        "pattern": r"eyJ[A-Za-z0-9_-]+?\.[A-Za-z0-9_-]+?\.[A-Za-z0-9_-]+",
        "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK",
        "inputEnabled": True, "outputEnabled": True,
    },
    {
        "name": "PEMPrivateKeyHeader",
        "description": "Block PEM private key headers",
        "pattern": r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
        "action": "BLOCK", "inputAction":"BLOCK","outputAction":"BLOCK",
        "inputEnabled": True, "outputEnabled": True,
    },
]

# -----------------------------
# Denied Topics (policy-style)
# -----------------------------
topics_config = [
    {
        "type": "DENY",  # <-- REQUIRED
        "name": "CredentialSharing",
        "definition": "Requests or responses that include providing, requesting, or circulating authentication secrets or tokens.",
        "examples": [
            "Share access keys", "Provide my secret key", "Give me the login token",
            "Show kubectl config", "Tell me your API key"
        ],
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    },
    {
        "type": "DENY",  # <-- REQUIRED
        "name": "InternalArchitecture",
        "definition": "Requests for non-public internal system details, hostnames, or network topology.",
        "examples": [
            "List internal servers", "Tell me the cluster endpoints", "What is the prod DB hostname?",
            "Share VPC CIDRs", "Show private URLs"
        ],
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    },
]

# -----------------------------
# Denied Words/Phrases
# -----------------------------
words_config = [
    {
        "text": "access key",
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    },
    {
        "text": "secret key",
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    },
    {
        "text": "internal hostname",
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    },
    {
        "text": "jwt token",
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    },
    {
        "text": "private key",
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    },
]

# Fixed: Managed word lists need to be dictionaries, not strings
managed_word_lists = [
    {
        "type": "PROFANITY",
        "inputAction": "BLOCK",
        "outputAction": "BLOCK",
        "inputEnabled": True,
        "outputEnabled": True,
    }
]

print(f"Creating guardrail '{NAME}' in {REGION}...")

word_policy = {"wordsConfig": words_config}
# Add managed word lists if you want to enable profanity filtering
word_policy["managedWordListsConfig"] = managed_word_lists

resp = bedrock.create_guardrail(
    name=NAME,
    description=DESC,

    topicPolicyConfig={"topicsConfig": topics_config},

    contentPolicyConfig={"filtersConfig": filters_config},

    wordPolicyConfig=word_policy,

    sensitiveInformationPolicyConfig={
        "piiEntitiesConfig": pii_entities,
        "regexesConfig": regexes,
    },

    blockedInputMessaging=blocked_msg_in,
    blockedOutputsMessaging=blocked_msg_out,

    tags=[{"key": "Owner", "value": "BedrockScript"}],

    # Grounding/relevance checks — left disabled to match your prior state.
    # When ready, uncomment and adjust the actions/thresholds as needed:
    # contextualGroundingPolicyConfig={
    #     "groundingCheckConfig": {
    #         "enabled": True,
    #         "action": "BLOCK"   # or "SAFE_COMPLETE" if you prefer
    #     },
    #     "relevanceCheckConfig": {
    #         "enabled": True,
    #         "action": "BLOCK"
    #     }
    # },
)

guardrail_id  = resp["guardrailId"]
guardrail_arn = resp["guardrailArn"]

print("Created guardrail:")
print(json.dumps({"guardrailId": guardrail_id, "guardrailArn": guardrail_arn}, indent=2))

print("Publishing version...")
ver = bedrock.create_guardrail_version(guardrailIdentifier=guardrail_id)
guardrail_version = ver["version"]

print("Done.")
print(json.dumps({
    "region": REGION,
    "name": NAME,
    "guardrailId": guardrail_id,
    "guardrailArn": guardrail_arn,
    "guardrailVersion": guardrail_version
}, indent=2))