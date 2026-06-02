"""
BuildPipelineWorkflow — durable Temporal workflow for the full build pipeline.

Pipeline stages:
  1. prefab_scaffolding   — pre-create stub files via claudebox build-plan-prefab
  2. implement_build      — run the build plan on the target agent
  3. request_security_audit — write audit request, dispatch to security agent
  4. process_triage_output  — read security triage YAML, classify findings
  5. apply_flag_fixes     — apply auto-fixable findings on target agent (if any)
  6. notify_blocks        — ntfy Ted + set task to input-required (if any blocks)
  7. wait_for_block_resolution — poll until task → approved (if blocks hit)
  8. close_build          — run build-close-out on target agent
  9. summarize_workflow   — write YAML summary to agent-activity repo

Determinism contract (Temporal replays workflow code on worker restart):
  - Use workflow.now() and workflow.uuid4() — NOT datetime.now() / uuid.uuid4()
  - No I/O, no randomness, no non-deterministic calls in the workflow function
  - All non-deterministic logic lives in activities
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.build_pipeline_activities import (
        apply_flag_fixes,
        close_build,
        implement_build,
        notify_blocks,
        prefab_scaffolding,
        process_triage_output,
        request_security_audit,
        summarize_workflow,
        wait_for_block_resolution,
    )
    from models import (
        BuildPhaseResult,
        BuildPipelineInput,
        BuildPipelineResult,
        TriageOutput,
    )


@workflow.defn
class BuildPipelineWorkflow:
    @workflow.run
    async def run(self, input: BuildPipelineInput) -> BuildPipelineResult:
        wf_id = workflow.info().workflow_id
        # workflow.now() is deterministic — safe in workflow code
        started_at = workflow.now().isoformat()

        # ── 1. Prefab scaffolding ─────────────────────────────────────────────
        await workflow.execute_activity(
            prefab_scaffolding,
            args=[input.build_name, input.plan_path],
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
                non_retryable_error_types=["PhaseFailedError"],
            ),
        )

        # ── 2. Implement build ────────────────────────────────────────────────
        await workflow.execute_activity(
            implement_build,
            args=[input.build_name, input.task_id, input.target_agent],
            start_to_close_timeout=timedelta(hours=4),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
                non_retryable_error_types=["PhaseFailedError"],
            ),
        )

        # ── 3. Request security audit ─────────────────────────────────────────
        await workflow.execute_activity(
            request_security_audit,
            args=[input.build_name, input.plan_path],
            start_to_close_timeout=timedelta(hours=4),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
                non_retryable_error_types=["PhaseFailedError"],
            ),
        )

        # ── 4. Process triage output ──────────────────────────────────────────
        # Retry with backoff — triage-output.yml may not be present immediately
        triage: TriageOutput = await workflow.execute_activity(
            process_triage_output,
            args=[input.build_name],
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(
                maximum_attempts=5,
                initial_interval=timedelta(minutes=2),
                maximum_interval=timedelta(minutes=15),
            ),
        )

        phases_completed = ["prefab", "implement", "audit", "triage"]
        blocks_hit = 0
        flags_applied = 0

        # ── 5. Apply flag fixes (if any) ──────────────────────────────────────
        if triage.flags:
            await workflow.execute_activity(
                apply_flag_fixes,
                args=[input.build_name, triage.flags, input.target_agent],
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                    non_retryable_error_types=["PhaseFailedError"],
                ),
            )
            flags_applied = len(triage.flags)
            phases_completed.append("fixes")

        # ── 6 & 7. Notify blocks + wait for resolution (if any) ──────────────
        if triage.blocks:
            blocks_hit = len(triage.blocks)
            await workflow.execute_activity(
                notify_blocks,
                args=[input.build_name, input.task_id, triage.blocks],
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # 7. Poll with heartbeat — schedule_to_close covers the 7-day wait
            await workflow.execute_activity(
                wait_for_block_resolution,
                args=[input.build_name, input.task_id],
                schedule_to_close_timeout=timedelta(days=7),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

        # ── 8. Close build ────────────────────────────────────────────────────
        close_result: BuildPhaseResult = await workflow.execute_activity(
            close_build,
            args=[input.build_name, input.target_agent],
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
                non_retryable_error_types=["PhaseFailedError"],
            ),
        )
        # The build agent passes the closeout artifact path as the output field
        closeout_path = close_result.output if close_result.output else ""
        phases_completed.append("close")

        completed_at = workflow.now().isoformat()

        # ── 9. Summarize workflow ─────────────────────────────────────────────
        summary_path: str = await workflow.execute_activity(
            summarize_workflow,
            args=[
                wf_id,
                input.build_name,
                started_at,
                completed_at,
                phases_completed,
                blocks_hit,
                flags_applied,
                input.plan_path,
                closeout_path,
            ],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return BuildPipelineResult(
            status="complete",
            workflow_id=wf_id,
            summary_path=summary_path,
        )
