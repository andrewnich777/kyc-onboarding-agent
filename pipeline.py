"""
KYC Pipeline Orchestrator

Runs the 5-stage KYC pipeline:
1. Intake & Classification (deterministic)
2. Investigation (AI agents + deterministic utilities)
3. Synthesis & Proto-Reports (Opus AI)
4. Conversational Review (pause for human)
5. Final Reports (generators + PDF)
"""

import asyncio
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from logger import get_logger
from config import get_config

logger = get_logger(__name__)

from models import (
    IndividualClient, BusinessClient, ClientType,
    InvestigationPlan, InvestigationResults, RiskAssessment, RiskLevel,
    KYCSynthesisOutput, KYCOutput, OnboardingDecision,
    ReviewSession, ReviewAction, EvidenceRecord,
    SanctionsResult, PEPClassification, AdverseMediaResult,
    EntityVerification, JurisdictionRiskResult,
)
from agents import (
    IndividualSanctionsAgent, PEPDetectionAgent, IndividualAdverseMediaAgent,
    EntityVerificationAgent, EntitySanctionsAgent, BusinessAdverseMediaAgent,
    JurisdictionRiskAgent, KYCSynthesisAgent,
)
from utilities.investigation_planner import build_investigation_plan
from utilities.risk_scoring import revise_risk_score
from models import RiskFactor


console = Console(force_terminal=True, legacy_windows=True)


class KYCPipeline:
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
    # Checkpoint System
    # =========================================================================

    def _get_checkpoint_path(self, client_id: str) -> Path:
        return self.output_dir / client_id / "checkpoint.json"

    def _load_checkpoint(self, client_id: str) -> dict:
        if not self.resume:
            return {}
        cp_path = self._get_checkpoint_path(client_id)
        if cp_path.exists():
            try:
                data = json.loads(cp_path.read_text(encoding="utf-8"))
                self.log(f"  [green]Loaded checkpoint (stage {data.get('completed_stage', 0)})[/green]")
                return data
            except Exception as e:
                self.log(f"  [yellow]Could not load checkpoint: {e}[/yellow]")
        return {}

    def _save_checkpoint(self, client_id: str, data: dict):
        cp_path = self._get_checkpoint_path(client_id)
        cp_path.parent.mkdir(parents=True, exist_ok=True)
        cp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

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

    # =========================================================================
    # Stage 2: Investigation
    # =========================================================================

    async def _run_investigation(self, client, plan: InvestigationPlan) -> InvestigationResults:
        """Stage 2: Run AI agents and deterministic utilities."""
        results = InvestigationResults()

        # Run AI agents sequentially (no rate limit pauses — Claude Max)
        for agent_name in plan.agents_to_run:
            self.log(f"  Running {agent_name}...")
            try:
                result = await self._run_agent(agent_name, client, plan)
                self._store_agent_result(results, agent_name, result)
                self.log(f"  [green]{agent_name} complete[/green]")
            except Exception as e:
                self.log(f"  [red]{agent_name} error: {e}[/red]")
                logger.exception(f"Agent {agent_name} failed")

        # UBO cascade for business clients
        if plan.ubo_cascade_needed and isinstance(client, BusinessClient):
            self.log(f"\n  [bold cyan]UBO Cascade ({len(plan.ubo_names)} owners)[/bold cyan]")
            for ubo in client.beneficial_owners:
                self.log(f"  Screening UBO: {ubo.full_name} ({ubo.ownership_percentage}%)")
                ubo_results = await self._screen_ubo(ubo)
                results.ubo_screening[ubo.full_name] = ubo_results

        # Run deterministic utilities (pass partial results for EDD/compliance)
        self.log(f"\n  [bold cyan]Deterministic Utilities[/bold cyan]")
        for util_name in plan.utilities_to_run:
            self.log(f"  Running {util_name}...")
            try:
                result = await self._run_utility(util_name, client, plan, results)
                self._store_utility_result(results, util_name, result)
                self.log(f"  [green]{util_name} complete[/green]")
            except Exception as e:
                self.log(f"  [red]{util_name} error: {e}[/red]")
                logger.exception(f"Utility {util_name} failed")

        return results

    async def _run_agent(self, agent_name: str, client, plan: InvestigationPlan):
        """Dispatch to the correct agent."""
        if agent_name == "IndividualSanctions":
            return await self.individual_sanctions_agent.research(
                full_name=client.full_name,
                date_of_birth=getattr(client, 'date_of_birth', None),
                citizenship=getattr(client, 'citizenship', None),
            )
        elif agent_name == "PEPDetection":
            return await self.pep_detection_agent.research(
                full_name=client.full_name,
                citizenship=getattr(client, 'citizenship', None),
                pep_self_declaration=getattr(client, 'pep_self_declaration', False),
                pep_details=getattr(client, 'pep_details', None),
            )
        elif agent_name == "IndividualAdverseMedia":
            employer = None
            if hasattr(client, 'employment') and client.employment:
                employer = client.employment.employer
            return await self.individual_adverse_media_agent.research(
                full_name=client.full_name,
                employer=employer,
                citizenship=getattr(client, 'citizenship', None),
            )
        elif agent_name == "EntityVerification":
            declared_ubos = [
                {"full_name": ubo.full_name, "ownership_percentage": ubo.ownership_percentage}
                for ubo in client.beneficial_owners
            ] if hasattr(client, 'beneficial_owners') else None
            return await self.entity_verification_agent.research(
                legal_name=client.legal_name,
                jurisdiction=getattr(client, 'incorporation_jurisdiction', None),
                business_number=getattr(client, 'business_number', None),
                declared_ubos=declared_ubos,
            )
        elif agent_name == "EntitySanctions":
            ubo_dicts = [
                {"full_name": ubo.full_name, "ownership_percentage": ubo.ownership_percentage}
                for ubo in client.beneficial_owners
            ] if hasattr(client, 'beneficial_owners') else None
            return await self.entity_sanctions_agent.research(
                legal_name=client.legal_name,
                beneficial_owners=ubo_dicts,
                countries=getattr(client, 'countries_of_operation', None),
                us_nexus=getattr(client, 'us_nexus', False),
            )
        elif agent_name == "BusinessAdverseMedia":
            return await self.business_adverse_media_agent.research(
                legal_name=client.legal_name,
                industry=getattr(client, 'industry', None),
                countries=getattr(client, 'countries_of_operation', None),
            )
        elif agent_name == "JurisdictionRisk":
            jurisdictions = set()
            if isinstance(client, IndividualClient):
                if client.citizenship:
                    jurisdictions.add(client.citizenship)
                if client.country_of_residence:
                    jurisdictions.add(client.country_of_residence)
                if client.country_of_birth:
                    jurisdictions.add(client.country_of_birth)
                jurisdictions.update(client.tax_residencies)
            else:
                jurisdictions.update(client.countries_of_operation)
                if client.incorporation_jurisdiction:
                    jurisdictions.add(client.incorporation_jurisdiction)
                for ubo in client.beneficial_owners:
                    if ubo.citizenship:
                        jurisdictions.add(ubo.citizenship)
                    if ubo.country_of_birth:
                        jurisdictions.add(ubo.country_of_birth)
                    if ubo.country_of_residence:
                        jurisdictions.add(ubo.country_of_residence)
            # Remove None and Canada
            jurisdictions = [j for j in jurisdictions if j and j.lower() not in ("canada", "ca")]
            if not jurisdictions:
                jurisdictions = ["Canada"]  # At minimum assess Canada
            return await self.jurisdiction_risk_agent.research(list(jurisdictions))
        else:
            raise ValueError(f"Unknown agent: {agent_name}")

    async def _screen_ubo(self, ubo) -> dict:
        """Screen a single beneficial owner through individual pipeline."""
        ubo_results = {}

        try:
            sanctions = await self.individual_sanctions_agent.research(
                full_name=ubo.full_name,
                date_of_birth=ubo.date_of_birth,
                citizenship=ubo.citizenship,
                context=f"UBO ({ubo.ownership_percentage}% owner)",
            )
            ubo_results["sanctions"] = sanctions.model_dump() if sanctions else None
            # Add evidence to store
            if sanctions and sanctions.evidence_records:
                for er in sanctions.evidence_records:
                    er.entity_context = f"UBO ({ubo.ownership_percentage}% owner)"
                    self.evidence_store.append(er.model_dump())
        except Exception as e:
            logger.error(f"UBO sanctions screening failed for {ubo.full_name}: {e}")

        try:
            pep = await self.pep_detection_agent.research(
                full_name=ubo.full_name,
                citizenship=ubo.citizenship,
                pep_self_declaration=ubo.pep_self_declaration,
            )
            ubo_results["pep"] = pep.model_dump() if pep else None
            if pep and pep.evidence_records:
                for er in pep.evidence_records:
                    er.entity_context = f"UBO ({ubo.ownership_percentage}% owner)"
                    self.evidence_store.append(er.model_dump())
        except Exception as e:
            logger.error(f"UBO PEP detection failed for {ubo.full_name}: {e}")

        try:
            adverse = await self.individual_adverse_media_agent.research(
                full_name=ubo.full_name,
                citizenship=ubo.citizenship,
            )
            ubo_results["adverse_media"] = adverse.model_dump() if adverse else None
            if adverse and adverse.evidence_records:
                for er in adverse.evidence_records:
                    er.entity_context = f"UBO ({ubo.ownership_percentage}% owner)"
                    self.evidence_store.append(er.model_dump())
        except Exception as e:
            logger.error(f"UBO adverse media failed for {ubo.full_name}: {e}")

        return ubo_results

    async def _run_utility(self, util_name: str, client, plan: InvestigationPlan,
                           investigation: InvestigationResults = None):
        """Dispatch to the correct utility."""
        if util_name == "id_verification":
            from utilities.id_verification import assess_id_verification
            return assess_id_verification(client)
        elif util_name == "suitability":
            from utilities.suitability import assess_suitability
            return assess_suitability(client)
        elif util_name == "individual_fatca_crs":
            from utilities.individual_fatca_crs import classify_individual_fatca_crs
            return classify_individual_fatca_crs(client)
        elif util_name == "entity_fatca_crs":
            from utilities.entity_fatca_crs import classify_entity_fatca_crs
            return classify_entity_fatca_crs(client)
        elif util_name == "edd_requirements":
            from utilities.edd_requirements import assess_edd_requirements
            return assess_edd_requirements(client, plan.preliminary_risk, investigation)
        elif util_name == "compliance_actions":
            from utilities.compliance_actions import determine_compliance_actions
            return determine_compliance_actions(client, plan.preliminary_risk, investigation)
        elif util_name == "business_risk_assessment":
            from utilities.business_risk_assessment import assess_business_risk_factors
            return assess_business_risk_factors(client)
        elif util_name == "document_requirements":
            from utilities.document_requirements import consolidate_document_requirements
            return consolidate_document_requirements(client, plan, investigation)
        else:
            raise ValueError(f"Unknown utility: {util_name}")

    def _store_agent_result(self, results: InvestigationResults, agent_name: str, result):
        """Store agent result in the appropriate field and update evidence store."""
        if agent_name == "IndividualSanctions":
            results.individual_sanctions = result
        elif agent_name == "PEPDetection":
            results.pep_classification = result
        elif agent_name == "IndividualAdverseMedia":
            results.individual_adverse_media = result
        elif agent_name == "EntityVerification":
            results.entity_verification = result
        elif agent_name == "EntitySanctions":
            results.entity_sanctions = result
        elif agent_name == "BusinessAdverseMedia":
            results.business_adverse_media = result
        elif agent_name == "JurisdictionRisk":
            results.jurisdiction_risk = result

        # Add evidence records to central store
        if hasattr(result, 'evidence_records'):
            for er in result.evidence_records:
                self.evidence_store.append(er.model_dump() if hasattr(er, 'model_dump') else er)

    def _store_utility_result(self, results: InvestigationResults, util_name: str, result: dict):
        """Store utility result and update evidence store."""
        if util_name == "id_verification":
            results.id_verification = result
        elif util_name == "suitability":
            results.suitability_assessment = result
        elif util_name in ("individual_fatca_crs", "entity_fatca_crs"):
            results.fatca_crs = result
        elif util_name == "edd_requirements":
            results.edd_requirements = result
        elif util_name == "compliance_actions":
            results.compliance_actions = result
        elif util_name == "business_risk_assessment":
            results.business_risk_assessment = result
        elif util_name == "document_requirements":
            results.document_requirements = result

        # Add evidence records from utility (utilities use "evidence" key)
        if isinstance(result, dict):
            evidence = result.get("evidence_records") or result.get("evidence") or []
            self.evidence_store.extend(evidence)

    # =========================================================================
    # Stage 3: Synthesis
    # =========================================================================

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

    # =========================================================================
    # Stage 5: Final Reports
    # =========================================================================

    async def _run_final_reports(self, client_id: str, synthesis, plan, review_session,
                                investigation: InvestigationResults = None):
        """Stage 5: Generate final 4 department-targeted briefs + PDFs."""
        output_dir = self.output_dir / client_id / "05_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load evidence store
        es_path = self.output_dir / client_id / "02_investigation" / "evidence_store.json"
        evidence_store = []
        if es_path.exists():
            evidence_store = json.loads(es_path.read_text(encoding="utf-8"))

        risk_level = None
        if plan and plan.preliminary_risk:
            risk_level = plan.preliminary_risk.risk_level.value

        # 1. AML Operations Brief
        try:
            from generators.aml_operations_brief import generate_aml_operations_brief
            brief = generate_aml_operations_brief(
                client_id=client_id,
                synthesis=synthesis,
                plan=plan,
                evidence_store=evidence_store,
                review_session=review_session,
                investigation=investigation,
            )
            (output_dir / "aml_operations_brief.md").write_text(brief, encoding="utf-8")
            self.log(f"  [green]AML operations brief generated[/green]")
        except Exception as e:
            self.log(f"  [red]AML operations brief error: {e}[/red]")
            logger.exception("AML operations brief generation failed")

        # 2. Risk Assessment Brief
        try:
            from generators.risk_assessment_brief import generate_risk_assessment_brief
            brief = generate_risk_assessment_brief(
                client_id=client_id,
                synthesis=synthesis,
                plan=plan,
                investigation=investigation,
            )
            (output_dir / "risk_assessment_brief.md").write_text(brief, encoding="utf-8")
            self.log(f"  [green]Risk assessment brief generated[/green]")
        except Exception as e:
            self.log(f"  [red]Risk assessment brief error: {e}[/red]")
            logger.exception("Risk assessment brief generation failed")

        # 3. Regulatory Actions Brief
        try:
            from generators.regulatory_actions_brief import generate_regulatory_actions_brief
            brief = generate_regulatory_actions_brief(
                client_id=client_id,
                synthesis=synthesis,
                plan=plan,
                investigation=investigation,
            )
            (output_dir / "regulatory_actions_brief.md").write_text(brief, encoding="utf-8")
            self.log(f"  [green]Regulatory actions brief generated[/green]")
        except Exception as e:
            self.log(f"  [red]Regulatory actions brief error: {e}[/red]")
            logger.exception("Regulatory actions brief generation failed")

        # 4. Onboarding Decision Brief
        try:
            from generators.onboarding_summary import generate_onboarding_summary
            brief = generate_onboarding_summary(
                client_id=client_id,
                synthesis=synthesis,
                plan=plan,
                investigation=investigation,
            )
            (output_dir / "onboarding_decision_brief.md").write_text(brief, encoding="utf-8")
            self.log(f"  [green]Onboarding decision brief generated[/green]")
        except Exception as e:
            self.log(f"  [red]Onboarding decision brief error: {e}[/red]")
            logger.exception("Onboarding decision brief generation failed")

        # Generate PDFs for all 4 briefs
        try:
            from generators.pdf_generator import generate_kyc_pdf
            for doc_name in [
                "aml_operations_brief",
                "risk_assessment_brief",
                "regulatory_actions_brief",
                "onboarding_decision_brief",
            ]:
                md_path = output_dir / f"{doc_name}.md"
                if md_path.exists():
                    md_content = md_path.read_text(encoding="utf-8")
                    pdf_path = output_dir / f"{doc_name}.pdf"
                    generate_kyc_pdf(md_content, str(pdf_path), doc_name, risk_level=risk_level)
                    self.log(f"  [green]PDF generated: {doc_name}.pdf[/green]")
        except Exception as e:
            self.log(f"  [yellow]PDF generation skipped: {e}[/yellow]")

    # =========================================================================
    # File I/O Helpers
    # =========================================================================

    def _save_stage_results(self, client_id: str, stage_dir: str, data: dict):
        """Save stage results to appropriate directory."""
        stage_path = self.output_dir / client_id / stage_dir
        stage_path.mkdir(parents=True, exist_ok=True)
        for filename, content in data.items():
            file_path = stage_path / f"{filename}.json"
            file_path.write_text(
                json.dumps(content, indent=2, default=str),
                encoding="utf-8"
            )

    def _save_evidence_store(self, client_id: str):
        """Save the central evidence store."""
        inv_path = self.output_dir / client_id / "02_investigation"
        inv_path.mkdir(parents=True, exist_ok=True)
        (inv_path / "evidence_store.json").write_text(
            json.dumps(self.evidence_store, indent=2, default=str),
            encoding="utf-8"
        )

    def _save_stage3_outputs(self, client_id: str, synthesis, plan):
        """Save Stage 3 synthesis outputs and proto-reports."""
        synth_path = self.output_dir / client_id / "03_synthesis"
        synth_path.mkdir(parents=True, exist_ok=True)

        if synthesis:
            (synth_path / "evidence_graph.json").write_text(
                json.dumps(synthesis.evidence_graph.model_dump(), indent=2, default=str),
                encoding="utf-8"
            )
            (synth_path / "risk_assessment.json").write_text(
                json.dumps(
                    synthesis.revised_risk_assessment.model_dump() if synthesis.revised_risk_assessment else {},
                    indent=2, default=str
                ),
                encoding="utf-8"
            )

            # Generate proto-reports (4 department-targeted briefs)
            try:
                from generators.aml_operations_brief import generate_aml_operations_brief
                proto = generate_aml_operations_brief(
                    client_id=client_id,
                    synthesis=synthesis,
                    plan=plan,
                    evidence_store=self.evidence_store,
                )
                (synth_path / "proto_aml_operations_brief.md").write_text(proto, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Proto AML operations brief failed: {e}")

            try:
                from generators.risk_assessment_brief import generate_risk_assessment_brief
                proto = generate_risk_assessment_brief(
                    client_id=client_id,
                    synthesis=synthesis,
                    plan=plan,
                )
                (synth_path / "proto_risk_assessment_brief.md").write_text(proto, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Proto risk assessment brief failed: {e}")

            try:
                from generators.regulatory_actions_brief import generate_regulatory_actions_brief
                proto = generate_regulatory_actions_brief(
                    client_id=client_id,
                    synthesis=synthesis,
                    plan=plan,
                )
                (synth_path / "proto_regulatory_actions_brief.md").write_text(proto, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Proto regulatory actions brief failed: {e}")

            try:
                from generators.onboarding_summary import generate_onboarding_summary
                proto = generate_onboarding_summary(
                    client_id=client_id,
                    synthesis=synthesis,
                    plan=plan,
                )
                (synth_path / "proto_onboarding_decision_brief.md").write_text(proto, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Proto onboarding decision brief failed: {e}")

    def _save_review_session(self, client_id: str, session: ReviewSession):
        """Save review session data."""
        review_path = self.output_dir / client_id / "04_review"
        review_path.mkdir(parents=True, exist_ok=True)
        (review_path / "review_session.json").write_text(
            json.dumps(session.model_dump(), indent=2, default=str),
            encoding="utf-8"
        )

    def _serialize_investigation(self, investigation: InvestigationResults) -> dict:
        """Serialize investigation results for checkpoint."""
        data = {}
        for field_name in [
            "individual_sanctions", "pep_classification", "individual_adverse_media",
            "entity_verification", "entity_sanctions", "business_adverse_media",
            "jurisdiction_risk",
        ]:
            val = getattr(investigation, field_name, None)
            data[field_name] = val.model_dump() if val else None

        for field_name in [
            "id_verification", "suitability_assessment", "fatca_crs",
            "edd_requirements", "compliance_actions", "business_risk_assessment",
            "document_requirements",
        ]:
            data[field_name] = getattr(investigation, field_name, None)

        data["ubo_screening"] = investigation.ubo_screening
        return data

    def _deserialize_investigation(self, data: dict) -> InvestigationResults:
        """Deserialize investigation results from checkpoint."""
        results = InvestigationResults()

        model_map = {
            "individual_sanctions": SanctionsResult,
            "pep_classification": PEPClassification,
            "individual_adverse_media": AdverseMediaResult,
            "entity_verification": EntityVerification,
            "entity_sanctions": SanctionsResult,
            "business_adverse_media": AdverseMediaResult,
            "jurisdiction_risk": JurisdictionRiskResult,
        }

        for field_name, model_class in model_map.items():
            val = data.get(field_name)
            if val:
                try:
                    setattr(results, field_name, model_class(**val))
                except Exception as e:
                    logger.warning(f"Could not deserialize {field_name}: {e}")

        for field_name in [
            "id_verification", "suitability_assessment", "fatca_crs",
            "edd_requirements", "compliance_actions", "business_risk_assessment",
            "document_requirements",
        ]:
            setattr(results, field_name, data.get(field_name))

        results.ubo_screening = data.get("ubo_screening", {})
        return results
