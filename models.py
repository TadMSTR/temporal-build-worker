from dataclasses import dataclass, field
from typing import List


@dataclass
class PhaseSpec:
    number: int
    agent_type: str
    description: str
    context_refs: List[str] = field(default_factory=list)


@dataclass
class BuildPlanInput:
    plan_name: str
    phases: List[PhaseSpec]


@dataclass
class BuildPhaseInput:
    plan_name: str
    phase_number: int
    agent_type: str
    description: str
    context_refs: List[str] = field(default_factory=list)
    workflow_id: str = ""


@dataclass
class BuildPhaseResult:
    status: str   # "success" | "failed"
    output: str = ""


@dataclass
class BuildPlanResult:
    status: str
    phases_run: int


# --- BuildPipelineWorkflow models ---

@dataclass
class BuildPipelineInput:
    build_name: str       # e.g. "automation-infrastructure"
    plan_path: str        # e.g. "~/.claude/comms/artifacts/build-plans/automation-infrastructure/plan.md"
    task_id: str          # ID of the task-queue entry that triggered this workflow
    target_agent: str     # e.g. "helm-build", "claudebox", "dev"


@dataclass
class TriageOutput:
    blocks: List[str] = field(default_factory=list)   # issues requiring Ted's decision
    flags: List[str] = field(default_factory=list)    # auto-fixable issues
    info: List[str] = field(default_factory=list)     # informational findings


@dataclass
class BuildPipelineResult:
    status: str           # "complete" | "failed"
    workflow_id: str
    summary_path: str     # path to the agent-activity summary YAML
