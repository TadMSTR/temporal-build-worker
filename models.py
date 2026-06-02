from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, Field


# ─── BuildPlanWorkflow models (dataclass — serialized by Temporal SDK) ────────
#
# These remain @dataclass because Temporal's Python SDK serializes workflow
# inputs/outputs via dataclasses-json and expects __dataclass_fields__.

@dataclass
class PhaseSpec:
    number: int
    agent_type: str
    description: str
    context_refs: list[str] = field(default_factory=list)


@dataclass
class BuildPlanInput:
    plan_name: str
    phases: list[PhaseSpec]


@dataclass
class BuildPhaseInput:
    plan_name: str
    phase_number: int
    agent_type: str
    description: str
    context_refs: list[str] = field(default_factory=list)
    workflow_id: str = ""


@dataclass
class BuildPhaseResult:
    status: str   # "success" | "failed"
    output: str = ""


@dataclass
class BuildPlanResult:
    status: str
    phases_run: int


# ─── BuildPipelineWorkflow models (Pydantic — validated at workflow entry) ────

class BuildPipelineInput(BaseModel):
    build_name: Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9-]*$')]
    plan_path: str
    task_id: str
    target_agent: str


class TriageOutput(BaseModel):
    blocks: list[str] = []
    flags: list[str] = []
    info: list[str] = []


class BuildPipelineResult(BaseModel):
    status: str           # "complete" | "failed"
    workflow_id: str
    summary_path: str     # path to the agent-activity summary YAML
