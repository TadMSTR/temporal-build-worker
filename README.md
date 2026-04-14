# helm-temporal-worker

Python Temporal worker that drives autonomous build pipelines on the Helm platform. Bridges [Temporal](https://temporal.io/) durable execution to Claude Code agent sessions via the task-queue async activity completion pattern.

Current version: **v0.3.0**

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
| 3 | `request_security_audit` | security-agent | async task token |
| 4 | `process_triage_output` | — | inline (polls for YAML) |
| 5 | `apply_flag_fixes` | target agent | async task token (if flags) |
| 6 | `notify_blocks` | — | inline (ntfy + task update) |
| 7 | `wait_for_block_resolution` | — | inline poll, 7-day timeout |
| 8 | `close_build` | target agent | async task token |
| 9 | `summarize_workflow` | — | inline (writes YAML summary) |

Input: `BuildPipelineInput(build_name, plan_path, task_id, target_agent)`

### `BuildPlanWorkflow`

Simpler phase-based workflow. Dispatches sequential build phases as task YAML files. Used for phased builds where each phase is a discrete agent handoff.

---

## Async Activity Completion Pattern

Agent-invoking activities (stages 1, 2, 3, 5, 8) work the same way:

1. Activity encodes its Temporal task token as base64
2. Writes a task YAML to `~/.claude/task-queue/` with `payload.task_token` embedded
3. Calls `activity.raise_complete_async()` — Temporal suspends the activity
4. The picked-up agent does its work, then calls:
   ```
   python3 ~/repos/personal/helm-temporal-worker/complete_activity.py $TASK_TOKEN success [output]
   ```
5. Temporal resumes the activity with the result

This decouples the worker from agent execution time — a build can take hours and the worker holds no thread.

### `complete_activity.py`

Used by agents to signal completion back to Temporal:

```
python3 complete_activity.py <task_token_b64> success [output_message]
python3 complete_activity.py <task_token_b64> failed  [error_message]
```

The `task_token_b64` value comes from `payload.task_token` in the task YAML. A symlink at `~/scripts/temporal-complete` points here for convenience.

---

## Security Audit Integration

Stage 3 writes a `request.md` to `~/repos/audits/security-audits/<build_name>/` describing the audit scope and the expected output format. The security agent writes `report.md` and `triage-output.yml` to the same directory on completion.

`triage-output.yml` schema:
```yaml
blocks:
  - description: ...   # requires Ted's decision before close
flags:
  - description: ...   # auto-fixable, applied by build agent
info:
  - description: ...   # informational, no action required
```

Blocks trigger ntfy notifications and park the workflow for up to 7 days waiting for approval (task status `input-required` → `approved`). Flags are dispatched to the build agent as a `security_fix` task.

---

## Setup

Requires Python 3.13+ and a running Temporal server at `localhost:7233`.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `NTFY_URL` | `https://ntfy.your-domain.com/claudebox-alerts` | ntfy endpoint for block notifications |

---

## Running

### PM2 (production)

```bash
pm2 start ecosystem.config.js
pm2 save
```

The service is named `helm-temporal-worker` and uses the local venv Python. Autorestart enabled with exponential backoff.

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
models.py                        # Dataclasses for workflow/activity I/O
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
| Address | `localhost:7233` |
| Namespace | `default` |
| Task queue | `helm-build` |

Workflow summaries are written to `~/repos/personal/agent-activity/workflows/<YYYY-MM>/<workflow_id>.yml` on pipeline completion.
