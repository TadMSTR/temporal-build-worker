import asyncio
import logging
import signal
import uuid

import structlog

from temporalio.client import Client, TLSConfig
from temporalio.contrib.pydantic import pydantic_data_converter
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
from config import load_config
from exceptions import CredentialError
from observability import init_observability
from workflows.build_plan import BuildPlanWorkflow
from workflows.build_pipeline_workflow import BuildPipelineWorkflow

WORKER_ID: str = str(uuid.uuid4())


def _configure_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def main() -> None:
    config = load_config()
    _configure_logging(config.log_level)
    init_observability()

    log = structlog.get_logger().bind(worker_id=WORKER_ID)

    # ── mTLS via Vault ────────────────────────────────────────────────────────
    tls: TLSConfig | bool = False
    if config.vault_addr and config.vault_role_id and config.vault_secret_id_file:
        try:
            try:
                from vault import fetch_temporal_credentials
            except ImportError as e:
                raise CredentialError(
                    "VAULT_ADDR is set but hvac is not installed. "
                    "Install with: pip install hvac"
                ) from e
            creds = fetch_temporal_credentials(
                vault_addr=config.vault_addr,
                role_id=config.vault_role_id,
                secret_id_file=config.vault_secret_id_file,
            )
            tls = TLSConfig(
                server_root_ca_cert=creds.ca_cert_pem,
                client_cert=creds.client_cert_pem,
                client_private_key=creds.client_key_pem,
            )
            log.info("tls_enabled", vault_addr=config.vault_addr)
        except CredentialError as e:
            log.error("tls_credential_error", error=str(e))
            raise
    else:
        log.warning("tls_disabled", reason="no_vault_config")

    log.info(
        "worker_starting",
        address=config.temporal_address,
        namespace=config.temporal_namespace,
        task_queue=config.task_queue,
        tls=tls is not False,
    )

    client = await Client.connect(
        config.temporal_address,
        namespace=config.temporal_namespace,
        tls=tls,
        data_converter=pydantic_data_converter,
    )
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    worker = Worker(
        client,
        task_queue=config.task_queue,
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

    log.info("worker_started", task_queue=config.task_queue, address=config.temporal_address)
    async with worker:
        await stop_event.wait()

    log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
