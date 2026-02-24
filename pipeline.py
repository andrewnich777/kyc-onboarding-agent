"""
KYC Pipeline Orchestrator

Runs the 5-stage KYC pipeline:
1. Intake & Classification (deterministic)
2. Investigation (AI agents + deterministic utilities)
3. Synthesis & Proto-Reports (Opus AI)
4. Conversational Review (pause for human)
5. Final Reports (generators + PDF)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from rich.console import Console

from logger import get_logger
from config import get_config

logger = get_logger(__name__)

from models import (
    IndividualClient, BusinessClient, ClientType,
    InvestigationPlan, InvestigationResults,
    KYCSynthesisOutput, KYCOutput, OnboardingDecision,
    ReviewSession,
)
from agents import (
    IndividualSanctionsAgent, PEPDetectionAgent, IndividualAdverseMediaAgent,
    EntityVerificationAgent, EntitySanctionsAgent, BusinessAdverseMediaAgent,
    JurisdictionRiskAgent, KYCSynthesisAgent,
)
from utilities.investigation_planner import build_investigation_plan
from pipeline_checkpoint import CheckpointMixin
from pipeline_investigation import InvestigationMixin
from pipeline_synthesis import SynthesisMixin
from pipeline_reports import ReportsMixin


console = Console(force_terminal=True, legacy_windows=True)


class KYCPipeline(CheckpointMixin, InvestigationMixin, SynthesisMixin, ReportsMixin):
    """Orchestrates the full KYC pipeline for client onboarding."""

    def __init__(self, output_dir: str = "results", verbose: bool = True, resume: bool = False):
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.resume = resume
        self.checkpoint = {}
        self.checkpoint_path = None

        # Initialize AI agents
        self.individual_sanctions_agent = IndividualSanctionsAgent()
        self.pep_detection_agent = PEPDetectionAgent()
        self.individual_adverse_media_agent = IndividualAdverseMediaAgent()
        self.entity_verification_agent = EntityVerificationAgent()
        self.entity_sanctions_agent = EntitySanctionsAgent()
        self.business_adverse_media_agent = BusinessAdverseMediaAgent()
        self.jurisdiction_risk_agent = JurisdictionRiskAgent()
        self.synthesis_agent = KYCSynthesisAgent()

        # Evidence store — central truth for all findings
        self.evidence_store: list[dict] = []

    def log(self, message: str, style: str = ""):
        """Log a message if verbose mode is on."""
        if self.verbose:
            console.print(message, style=style)

    # =========================================================================
    # Main Pipeline
    # =========================================================================

    async def run(self, client_data: dict) -> KYCOutput:
        """Run the full KYC pipeline for a client."""
        start_time = datetime.now()

        # Parse client type
        client_type = client_data.get("client_type", "individual")
        if client_type == "individual":
            client = IndividualClient(**client_data)
        else:
            client = BusinessClient(**client_data)

        # Stage 1: Intake & Classification
        self.log("\n[bold blue]Stage 1: Intake & Classification[/bold blue]")
        plan = await self._run_intake(client)
        client_id = plan.client_id

        # Load checkpoint
        self.checkpoint = self._load_checkpoint(client_id)
        completed_stage = self.checkpoint.get("completed_stage", 0)

        # Save Stage 1
        self._save_stage_results(client_id, "01_intake", {
            "classification": plan.preliminary_risk.model_dump(),
            "investigation_plan": plan.model_dump(),
        })

        # Save client data to checkpoint for finalize() recovery
        self.checkpoint["client_data"] = client_data

        self.log(f"  Client ID: {client_id}")
        self.log(f"  Risk Level: {plan.preliminary_risk.risk_level.value} ({plan.preliminary_risk.total_score} pts)")
        self.log(f"  Regulations: {', '.join(plan.applicable_regulations)}")
        self.log(f"  Agents: {', '.join(plan.agents_to_run)}")
        if plan.ubo_cascade_needed:
            self.log(f"  UBO Cascade: {', '.join(plan.ubo_names)}")

        # Stage 2: Investigation
        if completed_stage < 2:
            self.log("\n[bold blue]Stage 2: Investigation[/bold blue]")
            investigation = await self._run_investigation(client, plan)
            self.checkpoint["completed_stage"] = 2
            self.checkpoint["investigation"] = self._serialize_investigation(investigation)
            self._save_checkpoint(client_id, self.checkpoint)
        else:
            self.log("\n[bold blue]Stage 2: Investigation[/bold blue] [green](cached)[/green]")
            investigation = self._deserialize_investigation(self.checkpoint.get("investigation", {}))

        # Save evidence store
        self._save_evidence_store(client_id)

        # Stage 3: Synthesis
        if completed_stage < 3:
            self.log("\n[bold blue]Stage 3: Synthesis & Proto-Reports[/bold blue]")
            synthesis = await self._run_synthesis(client, plan, investigation)
            self.checkpoint["completed_stage"] = 3
            self.checkpoint["synthesis"] = synthesis.model_dump() if synthesis else None
            self._save_checkpoint(client_id, self.checkpoint)
        else:
            self.log("\n[bold blue]Stage 3: Synthesis[/bold blue] [green](cached)[/green]")
            synth_data = self.checkpoint.get("synthesis")
            synthesis = KYCSynthesisOutput(**synth_data) if synth_data else None

        # Save Stage 3 outputs
        self._save_stage3_outputs(client_id, synthesis, plan)

        # Display decision points requiring officer review
        self._display_decision_points(synthesis)

        # Stage 4: Pause for Review
        self.log("\n[bold yellow]Stage 4: Review[/bold yellow]")
        self.log("  Proto-reports generated. Review and ask questions.")
        self.log(f"  To finalize: python main.py --finalize results/{client_id}")

        # Initialize review session
        review_session = ReviewSession(client_id=client_id)
        self._save_review_session(client_id, review_session)

        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()

        # Build output
        output = KYCOutput(
            client_id=client_id,
            client_type=ClientType(client_type),
            client_data=client_data,
            intake_classification=plan,
            investigation_results=investigation,
            synthesis=synthesis,
            review_session=review_session,
            final_decision=synthesis.recommended_decision if synthesis else None,
            generated_at=datetime.now(),
            duration_seconds=duration,
        )

        return output

    async def finalize(self, results_dir: str) -> KYCOutput:
        """Finalize a paused review session and generate final reports."""
        results_path = Path(results_dir)
        client_id = results_path.name

        self.log(f"\n[bold blue]Stage 5: Final Reports[/bold blue]")
        self.log(f"  Finalizing: {client_id}")

        # Load checkpoint
        cp_path = results_path / "checkpoint.json"
        if not cp_path.exists():
            raise ValueError(f"No checkpoint found at {results_dir}")

        checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))

        # Load review session
        review_path = results_path / "04_review" / "review_session.json"
        review_session = None
        if review_path.exists():
            review_data = json.loads(review_path.read_text(encoding="utf-8"))
            review_session = ReviewSession(**review_data)
            review_session.finalized = True
            review_session.finalized_at = datetime.now()

        # Load synthesis
        synth_data = checkpoint.get("synthesis")
        synthesis = KYCSynthesisOutput(**synth_data) if synth_data else None

        # Load investigation plan
        intake_path = results_path / "01_intake" / "investigation_plan.json"
        plan_data = json.loads(intake_path.read_text(encoding="utf-8")) if intake_path.exists() else {}
        plan = InvestigationPlan(**plan_data) if plan_data else None

        # Load client data from checkpoint
        client_data = checkpoint.get("client_data", {})

        # Deserialize investigation results from checkpoint
        inv_data = checkpoint.get("investigation", {})
        investigation = self._deserialize_investigation(inv_data) if inv_data else InvestigationResults()

        # Check for unresolved decision points
        if synthesis and synthesis.decision_points:
            unresolved = [
                dp for dp in synthesis.decision_points
                if dp.officer_selection is None
            ]
            if unresolved:
                for dp in unresolved:
                    self.log(f"  [bold yellow]Unresolved decision point: {dp.title}[/bold yellow]")
                self.log(f"  [yellow]{len(unresolved)} decision point(s) without officer selection — "
                         f"recording as pending in audit trail[/yellow]")

        # Apply deterministic recommendation engine as safety net
        final_decision = synthesis.recommended_decision if synthesis else None
        if plan and synthesis:
            from generators.recommendation_engine import recommend_decision
            risk_assessment = synthesis.revised_risk_assessment or plan.preliminary_risk
            decision, reasoning, conditions = recommend_decision(risk_assessment, investigation)
            # Deterministic rules override AI for hard blocks (sanctions = DECLINE)
            if decision == OnboardingDecision.DECLINE:
                final_decision = OnboardingDecision.DECLINE
                self.log(f"  [bold red]Deterministic override: DECLINE ({reasoning})[/bold red]")

        # Generate final reports
        await self._run_final_reports(client_id, synthesis, plan, review_session, investigation)

        # Save finalized review session
        if review_session:
            self._save_review_session(client_id, review_session)

        duration = 0.0
        output = KYCOutput(
            client_id=client_id,
            client_type=ClientType(client_data.get("client_type", "individual")),
            client_data=client_data,
            intake_classification=plan or InvestigationPlan(client_type=ClientType.INDIVIDUAL, client_id=client_id),
            investigation_results=investigation,
            synthesis=synthesis,
            review_session=review_session,
            final_decision=final_decision,
            generated_at=datetime.now(),
            duration_seconds=duration,
        )

        self.log(f"\n[bold green]Finalization complete[/bold green]")
        return output

    # =========================================================================
    # Stage 1: Intake & Classification
    # =========================================================================

    async def _run_intake(self, client) -> InvestigationPlan:
        """Stage 1: Classify client and build investigation plan."""
        plan = build_investigation_plan(client)
        return plan
