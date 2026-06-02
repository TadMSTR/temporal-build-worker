"""
HashiCorp Vault credential fetch for temporal-build-worker.

Fetches mTLS certs from Vault using AppRole auth at worker startup.
Adapted from scoped-mcp/src/scoped_mcp/credentials_vault.py.

Requires: pip install hvac
"""

from __future__ import annotations

from pathlib import Path

import structlog

from exceptions import CredentialError

try:
    import hvac
    import hvac.exceptions
except ImportError as _e:
    raise ImportError(
        "Vault credential fetch requires hvac. Install with: pip install hvac"
    ) from _e

log = structlog.get_logger(__name__)

_VAULT_PATH = "secret/data/temporal/worker"


class TemporalCredentials:
    """mTLS cert bundle fetched from Vault."""

    def __init__(
        self,
        ca_cert_pem: bytes,
        client_cert_pem: bytes,
        client_key_pem: bytes,
    ) -> None:
        self.ca_cert_pem = ca_cert_pem
        self.client_cert_pem = client_cert_pem
        self.client_key_pem = client_key_pem


def fetch_temporal_credentials(
    vault_addr: str,
    role_id: str,
    secret_id_file: str,
) -> TemporalCredentials:
    """
    Authenticate with Vault via AppRole and fetch worker mTLS certs.

    Returns a TemporalCredentials bundle. The secret_id is read from a file
    and discarded immediately after authentication. Raises CredentialError
    on any failure.
    """
    # Read secret_id from file — discarded immediately after auth
    try:
        secret_id = Path(secret_id_file).read_text().strip()
    except OSError as e:
        raise CredentialError(
            f"Cannot read VAULT_SECRET_ID_FILE={secret_id_file!r}: {e}"
        ) from e

    if not secret_id:
        raise CredentialError(
            f"VAULT_SECRET_ID_FILE={secret_id_file!r} is empty"
        )

    try:
        client = hvac.Client(url=vault_addr)
        auth_resp = client.auth.approle.login(
            role_id=role_id,
            secret_id=secret_id,
        )
        # Drop secret_id binding before any further calls that may fail
        secret_id = ""

        lease_duration = auth_resp["auth"].get("lease_duration", 3600)

        resp = client.secrets.kv.v2.read_secret_version(path="temporal/worker")
        raw = resp["data"]["data"]

        if not isinstance(raw, dict):
            raise CredentialError(
                f"Vault path {_VAULT_PATH!r}: expected a dict, got {type(raw).__name__}"
            )

        for field in ("ca_cert_pem", "client_cert_pem", "client_key_pem"):
            if field not in raw:
                raise CredentialError(
                    f"Vault path {_VAULT_PATH!r}: missing field {field!r}"
                )

        log.info(
            "vault_credentials_fetched",
            vault_addr=vault_addr,
            path=_VAULT_PATH,
            lease_duration=lease_duration,
        )

        return TemporalCredentials(
            ca_cert_pem=raw["ca_cert_pem"].encode() if isinstance(raw["ca_cert_pem"], str) else raw["ca_cert_pem"],
            client_cert_pem=raw["client_cert_pem"].encode() if isinstance(raw["client_cert_pem"], str) else raw["client_cert_pem"],
            client_key_pem=raw["client_key_pem"].encode() if isinstance(raw["client_key_pem"], str) else raw["client_key_pem"],
        )

    except CredentialError:
        raise
    except hvac.exceptions.VaultError as e:
        raise CredentialError(
            f"Vault error at {vault_addr!r}: {e}"
        ) from e
    except Exception as e:
        raise CredentialError(
            f"Failed to connect to Vault at {vault_addr!r}: {type(e).__name__}: {e}"
        ) from e
