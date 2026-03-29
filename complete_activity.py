#!/usr/bin/env python3
"""
Signal Temporal async activity completion from Claude Code build-close-out.

Usage:
    python3 complete_activity.py <task_token_b64> success [output_message]
    python3 complete_activity.py <task_token_b64> failed  [error_message]

The task_token_b64 comes from the task queue YAML payload.task_token field.
"""
import asyncio
import base64
import sys

from temporalio.client import Client
from temporalio.exceptions import ApplicationError

from models import BuildPhaseResult

TEMPORAL_ADDRESS = "localhost:7233"
TEMPORAL_NAMESPACE = "default"


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    task_token_b64 = sys.argv[1]
    status = sys.argv[2]
    message = sys.argv[3] if len(sys.argv) > 3 else ""

    task_token = base64.b64decode(task_token_b64)
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)

    if status == "success":
        await client.complete_async_activity_by_token(
            task_token,
            BuildPhaseResult(status="success", output=message),
        )
        print(f"Activity completed: {message or 'success'}")

    elif status == "failed":
        await client.fail_async_activity_by_token(
            task_token,
            ApplicationError(message or "Phase failed", type="PhaseFailedError"),
        )
        print(f"Activity failed: {message or 'no details'}")

    else:
        print(f"Unknown status '{status}' — use 'success' or 'failed'")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
