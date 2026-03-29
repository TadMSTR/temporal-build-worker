from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from activities.build_phase import execute_build_phase
    from models import BuildPlanInput, BuildPhaseInput, BuildPhaseResult, BuildPlanResult


@workflow.defn
class BuildPlanWorkflow:
    @workflow.run
    async def run(self, input: BuildPlanInput) -> BuildPlanResult:
        wf_id = workflow.info().workflow_id

        for phase in input.phases:
            result: BuildPhaseResult = await workflow.execute_activity(
                execute_build_phase,
                BuildPhaseInput(
                    plan_name=input.plan_name,
                    phase_number=phase.number,
                    agent_type=phase.agent_type,
                    description=phase.description,
                    context_refs=phase.context_refs,
                    workflow_id=wf_id,
                ),
                start_to_close_timeout=timedelta(hours=24),
                retry_policy=RetryPolicy(
                    maximum_attempts=2,
                    non_retryable_error_types=["PhaseFailedError"],
                ),
            )
            if result.status != "success":
                raise ApplicationError(
                    f"Phase {phase.number} failed: {result.output}",
                    type="PhaseFailedError",
                )

        return BuildPlanResult(
            status="complete",
            phases_run=len(input.phases),
        )
