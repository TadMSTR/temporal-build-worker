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
