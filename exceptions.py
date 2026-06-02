"""Custom exceptions for temporal-build-worker."""


class TemporalWorkerError(Exception):
    """Base exception for temporal-build-worker."""


class ConfigError(TemporalWorkerError):
    """Raised when required configuration is missing or invalid."""


class CredentialError(TemporalWorkerError):
    """Raised when a required credential cannot be resolved."""


class ActivityRuntimeError(TemporalWorkerError):
    """Raised when an activity fails at runtime."""
