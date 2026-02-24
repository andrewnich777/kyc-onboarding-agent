"""
Synthesis mixin for KYC Pipeline.

Handles Stage 3: Cross-referencing findings and producing synthesis output.
"""

from typing import Optional

from logger import get_logger
from models import (
    IndividualClient, BusinessClient,
    InvestigationPlan, InvestigationResults,
    KYCSynthesisOutput, OnboardingDecision,
)
from utilities.risk_scoring import revise_risk_score

logger = get_logger(__name__)


class SynthesisMixin:
    """Stage 3 synthesis execution."""

    async def _run_synthesis(self, client, plan: InvestigationPlan,
                             investigation: InvestigationResults) -> Optional[KYCSynthesisOutput]:
        """Stage 3: Synthesize all findings."""
        try:
            # Build client summary
            if isinstance(client, IndividualClient):
                client_summary = (
                    f"Individual: {client.full_name}\n"
                    f"Citizenship: {client.citizenship}\n"
                    f"Residence: {client.country_of_residence}\n"
                    f"PEP Self-Declaration: {client.pep_self_declaration}\n"
                    f"US Person: {client.us_person}\n"
                )
            else:
                ubo_lines = [f"  - {ubo.full_name} ({ubo.ownership_percentage}%)" for ubo in client.beneficial_owners]
                client_summary = (
                    f"Business: {client.legal_name}\n"
                    f"Industry: {client.industry}\n"
                    f"Countries: {', '.join(client.countries_of_operation)}\n"
                    f"US Nexus: {client.us_nexus}\n"
                    f"Beneficial Owners:\n" + "\n".join(ubo_lines) + "\n"
                )

            # Revise risk score with UBO cascade results (business clients)
            revised_risk = plan.preliminary_risk
            if isinstance(client, BusinessClient) and investigation.ubo_screening:
                ubo_scores = {}
                for ubo_name, ubo_data in investigation.ubo_screening.items():
                    # Calculate individual risk score for each UBO
                    score = 0
                    sanctions = ubo_data.get("sanctions", {})
                    if sanctions and sanctions.get("disposition") != "CLEAR":
                        score += 30
                    pep = ubo_data.get("pep", {})
                    if pep and pep.get("detected_level", "NOT_PEP") != "NOT_PEP":
                        score += 25
                    adverse = ubo_data.get("adverse_media", {})
                    if adverse and adverse.get("overall_level", "CLEAR") != "CLEAR":
                        score += 15
                    ubo_scores[ubo_name] = score

                synthesis_factors = []
                revised_risk = revise_risk_score(
                    plan.preliminary_risk,
                    ubo_scores=ubo_scores,
                    synthesis_factors=synthesis_factors,
                )

            # Run synthesis agent
            synthesis = await self.synthesis_agent.synthesize(
                evidence_store=self.evidence_store,
                risk_assessment=revised_risk.model_dump(),
                client_summary=client_summary,
            )

            # Update risk assessment on synthesis output
            synthesis.revised_risk_assessment = revised_risk

            return synthesis

        except Exception as e:
            self.log(f"  [red]Synthesis error: {e}[/red]")
            logger.exception("Synthesis failed")
            return KYCSynthesisOutput(
                recommended_decision=OnboardingDecision.ESCALATE,
                decision_reasoning=f"Synthesis failed: {e} — escalating for manual review",
                items_requiring_review=["All findings require manual review"],
                senior_management_approval_needed=True,
            )
