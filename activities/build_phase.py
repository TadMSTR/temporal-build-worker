import base64
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path

import structlog
from temporalio import activity

from models import BuildPhaseInput, BuildPhaseResult

log = structlog.get_logger(__name__)

TASK_QUEUE_DIR = Path.home() / ".claude" / "task-queue"


@activity.defn
async def execute_build_phase(input: BuildPhaseInput) -> BuildPhaseResult:
    info = activity.info()
    alog = log.bind(
        workflow_id=info.workflow_id,
        activity=info.activity_type,
        phase=input.phase_number,
        plan=input.plan_name,
    )
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")

    # Encode task token — Claude Code uses this to signal completion back to Temporal
    task_token_b64 = base64.b64encode(info.task_token).decode()

    task = {
        "id": task_id,
        "created": now.isoformat(),
        "source_agent": "temporal-worker",
        "target_agent": input.agent_type,
        "task_type": "build_phase",
        "risk_level": "low",
        "requires_approval": False,
        "status": "submitted",
        "summary": f"Build phase {input.phase_number}: {input.description}",
        "ttl_days": 7,
        "payload": {
            "description": input.description,
            "plan_name": input.plan_name,
            "phase_number": input.phase_number,
            "context_refs": input.context_refs,
            "workflow_id": input.workflow_id,
            "task_token": task_token_b64,
        },
        "result": {
            "output": None,
            "completed_by": None,
            "completed_at": None,
        },
        "history": [
            {
                "timestamp": now.isoformat(),
                "status": "submitted",
                "actor": "temporal-worker",
                "note": f"Phase {input.phase_number} dispatched by BuildPlanWorkflow",
            }
        ],
    }

    # Atomic write — same pattern as all other task queue producers
    tmp = TASK_QUEUE_DIR / f"{timestamp}-{task_id[:8]}.yml.tmp"
    target = TASK_QUEUE_DIR / f"{timestamp}-{task_id[:8]}.yml"
    tmp.write_text(yaml.dump(task, default_flow_style=False, allow_unicode=True))
    tmp.rename(target)

    alog.info("phase_dispatched", agent=input.agent_type, task_id=task_id[:8])

    # Signal async completion — activity will be externally completed by
    # Claude Code running complete_activity.py after the phase closes out.
    # Temporal marks this activity as pending-external and waits.
    activity.raise_complete_async()
