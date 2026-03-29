import asyncio
import logging
import signal

from temporalio.client import Client
from temporalio.worker import Worker

from activities.build_phase import execute_build_phase
from workflows.build_plan import BuildPlanWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("helm-temporal-worker")

TEMPORAL_ADDRESS = "localhost:7233"
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
        workflows=[BuildPlanWorkflow],
        activities=[execute_build_phase],
    )

    logger.info(f"Helm Temporal worker started — task queue '{TASK_QUEUE}'")
    async with worker:
        await stop_event.wait()

    logger.info("Helm Temporal worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
