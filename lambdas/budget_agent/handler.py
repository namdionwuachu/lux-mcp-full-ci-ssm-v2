"""Lambda shim for budget agent."""
import json
from .agent import run
def lambda_handler(event, context):
    task = json.loads(event.get("body") or event.get("Records", [{}])[0].get("body", "{}")); out = run(task); return {"statusCode":200,"body":json.dumps(out)}
