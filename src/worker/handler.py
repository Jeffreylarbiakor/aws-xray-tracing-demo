"""
Worker Lambda — downstream service called by the api Lambda.

Fault switch (passed in the event payload):
  fault=slow   → sleep 2 s (simulates a slow dependency)
  fault=error  → raise RuntimeError (simulates an unhandled failure)
  (default)    → returns immediately (healthy path)

X-Ray: Lambda automatically creates a segment for this function because
Tracing: Active is set in template.yaml. We add one custom subsegment
("process") so the trace timeline shows meaningful internal structure.
"""

import time
import logging

from aws_xray_sdk.core import xray_recorder

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    fault = event.get("fault", "none")
    logger.info("Worker received fault=%s", fault)

    # Custom subsegment — visible as a named block in the X-Ray trace timeline
    with xray_recorder.in_subsegment("process") as subsegment:
        subsegment.put_annotation("fault_mode", fault)

        if fault == "slow":
            # Annotate before sleeping so the timeline shows exactly when it started
            subsegment.put_metadata("sleep_seconds", 2)
            time.sleep(2)

        elif fault == "error":
            # Mark the subsegment as errored before raising so X-Ray captures it
            subsegment.put_annotation("error", True)
            raise RuntimeError("Injected fault: worker raised an error")

    return {"status": "ok", "fault": fault}
