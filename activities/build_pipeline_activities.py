"""
BuildPipelineWorkflow activities.

Agent-invoking activities (1, 2, 3, 5, 8) use the task_token pattern:
  - Write a task YAML to ~/.claude/task-queue/ with a base64-encoded Temporal
    task token embedded in payload.task_token
  - Call activity.raise_complete_async() — Temporal suspends the activity
  - The picked-up agent calls complete_activity.py <token> success|failed [output]
    when its work is done, which resumes the activity

Local activities (4, 6, 7, 9) do their work in-process and return normally.
"""

import asyncio
import base64
import os
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from temporalio import activity

from models import BuildPhaseResult, TriageOutput

# ─── Constants ────────────────────────────────────────────────────────────────

TASK_QUEUE_DIR = Path.home() / ".claude" / "task-queue"
AUDIT_DIR = Path.home() / "repos" / "audits" / "security-audits"
ACTIVITY_SUMMARY_DIR = Path.home() / "repos" / "personal" / "agent-activity" / "workflows"
NTFY_URL = "http://10.10.1.9:8080/claudebox-alerts"  # gitleaks:allow


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _write_task(task: dict) -> None:
    """Atomically write a task YAML to the task queue."""
    now = datetime.now(timezone.utc)
    task_id = task["id"]
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    tmp = TASK_QUEUE_DIR / f"{timestamp}-{task_id[:8]}.yml.tmp"
    target = TASK_QUEUE_DIR / f"{timestamp}-{task_id[:8]}.yml"
    TASK_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(yaml.dump(task, default_flow_style=False, allow_unicode=True))
    tmp.rename(target)


def _find_task_file(task_id: str) -> Optional[Path]:
    """Find a task file by ID in the queue and archive."""
    search_dirs = [TASK_QUEUE_DIR, TASK_QUEUE_DIR / "archive"]
    for d in search_dirs:
        if not d.exists():
            continue
        for path in d.glob("*.yml"):
            try:
                data = yaml.safe_load(path.read_text())
                if isinstance(data, dict) and data.get("id") == task_id:
                    return path
            except Exception:
                continue
    return None


def _build_agent_task(
    *,
    task_id: str,
    target_agent: str,
    task_type: str,
    summary: str,
    payload: dict,
    task_token_b64: str,
    now: datetime,
) -> dict:
    """Build a standard task queue entry with embedded task_token."""
    return {
        "id": task_id,
        "created": now.isoformat(),
        "source_agent": "temporal-worker",
        "target_agent": target_agent,
        "task_type": task_type,
        "risk_level": "low",
        "requires_approval": False,
        "status": "submitted",
        "summary": summary,
        "ttl_days": 7,
        "payload": {**payload, "task_token": task_token_b64},
        "result": {"output": None, "completed_by": None, "completed_at": None},
        "history": [
            {
                "timestamp": now.isoformat(),
                "status": "submitted",
                "actor": "temporal-worker",
                "note": summary,
            }
        ],
    }


def _send_ntfy(title: str, body: str, priority: str = "default", tags: str = "bell") -> None:
    """Fire-and-forget ntfy notification (best-effort)."""
    try:
        httpx.post(
            NTFY_URL,
            content=body.encode(),
            headers={
                "Title": title,
                "Tags": tags,
                "Priority": priority,
            },
            timeout=10,
        )
    except Exception as exc:
        activity.logger.warning(f"ntfy notification failed (non-fatal): {exc}")


# ─── Activity 1: prefab_scaffolding ──────────────────────────────────────────

@activity.defn
async def prefab_scaffolding(build_name: str, plan_path: str) -> BuildPhaseResult:
    """
    Dispatch a build-plan-prefab task to the claudebox agent.
    Prefab creates stub files and directories from the build plan before execution.
    Uses task_token pattern — completed externally by the claudebox agent.
    """
    info = activity.info()
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task_token_b64 = base64.b64encode(info.task_token).decode()

    task = _build_agent_task(
        task_id=task_id,
        target_agent="claudebox",
        task_type="build_prefab",
        summary=f"Prefab scaffolding for build '{build_name}'",
        payload={
            "build_name": build_name,
            "plan_path": plan_path,
            "instruction": (
                f"Run the build-plan-prefab skill for build '{build_name}'. "
                f"Plan is at: {plan_path}. "
                "After prefab completes, call: "
                "python3 ~/repos/personal/helm-temporal-worker/complete_activity.py "
                "$TASK_TOKEN success 'prefab-complete'"
            ),
        },
        task_token_b64=task_token_b64,
        now=now,
    )
    _write_task(task)
    activity.logger.info(f"Dispatched prefab task {task_id[:8]} for build '{build_name}'")
    activity.raise_complete_async()


# ─── Activity 2: implement_build ─────────────────────────────────────────────

@activity.defn
async def implement_build(
    build_name: str, originating_task_id: str, target_agent: str
) -> BuildPhaseResult:
    """
    Dispatch the build implementation task to the target agent.
    Uses task_token pattern — completed externally when the agent finishes the build.
    """
    info = activity.info()
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task_token_b64 = base64.b64encode(info.task_token).decode()

    task = _build_agent_task(
        task_id=task_id,
        target_agent=target_agent,
        task_type="build_plan",
        summary=f"Implement build: {build_name}",
        payload={
            "build_name": build_name,
            "originating_task_id": originating_task_id,
            "instruction": (
                f"Execute the build plan for '{build_name}'. "
                "Follow the standard phase-gated build workflow. "
                "When the build is complete and verified, call: "
                "python3 ~/repos/personal/helm-temporal-worker/complete_activity.py "
                "$TASK_TOKEN success 'build-complete'"
            ),
        },
        task_token_b64=task_token_b64,
        now=now,
    )
    _write_task(task)
    activity.logger.info(
        f"Dispatched build task {task_id[:8]} for '{build_name}' to {target_agent}"
    )
    activity.raise_complete_async()


# ─── Activity 3: request_security_audit ──────────────────────────────────────

@activity.defn
async def request_security_audit(build_name: str, plan_path: str) -> BuildPhaseResult:
    """
    Write a security audit request artifact and dispatch a task to the security agent.
    Uses task_token pattern — completed externally when the security agent finishes.
    """
    info = activity.info()
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task_token_b64 = base64.b64encode(info.task_token).decode()

    # Write the audit request artifact
    audit_dir = AUDIT_DIR / build_name
    audit_dir.mkdir(parents=True, exist_ok=True)
    request_path = audit_dir / "request.md"
    request_path.write_text(
        f"# Security Audit Request: {build_name}\n\n"
        f"**Requested by:** temporal-worker (BuildPipelineWorkflow)\n"
        f"**Date:** {now.date()}\n"
        f"**Build plan:** {plan_path}\n\n"
        "## Scope\n\n"
        f"Full security audit of the '{build_name}' build. "
        "Review all files created or modified during this build for:\n"
        "- Credential exposure or hardcoded secrets\n"
        "- Privilege escalation vectors\n"
        "- Network exposure (open ports, unauthenticated endpoints)\n"
        "- File permission issues\n"
        "- Container security (capabilities, volumes, network modes)\n\n"
        "## Output\n\n"
        f"Write `report.md` and `triage-output.yml` to: "
        f"`{audit_dir}/`\n\n"
        "### triage-output.yml schema\n\n"
        "```yaml\n"
        "blocks:\n"
        "  - description: ...\n"
        "flags:\n"
        "  - description: ...\n"
        "info:\n"
        "  - description: ...\n"
        "```\n\n"
        "- **blocks**: findings requiring a decision from Ted before the build closes\n"
        "- **flags**: auto-fixable findings the build agent can apply without input\n"
        "- **info**: informational findings, no action required\n\n"
        "## Completion\n\n"
        "After writing both files, call:\n"
        "```\n"
        "python3 ~/repos/personal/helm-temporal-worker/complete_activity.py "
        "$TASK_TOKEN success 'audit-complete'\n"
        "```\n"
    )

    task = _build_agent_task(
        task_id=task_id,
        target_agent="security-agent",
        task_type="security_audit",
        summary=f"Security audit for build '{build_name}'",
        payload={
            "build_name": build_name,
            "plan_path": plan_path,
            "audit_request_path": str(request_path),
            "output_dir": str(audit_dir),
            "instruction": (
                f"Run a security audit for build '{build_name}'. "
                f"Request details: {request_path}. "
                "Write report.md and triage-output.yml to the output_dir, then call temporal-complete."
            ),
        },
        task_token_b64=task_token_b64,
        now=now,
    )
    _write_task(task)
    activity.logger.info(
        f"Dispatched security audit task {task_id[:8]} for '{build_name}'; "
        f"request at {request_path}"
    )
    activity.raise_complete_async()


# ─── Activity 4: process_triage_output ───────────────────────────────────────

@activity.defn
async def process_triage_output(build_name: str) -> TriageOutput:
    """
    Read the triage-output.yml written by the security agent and return structured data.
    Retried with backoff by the workflow — the audit may not be complete immediately.
    """
    triage_path = AUDIT_DIR / build_name / "triage-output.yml"
    if not triage_path.exists():
        raise FileNotFoundError(
            f"triage-output.yml not found at {triage_path}; "
            "security audit may still be running"
        )

    raw = yaml.safe_load(triage_path.read_text()) or {}
    blocks = [str(b) for b in raw.get("blocks", []) if b]
    flags = [str(f) for f in raw.get("flags", []) if f]
    info = [str(i) for i in raw.get("info", []) if i]

    activity.logger.info(
        f"Triage for '{build_name}': "
        f"{len(blocks)} blocks, {len(flags)} flags, {len(info)} info"
    )
    return TriageOutput(blocks=blocks, flags=flags, info=info)


# ─── Activity 5: apply_flag_fixes ────────────────────────────────────────────

@activity.defn
async def apply_flag_fixes(
    build_name: str, flags: List[str], target_agent: str
) -> BuildPhaseResult:
    """
    Dispatch a task to the build agent to apply auto-fixable security findings (flags).
    Uses task_token pattern — completed externally when fixes are committed.
    """
    info = activity.info()
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task_token_b64 = base64.b64encode(info.task_token).decode()

    flags_text = "\n".join(f"- {f}" for f in flags)
    task = _build_agent_task(
        task_id=task_id,
        target_agent=target_agent,
        task_type="security_fix",
        summary=f"Apply security flag fixes for build '{build_name}' ({len(flags)} items)",
        payload={
            "build_name": build_name,
            "flags": flags,
            "instruction": (
                f"Apply the following auto-fixable security findings for build '{build_name}':\n\n"
                f"{flags_text}\n\n"
                "For each flag: apply the fix, commit the change, and record the commit hash. "
                "After all flags are resolved, call:\n"
                "python3 ~/repos/personal/helm-temporal-worker/complete_activity.py "
                "$TASK_TOKEN success 'flags-applied'"
            ),
        },
        task_token_b64=task_token_b64,
        now=now,
    )
    _write_task(task)
    activity.logger.info(
        f"Dispatched flag-fix task {task_id[:8]} for '{build_name}' "
        f"({len(flags)} flags) to {target_agent}"
    )
    activity.raise_complete_async()


# ─── Activity 6: notify_blocks ────────────────────────────────────────────────

@activity.defn
async def notify_blocks(
    build_name: str, task_id: str, blocks: List[str]
) -> None:
    """
    Send an ntfy notification for each blocking security finding and update the
    originating task to input-required so Ted knows a decision is needed.
    """
    # Send ntfy per block
    for i, block in enumerate(blocks, 1):
        _send_ntfy(
            title=f"[ACTION] {build_name}: block {i}/{len(blocks)} needs review",
            body=block,
            priority="high",
            tags="warning,action-required",
        )
        activity.logger.info(f"Sent ntfy for block {i}/{len(blocks)}: {block[:80]}")

    # Update the originating task status to input-required
    task_file = _find_task_file(task_id)
    if task_file:
        try:
            data = yaml.safe_load(task_file.read_text())
            now = datetime.now(timezone.utc)
            data["status"] = "input-required"
            data.setdefault("history", []).append(
                {
                    "timestamp": now.isoformat(),
                    "status": "input-required",
                    "actor": "temporal-worker",
                    "note": (
                        f"BuildPipelineWorkflow blocked on {len(blocks)} security finding(s) "
                        f"for '{build_name}'. ntfy sent. Approve task to resume."
                    ),
                }
            )
            task_file.write_text(
                yaml.dump(data, default_flow_style=False, allow_unicode=True)
            )
            activity.logger.info(
                f"Updated task {task_id[:8]} to input-required ({len(blocks)} blocks)"
            )
        except Exception as exc:
            activity.logger.warning(f"Could not update task status (non-fatal): {exc}")
    else:
        activity.logger.warning(
            f"Task {task_id[:8]} not found in queue — could not set input-required"
        )


# ─── Activity 7: wait_for_block_resolution ───────────────────────────────────

@activity.defn
async def wait_for_block_resolution(build_name: str, task_id: str) -> None:
    """
    Poll the originating task until its status transitions from input-required → approved.
    Heartbeats every 5 minutes so Temporal knows the activity is alive.
    Schedule-to-close timeout of 7 days is set in the workflow.
    """
    activity.logger.info(
        f"Waiting for block resolution on task {task_id[:8]} (build: {build_name})"
    )
    while True:
        task_file = _find_task_file(task_id)
        if task_file:
            try:
                data = yaml.safe_load(task_file.read_text())
                status = data.get("status", "")
                if status == "approved":
                    activity.logger.info(
                        f"Task {task_id[:8]} approved — blocks resolved, resuming pipeline"
                    )
                    return
                activity.logger.info(
                    f"Task {task_id[:8]} status={status!r}, still waiting..."
                )
            except Exception as exc:
                activity.logger.warning(f"Error reading task file (will retry): {exc}")
        else:
            activity.logger.warning(
                f"Task {task_id[:8]} not found — still waiting for it to appear"
            )

        # Heartbeat so Temporal knows we're alive
        activity.heartbeat(
            {"build_name": build_name, "task_id": task_id, "checked_at": datetime.now(timezone.utc).isoformat()}
        )
        await asyncio.sleep(300)  # 5-minute poll interval


# ─── Activity 8: close_build ─────────────────────────────────────────────────

@activity.defn
async def close_build(build_name: str, target_agent: str) -> BuildPhaseResult:
    """
    Dispatch a build-close-out task to the build agent.
    Uses task_token pattern — completed externally with the closeout artifact path
    in the output field (e.g. temporal-complete $TOKEN success /path/to/closeout/).
    """
    info = activity.info()
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    task_token_b64 = base64.b64encode(info.task_token).decode()

    task = _build_agent_task(
        task_id=task_id,
        target_agent=target_agent,
        task_type="build_closeout",
        summary=f"Close out build '{build_name}'",
        payload={
            "build_name": build_name,
            "instruction": (
                f"Run the build-close-out skill for '{build_name}'. "
                "After close-out is complete and the closeout artifact is written, call:\n"
                "python3 ~/repos/personal/helm-temporal-worker/complete_activity.py "
                "$TASK_TOKEN success <closeout_artifact_path>\n\n"
                "Pass the absolute path to the closeout artifact directory or file as the "
                "third argument — it will be recorded in the workflow summary."
            ),
        },
        task_token_b64=task_token_b64,
        now=now,
    )
    _write_task(task)
    activity.logger.info(
        f"Dispatched close-out task {task_id[:8]} for '{build_name}' to {target_agent}"
    )
    activity.raise_complete_async()


# ─── Activity 9: summarize_workflow ──────────────────────────────────────────

@activity.defn
async def summarize_workflow(
    workflow_id: str,
    build_name: str,
    started_at: str,
    completed_at: str,
    phases_completed: List[str],
    blocks_hit: int,
    flags_applied: int,
    plan_path: str,
    build_report_path: str,
) -> str:
    """
    Write a YAML workflow summary to the agent-activity repo.
    Returns the path to the written file.
    """
    # Derive YYYY-MM from started_at (ISO string from workflow.now())
    try:
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        month_dir = dt.strftime("%Y-%m")
    except Exception:
        month_dir = datetime.now(timezone.utc).strftime("%Y-%m")

    summary_dir = ACTIVITY_SUMMARY_DIR / month_dir
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / f"{workflow_id}.yml"

    outcome = "success" if blocks_hit == 0 else "partial"

    summary = {
        "workflow_id": workflow_id,
        "build_name": build_name,
        "started": started_at,
        "completed": completed_at,
        "phases_completed": phases_completed,
        "blocks_hit": blocks_hit,
        "flags_applied": flags_applied,
        "outcome": outcome,
        "plan_path": plan_path,
        "build_report_path": build_report_path,
    }
    summary_path.write_text(yaml.dump(summary, default_flow_style=False, allow_unicode=True))

    activity.logger.info(f"Workflow summary written to {summary_path}")
    return str(summary_path)
