# temporal-build-worker

Python Temporal worker that drives autonomous build pipelines on the forge agent platform. Bridges [Temporal](https://temporal.io/) durable execution to Claude Code agent sessions via the task-queue async activity completion pattern.

Current version: **v0.5.0**

---

## Overview

The worker connects to a local Temporal server and processes tasks on the `helm-build` task queue. When a build is triggered, it runs a `BuildPipelineWorkflow` that coordinates the full build lifecycle across multiple Claude Code agents — dispatching work as YAML task files and waiting for agents to signal completion via `complete_activity.py`.

Temporal provides durability: if the worker restarts mid-pipeline, the workflow replays from the last completed activity. Each agent-dispatching activity uses the async completion pattern — Temporal suspends the activity until an agent explicitly signals done.

---

## Workflows

### `BuildPipelineWorkflow`

End-to-end autonomous build pipeline. Nine sequential stages:

| Stage | Activity | Agent | Pattern |
|-------|----------|-------|---------|
| 1 | `prefab_scaffolding` | claudebox | async task token |
| 2 | `implement_build` | target agent | async task token |
| 3 | `request_security_audit` | security agent | async task token |
| 4 | `process_triage_output` | — | inline (polls for YAML) |
| 5 | `apply_flag_fixes` | target agent | async task token (if flags) |
| 6 | `notify_blocks` | — | inline (Matrix + task update) |
| 7 | `wait_for_block_resolution` | — | inline poll, 7-day timeout |
| 8 | `close_build` | target agent | async task token |
| 9 | `summarize_workflow` | — | inline (writes YAML summary) |

Input: `BuildPipelineInput(build_name, plan_path, task_id, target_agent)`

`build_name` must match `^[a-z0-9][a-z0-9-]*$` — validated at Pydantic deserialization.

### `BuildPlanWorkflow`

Simpler phase-based workflow. Dispatches sequential build phases as task YAML files. Used for phased builds where each phase is a discrete agent handoff.

---

## Async Activity Completion Pattern

Agent-invoking activities (stages 1, 2, 3, 5, 8) work the same way:

1. Activity encodes its Temporal task token as base64
2. Writes a task YAML to `~/.claude/task-queue/` with `payload.task_token` embedded
3. Calls `activity.raise_complete_async()` — Temporal suspends the activity
4. The picked-up agent does its work, then signals completion:
   ```bash
   python3 ~/repos/personal/temporal-build-worker/complete_activity.py $TASK_TOKEN success [output]
   ```
5. Temporal resumes the activity with the result

This decouples the worker from agent execution time — a build can take hours and the worker holds no thread.

### `complete_activity.py`

Used by agents to signal completion back to Temporal:

```bash
python3 complete_activity.py <task_token_b64> success [output_message]
python3 complete_activity.py <task_token_b64> failed  [error_message]
```

The `task_token_b64` value comes from `payload.task_token` in the task YAML.

When mTLS is enabled (Vault env vars set), `complete_activity.py` fetches TLS credentials from Vault before connecting. This matches the worker's TLS configuration.

---

## Security Audit Integration

Stage 3 writes an audit request to `~/.claude/comms/artifacts/audit-requests/<build_name>/request.md`. The security agent writes `audit.md` and `triage-output.yml` on completion.

`triage-output.yml` schema:
```yaml
blocks:
  - description: ...   # requires operator decision before close
flags:
  - description: ...   # auto-fixable, dispatched to build agent
info:
  - description: ...   # informational, no action required
```

Blocks trigger Matrix notifications and park the workflow for up to 7 days. Flags are dispatched to the build agent as a `security_fix` task. Flag content is wrapped in `<security-findings>` delimiters before reaching the agent prompt.

---

## Setup

Requires Python 3.13+ and a running Temporal server at `localhost:7233`.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For mTLS support, also install:
```bash
pip install hvac
```

---

## Configuration

All configuration is via environment variables. Non-secret values are logged at startup; secret values are never logged.

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPORAL_ADDRESS` | `localhost:7233` | Temporal gRPC endpoint |
| `TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `TASK_QUEUE` | `helm-build` | Worker task queue name |
| `MATRIX_ROOM` | `sysadmin` | Matrix room for block notifications |
| `LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FILE` | — | Optional log file path (in addition to stdout) |

### mTLS via Vault (optional)

When all three Vault vars are set, the worker fetches mTLS credentials from Vault at startup and passes them to `Client.connect()`. If any are unset, the worker connects without TLS.

| Variable | Description |
|----------|-------------|
| `VAULT_ADDR` | Vault server address (e.g. `http://127.0.0.1:8200`) |
| `VAULT_ROLE_ID` | AppRole role ID |
| `VAULT_SECRET_ID_FILE` | Path to file containing the AppRole secret ID |

The secret ID is read from the file and wiped from memory immediately after authentication. Vault path: `secret/data/temporal/worker`. Required fields: `ca_cert_pem`, `client_cert_pem`, `client_key_pem`.

### OpenTelemetry (optional)

| Variable | Description |
|----------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint — enables tracing and metrics |
| `OTEL_SERVICE_NAME` | Service name in traces (default: `temporal-build-worker`) |

OTel is fully opt-in. When `OTEL_EXPORTER_OTLP_ENDPOINT` is not set, all instrumentation is no-op and the `opentelemetry-*` packages are not required.

---

## Running

### PM2 (production)

```bash
pm2 start ecosystem.config.js
pm2 save
```

The service is named `temporal-build-worker` and uses the local venv Python. Autorestart enabled with exponential backoff (max 10 restarts).

### Direct

```bash
source venv/bin/activate
python3 worker.py
```

---

## Project Structure

```
worker.py                        # Entry point — connects to Temporal, registers worker
complete_activity.py             # CLI: signal async activity completion from agent
config.py                        # WorkerConfig Pydantic model, load_config()
vault.py                         # Vault AppRole credential fetch for mTLS
exceptions.py                    # Exception hierarchy
observability.py                 # OTel tracing/metrics stubs (opt-in)
models.py                        # Pydantic models and dataclasses for workflow I/O
ecosystem.config.js              # PM2 service config
workflows/
  build_pipeline_workflow.py     # 9-stage end-to-end build pipeline
  build_plan.py                  # Phase-based workflow (simple builds)
activities/
  build_pipeline_activities.py   # All 9 activities for BuildPipelineWorkflow
  build_phase.py                 # Phase execution activity (BuildPlanWorkflow)
```

---

## Temporal Config

| Setting | Value |
|---------|-------|
| Address | `localhost:7233` (override via `TEMPORAL_ADDRESS`) |
| Namespace | `default` (override via `TEMPORAL_NAMESPACE`) |
| Task queue | `helm-build` (override via `TASK_QUEUE`) |
| Data converter | `pydantic_data_converter` |

---

## Security

- **mTLS**: Worker and `complete_activity.py` support mutual TLS via Vault AppRole. Cert material lives in memory only — never written to disk.
- **Credential files**: Task queue files containing `task_token` values are written with `0o600` permissions using `os.open()` to prevent umask-derived world-readable permissions.
- **Prompt injection**: Triage flag content dispatched to build agents is wrapped in `<security-findings>` delimiters with an explicit data instruction.
- **Input validation**: `build_name` validated against `^[a-z0-9][a-z0-9-]*$` at Pydantic deserialization before any filesystem or workflow operations.
