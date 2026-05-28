import asyncio
import logging
import os
import signal

from temporalio.client import Client
from temporalio.worker import Worker

from activities.build_phase import execute_build_phase
from activities.build_pipeline_activities import (
    apply_flag_fixes,
    close_build,
    implement_build,
    notify_blocks,
    prefab_scaffolding,
    process_triage_output,
    request_security_audit,
    summarize_workflow,
    wait_for_block_resolution,
)
from workflows.build_plan import BuildPlanWorkflow
from workflows.build_pipeline_workflow import BuildPipelineWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("temporal-build-worker")

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = "default"
TASK_QUEUE = "helm-build"


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            BuildPlanWorkflow,
            BuildPipelineWorkflow,
        ],
        activities=[
            execute_build_phase,
            prefab_scaffolding,
            implement_build,
            request_security_audit,
            process_triage_output,
            apply_flag_fixes,
            notify_blocks,
            wait_for_block_resolution,
            close_build,
            summarize_workflow,
        ],
    )

    logger.info(f"Temporal build worker started — task queue '{TASK_QUEUE}', address '{TEMPORAL_ADDRESS}'")
    async with worker:
        await stop_event.wait()

    logger.info("Temporal build worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
