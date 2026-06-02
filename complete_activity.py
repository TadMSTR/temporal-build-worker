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
import logging
import os
import sys

import structlog

from temporalio.client import Client, TLSConfig
from temporalio.exceptions import ApplicationError

from exceptions import CredentialError
from models import BuildPhaseResult

TEMPORAL_ADDRESS = "localhost:7233"
TEMPORAL_NAMESPACE = "default"


def _build_tls_config(log: structlog.BoundLogger) -> TLSConfig | bool:
    """
    Return a TLSConfig if Vault env vars are set, False otherwise.
    Raises CredentialError if Vault is configured but credential fetch fails.
    """
    vault_addr = os.environ.get("VAULT_ADDR")
    role_id = os.environ.get("VAULT_ROLE_ID")
    secret_id_file = os.environ.get("VAULT_SECRET_ID_FILE")

    if not (vault_addr and role_id and secret_id_file):
        log.warning("tls_disabled", reason="no_vault_config")
        return False

    try:
        try:
            from vault import fetch_temporal_credentials
        except ImportError as e:
            raise CredentialError(
                "VAULT_ADDR is set but hvac is not installed. "
                "Install with: pip install hvac"
            ) from e

        creds = fetch_temporal_credentials(
            vault_addr=vault_addr,
            role_id=role_id,
            secret_id_file=secret_id_file,
        )
        log.info("tls_enabled", vault_addr=vault_addr)
        return TLSConfig(
            server_root_ca_cert=creds.ca_cert_pem,
            client_cert=creds.client_cert_pem,
            client_private_key=creds.client_key_pem,
        )
    except CredentialError as e:
        log.error("tls_credential_error", error=str(e))
        raise


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def main() -> None:
    _configure_logging()
    log = structlog.get_logger().bind(script="complete_activity")

    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    task_token_b64 = sys.argv[1]
    status = sys.argv[2]
    message = sys.argv[3] if len(sys.argv) > 3 else ""

    if not task_token_b64:
        log.error("invalid_task_token", error="task token is empty")
        sys.exit(1)

    try:
        task_token = base64.b64decode(task_token_b64)
    except Exception as e:
        log.error("invalid_task_token", error=str(e))
        sys.exit(1)

    tls = _build_tls_config(log)
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=tls)
    handle = client.get_async_activity_handle(task_token=task_token)

    if status == "success":
        await handle.complete(
            BuildPhaseResult(status="success", output=message),
        )
        log.info("activity_completed", output=message or "success")

    elif status == "failed":
        await handle.fail(
            error=ApplicationError(message or "Phase failed", type="PhaseFailedError"),
        )
        log.info("activity_failed", output=message or "no details")

    else:
        log.error("unknown_status", status=status, expected=["success", "failed"])
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
