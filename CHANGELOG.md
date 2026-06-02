# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

## [0.5.0] - 2026-06-01

### Added
- Worker-side mTLS via HashiCorp Vault AppRole (`vault.py`) — fetches CA cert, client cert, and client private key from `secret/data/temporal/worker` at startup; passes `TLSConfig` to `Client.connect()`. Graceful plaintext fallback when Vault env vars are not set.
- `complete_activity.py` now supports Vault mTLS via the same env-var pattern (`VAULT_ADDR`, `VAULT_ROLE_ID`, `VAULT_SECRET_ID_FILE`) — prevents workflow stall when `requireClientAuth: true` is enabled on the Temporal server (M-01).
- `config.py` — `WorkerConfig` Pydantic model with validated env var loading.
- `exceptions.py` — custom exception hierarchy (`TemporalWorkerError`, `ConfigError`, `CredentialError`, `ActivityRuntimeError`).
- `observability.py` — opt-in OpenTelemetry tracing and metrics stubs; no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset.

### Changed
- Structured logging via `structlog` throughout — JSON format, `worker_id` bound per process, `workflow_id` + `activity_type` bound per activity invocation.
- `BuildPipelineInput`, `TriageOutput`, `BuildPipelineResult` converted from dataclasses to Pydantic `BaseModel`; `pydantic_data_converter` registered on `Client`.
- `build_name` validated with `Field(pattern=r'^[a-z0-9][a-z0-9-]*$')` at Pydantic deserialization — removes inline `re.match` from workflow code.
- `apply_flag_fixes` instruction now wraps triage flag content in `<security-findings>` delimiters to prevent prompt injection across agent trust boundaries (L-02).
- `inc_counter` caches OTel counter instruments by name to avoid duplicate instrument registration (I-02).

### Fixed
- `build_phase.py` and `notify_blocks`: task queue files containing `task_token` credentials now written with `os.open(O_WRONLY|O_CREAT|O_TRUNC, 0o600)` — prevents umask-derived 0o644 permissions (FW-03).
- `worker.py`: `ImportError` from missing `hvac` package is now caught and re-raised as `CredentialError` with an actionable message (L-01).

### Removed
- `httpx` dependency — unused in source (I-03).

## [0.4.0] - 2026-05-28

### Changed
- **Renamed** from `helm-temporal-worker` to `temporal-build-worker` — GitHub repo, PM2 service name, directory path, and logger name updated throughout.
- `NTFY_URL` default changed from a placeholder URL to `""` — ntfy notifications are silently skipped when not configured.
- `AUDIT_DIR` is now env-configurable via `TEMPORAL_AUDIT_DIR` (default corrected to `~/.claude/comms/artifacts` to match the actual audit report layout).
- `TEMPORAL_ADDRESS` is now env-configurable via `TEMPORAL_ADDRESS` environment variable (default `localhost:7233`).

### Fixed
- `notify_blocks`: task file update now uses an atomic tmp→rename write pattern instead of a direct `write_text()` call, preventing partial-write corruption.
- `_send_ntfy`: was a blocking sync `httpx.post()` inside an async activity — wrapped in `asyncio.to_thread()` to avoid blocking the event loop during notification delivery.
- `process_triage_output`: raises `ApplicationError(non_retryable=True)` on malformed YAML input instead of silently treating it as an empty triage result.

## [0.3.0] - 2026-04-12

### Added
- `BuildPipelineWorkflow` — end-to-end autonomous build pipeline workflow with 9 activities covering the full lifecycle: prefab scaffolding, build execution, security audit, flag remediation, and build close-out. Each agent-invoking activity writes a base64 `task_token` into the task YAML file; agents signal completion via `~/scripts/temporal-complete`. Non-agent activities (prefab, block-wait, deploy-script-update, release-notes, build-unblock) execute inline.
- `wait_for_block_resolution` activity with 7-day `schedule_to_close` timeout and 5-minute heartbeat — allows the workflow to park until a security BLOCK is resolved without holding a worker thread.
- Determinism contract enforced throughout: `workflow.now()` and `workflow.uuid4()` used in workflow code; `datetime.now()` permitted only in activity code.

## [0.2.0] - 2026-03-29

### Added
- `BuildPlanWorkflow` — dispatches sequential build phases as task YAML files to `~/.claude/task-queue/`; agents signal completion via `~/scripts/temporal-complete` with a base64-encoded task token.
- `complete_activity.py` script wrapping the Temporal async activity completion API.
- PM2 `helm-temporal-worker` service entry in `ecosystem.config.js`.

### Fixed
- Replaced absolute home paths in `ecosystem.config.js` with `__dirname`-relative paths (PR #1).
- Validated base64 task token before decode in `complete_activity.py`.
- Async activity completion API compatibility with `temporalio` 1.24.0.

## [0.1.0] - 2026-03-28

### Added
- Initial worker: `BuildPlanWorkflow` skeleton, async activity completion pattern, gitignore for core dumps.

[Unreleased]: https://github.com/TadMSTR/temporal-build-worker/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/TadMSTR/temporal-build-worker/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/TadMSTR/temporal-build-worker/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/TadMSTR/temporal-build-worker/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/TadMSTR/temporal-build-worker/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/TadMSTR/temporal-build-worker/releases/tag/v0.1.0
