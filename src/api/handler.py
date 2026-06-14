"""
API Lambda — front door of the demo.

Flow for each request:
  1. Parse ?fault= query param (slow | error | absent)
  2. Invoke the worker Lambda synchronously
  3. Write a result record to DynamoDB
  4. Return 200 (or 500 if the worker raised)

X-Ray: aws_xray_sdk patches boto3 so every AWS SDK call (Lambda invoke,
DynamoDB put_item) automatically appears as a child subsegment in the
X-Ray trace timeline — no extra code needed beyond the patch_all() call.
"""

import json
import logging
import os
import uuid

import boto3
from aws_xray_sdk.core import patch_all, xray_recorder

# patch_all() wraps boto3 clients so their calls become X-Ray subsegments
patch_all()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

WORKER_FUNCTION_NAME = os.environ["WORKER_FUNCTION_NAME"]
TABLE_NAME = os.environ["TABLE_NAME"]

lambda_client = boto3.client("lambda")
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)


def lambda_handler(event, context):
    # Read ?fault= from the HTTP query string (API GW passes it here)
    qs = event.get("queryStringParameters") or {}
    fault = qs.get("fault", "none")
    request_id = str(uuid.uuid4())

    logger.info("api Lambda: requestId=%s fault=%s", request_id, fault)

    # Lambda active tracing creates a read-only FacadeSegment — annotations
    # must go on a subsegment we open ourselves, not on the root segment.
    with xray_recorder.in_subsegment("api-handler") as subsegment:
        subsegment.put_annotation("fault_mode", fault)
        subsegment.put_annotation("request_id", request_id)

        # ── Step 1: invoke the worker Lambda ─────────────────────────────
        # Because boto3 is patched, this call appears as a "Lambda" subsegment
        # in the trace. The worker's own segment links back via the trace header
        # that the SDK injects automatically.
        response = None
        try:
            response = lambda_client.invoke(
                FunctionName=WORKER_FUNCTION_NAME,
                InvocationType="RequestResponse",
                Payload=json.dumps({"fault": fault}),
            )
            payload = json.loads(response["Payload"].read())
            worker_ok = True
            status_code = 200
        except Exception as exc:
            logger.error("Worker invocation failed: %s", exc)
            payload = {"error": str(exc)}
            worker_ok = False
            status_code = 500

        # Worker itself may have raised (Lambda surfaces this as FunctionError)
        if response and response.get("FunctionError"):
            logger.error("Worker returned FunctionError: %s", payload)
            worker_ok = False
            status_code = 500

        # ── Step 2: write result to DynamoDB ─────────────────────────────
        # Patched boto3 makes this a "DynamoDB" subsegment automatically.
        table.put_item(Item={
            "requestId": request_id,
            "fault": fault,
            "workerOk": worker_ok,
            "workerPayload": json.dumps(payload),
        })

    return {
        "statusCode": status_code,
        "body": json.dumps({
            "requestId": request_id,
            "fault": fault,
            "worker": payload,
        }),
    }
