"""
Validated configuration for temporal-build-worker.

Reads all config from environment variables. Raises ConfigError on missing
required values. Config fields are logged at INFO on startup — no secret values
are logged.
"""

import os
from pathlib import Path

import structlog
from pydantic import BaseModel

from exceptions import ConfigError

log = structlog.get_logger(__name__)


class WorkerConfig(BaseModel):
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    task_queue: str = "helm-build"
    matrix_room: str = "sysadmin"
    log_level: str = "INFO"
    log_file: str | None = None
    vault_addr: str | None = None
    vault_role_id: str | None = None
    vault_secret_id_file: str | None = None
    require_tls: bool = False


def load_config() -> WorkerConfig:
    """Load and validate config from environment. Raises ConfigError on invalid input."""
    secret_id_file = os.environ.get("VAULT_SECRET_ID_FILE")
    if secret_id_file and not Path(secret_id_file).exists():
        raise ConfigError(
            f"VAULT_SECRET_ID_FILE={secret_id_file!r} does not exist"
        )

    config = WorkerConfig(
        temporal_address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        temporal_namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        task_queue=os.environ.get("TASK_QUEUE", "helm-build"),
        matrix_room=os.environ.get("MATRIX_ROOM", "sysadmin"),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        log_file=os.environ.get("LOG_FILE") or None,
        vault_addr=os.environ.get("VAULT_ADDR") or None,
        vault_role_id=os.environ.get("VAULT_ROLE_ID") or None,
        vault_secret_id_file=secret_id_file or None,
        require_tls=os.environ.get("TEMPORAL_REQUIRE_TLS", "").lower() in ("1", "true", "yes"),
    )

    log.info(
        "config_loaded",
        temporal_address=config.temporal_address,
        temporal_namespace=config.temporal_namespace,
        task_queue=config.task_queue,
        matrix_room=config.matrix_room,
        log_level=config.log_level,
        vault_configured=config.vault_addr is not None,
        require_tls=config.require_tls,
    )
    return config
