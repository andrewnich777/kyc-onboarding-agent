"""
KYC Synthesis Agent.
Cross-references all findings, detects contradictions, recommends decision.
Uses Opus 4.6 for complex reasoning.
"""

import json
from agents.base import BaseAgent, KYC_EVIDENCE_RULES, KYC_REGULATORY_CONTEXT
from models import (
    KYCSynthesisOutput, KYCEvidenceGraph, OnboardingDecision,
    RiskAssessment, RiskLevel,
    EvidenceRecord, EvidenceClass, DispositionStatus, Confidence,
    CounterArgument, DecisionOption, DecisionPoint,
)
from logger import get_logger

logger = get_logger(__name__)


class KYCSynthesisAgent(BaseAgent):
    """Cross-reference all KYC findings and recommend onboarding decision."""

    @property
    def name(self) -> str:
        return "KYCSynthesis"

    @property
    def system_prompt(self) -> str:
        return f"""You are a senior KYC compliance analyst performing final synthesis of all screening results.

{KYC_REGULATORY_CONTEXT}

## Your Role
1. Cross-reference ALL evidence records for consistency and contradictions
2. Identify corroborating evidence (multiple sources confirming same finding)
3. Identify contradictions (sources disagreeing)
4. Assess overall risk considering all findings holistically
5. Recommend an onboarding decision

## Decision Framework
- APPROVE: Low risk, all screenings clear, no material concerns
- CONDITIONAL: Moderate risk, specific conditions must be met (list them)
- ESCALATE: High risk or unresolved findings, needs senior management review
- DECLINE: Critical risk, confirmed sanctions match, or overwhelming adverse indicators

## Important Principles
- AI investigates. Rules classify. Humans decide.
- Your recommendation is advisory — the compliance officer makes the final call
- Flag items that REQUIRE human review explicitly
- Never auto-approve high-risk clients
- When evidence conflicts, explain both sides
- Your output feeds a downstream Review Intelligence engine that performs deterministic analysis. To maximize its effectiveness: be explicit about uncertainty levels and why confidence is low; when identifying contradictions, always name BOTH agents involved (e.g. "IndividualSanctions vs IndividualAdverseMedia"); when an evidence record has low confidence, state what additional verification would resolve it

## Counter-Arguments & Decision Points

For every non-trivial disposition in the investigation (sanctions matches not CLEAR, PEP classifications not NOT_PEP, adverse media rated MATERIAL_CONCERN or above), generate:

1. A COUNTER-ARGUMENT: The strongest case AGAINST the recommended disposition, using the same evidence. Be specific — cite evidence IDs, name the risk factors, explain what pattern an auditor might flag. Write it as if you're a skeptical senior compliance officer reviewing junior work.

2. DECISION OPTIONS: Present 3-4 concrete choices the compliance officer can make, each with:
   - What the choice means operationally
   - Downstream regulatory consequences (filing obligations, timelines, approval requirements)
   - Impact on client onboarding (proceeds, paused, rejected)
   - Expected timeline to resolution

Standard decision options by disposition type:

For sanctions dispositions (FALSE_POSITIVE, PENDING_REVIEW, POTENTIAL_MATCH):
  A) CLEAR — Accept disposition, document reasoning, onboarding proceeds
  B) ESCALATE — Senior AML analyst review, 30-day window, onboarding paused
  C) REQUEST_DOCS — Request additional identity verification from client, onboarding paused
  D) REJECT — Decline onboarding, document reasoning, consider STR filing

For PEP classifications:
  A) ACCEPT — Accept classification, apply required EDD measures, proceed with enhanced monitoring
  B) ESCALATE — Senior management review (required within 30 days for foreign PEP)
  C) REQUEST_DOCS — Request source of wealth/funds documentation before proceeding
  D) REJECT — Decline onboarding

For adverse media findings (MATERIAL_CONCERN or HIGH_RISK):
  A) ACCEPT_WITH_MONITORING — Accept risk, implement enhanced monitoring schedule
  B) ESCALATE — Senior review of media findings, assess STR consideration
  C) REQUEST_DOCS — Request client explanation of flagged articles
  D) REJECT — Decline onboarding

Adapt the consequences for each option based on the client's specific risk tier, applicable regulations, and investigation findings. Reference actual timelines from compliance actions.

For LOW risk clients with all-clear screening, do NOT generate counter-arguments or decision points. Just recommend APPROVE.

{KYC_EVIDENCE_RULES}

Return JSON with:
- evidence_graph: {{total_evidence_records, verified_count, sourced_count, inferred_count, unknown_count, contradictions, corroborations, unresolved_items}}
- key_findings: array of top findings
- contradictions: array of {{finding_1, finding_2, resolution}}
- risk_elevations: array of {{factor, points, reason}} (new risks discovered)
- recommended_decision: APPROVE | CONDITIONAL | ESCALATE | DECLINE
- decision_reasoning: detailed explanation
- conditions: array (for CONDITIONAL)
- items_requiring_review: array (items the officer must review)
- senior_management_approval_needed: boolean
- decision_points: array of {{decision_id, title, context_summary, disposition, confidence, counter_argument: {{evidence_id, disposition_challenged, argument, risk_if_wrong, recommended_mitigations}}, options: [{{option_id, label, description, consequences, onboarding_impact, timeline}}]}}"""

    @property
    def tools(self) -> list[str]:
        return []  # Pure reasoning, no tools

    async def synthesize(self, evidence_store: list[dict],
                         risk_assessment: dict,
                         client_summary: str) -> KYCSynthesisOutput:
        """Synthesize all evidence and recommend a decision."""
        evidence_json = json.dumps(evidence_store, indent=2, default=str)

        prompt = f"""Synthesize all KYC screening results and recommend an onboarding decision.

## Client Summary
{client_summary}

## Current Risk Assessment
Risk Level: {risk_assessment.get('risk_level', 'UNKNOWN')}
Risk Score: {risk_assessment.get('total_score', 0)}
Risk Factors: {json.dumps(risk_assessment.get('risk_factors', []), default=str)}

## Evidence Store ({len(evidence_store)} records)
{evidence_json}

Analyze ALL evidence records. Cross-reference findings. Identify contradictions.
Then recommend APPROVE, CONDITIONAL, ESCALATE, or DECLINE with detailed reasoning."""

        result = await self.run(prompt)
        return self._parse_result(result)

    def _parse_result(self, result: dict) -> KYCSynthesisOutput:
        data = result.get("json", {})
        if not data:
            return KYCSynthesisOutput(
                recommended_decision=OnboardingDecision.ESCALATE,
                decision_reasoning="Synthesis agent did not return structured data — escalating for manual review",
                items_requiring_review=["All findings require manual review"],
                senior_management_approval_needed=True,
            )

        decision = OnboardingDecision.ESCALATE
        try:
            decision = OnboardingDecision(data.get("recommended_decision", "ESCALATE").upper())
        except ValueError:
            pass

        graph_data = data.get("evidence_graph", {})
        graph = KYCEvidenceGraph(
            total_evidence_records=graph_data.get("total_evidence_records", 0),
            verified_count=graph_data.get("verified_count", 0),
            sourced_count=graph_data.get("sourced_count", 0),
            inferred_count=graph_data.get("inferred_count", 0),
            unknown_count=graph_data.get("unknown_count", 0),
            contradictions=graph_data.get("contradictions", []),
            corroborations=graph_data.get("corroborations", []),
            unresolved_items=graph_data.get("unresolved_items", []),
        )

        # Parse decision points
        decision_points = []
        for dp_data in data.get("decision_points", []):
            try:
                ca_data = dp_data.get("counter_argument", {})
                counter_arg = CounterArgument(
                    evidence_id=ca_data.get("evidence_id", ""),
                    disposition_challenged=ca_data.get("disposition_challenged", ""),
                    argument=ca_data.get("argument", ""),
                    risk_if_wrong=ca_data.get("risk_if_wrong", ""),
                    recommended_mitigations=ca_data.get("recommended_mitigations", []),
                )

                options = []
                for opt_data in dp_data.get("options", []):
                    options.append(DecisionOption(
                        option_id=opt_data.get("option_id", ""),
                        label=opt_data.get("label", ""),
                        description=opt_data.get("description", ""),
                        consequences=opt_data.get("consequences", []),
                        onboarding_impact=opt_data.get("onboarding_impact", ""),
                        timeline=opt_data.get("timeline", ""),
                    ))

                decision_points.append(DecisionPoint(
                    decision_id=dp_data.get("decision_id", f"dp_{len(decision_points)}"),
                    title=dp_data.get("title", ""),
                    context_summary=dp_data.get("context_summary", ""),
                    disposition=dp_data.get("disposition", ""),
                    confidence=float(dp_data.get("confidence", 0.0)),
                    counter_argument=counter_arg,
                    options=options,
                ))
            except Exception as e:
                logger.warning(f"Could not parse decision point: {e}")

        return KYCSynthesisOutput(
            evidence_graph=graph,
            key_findings=data.get("key_findings", []),
            contradictions=data.get("contradictions", []),
            risk_elevations=data.get("risk_elevations", []),
            recommended_decision=decision,
            decision_reasoning=data.get("decision_reasoning", ""),
            conditions=data.get("conditions", []),
            items_requiring_review=data.get("items_requiring_review", []),
            senior_management_approval_needed=data.get("senior_management_approval_needed", False),
            decision_points=decision_points,
        )
