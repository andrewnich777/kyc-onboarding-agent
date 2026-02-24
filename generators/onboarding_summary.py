"""
Onboarding Summary Generator.
One-page decision summary in Markdown.
"""

from datetime import datetime


def _extract_ubo_status(ubo_data: dict, screening_type: str, field: str) -> str:
    """Extract a human-readable status from UBO screening data."""
    if not ubo_data:
        return "Pending"
    result = ubo_data.get(screening_type)
    if not result:
        return "Pending"
    if isinstance(result, dict):
        value = result.get(field, "Pending")
        if value == "CLEAR" or value == "NOT_PEP":
            return "Clear"
        return str(value).replace("_", " ").title()
    return "Pending"


def generate_onboarding_summary(
    client_id: str,
    synthesis=None,
    plan=None,
    investigation=None,
) -> str:
    """Generate a one-page onboarding summary."""
    lines = []
    now = datetime.now().strftime("%B %d, %Y")

    # Decision banner
    decision = "ESCALATE"
    if synthesis:
        decision = synthesis.recommended_decision.value

    decision_emoji = {
        "APPROVE": "APPROVED",
        "CONDITIONAL": "CONDITIONAL APPROVAL",
        "ESCALATE": "ESCALATED FOR REVIEW",
        "DECLINE": "DECLINED",
    }

    lines.append(f"# Onboarding Decision: {decision_emoji.get(decision, decision)}")
    lines.append(f"**Client:** {client_id} | **Date:** {now}")
    lines.append("")

    # Risk summary
    if plan and plan.preliminary_risk:
        risk = plan.preliminary_risk
        lines.append(f"## Risk Assessment: {risk.risk_level.value} ({risk.total_score} pts)")
        lines.append("")

    # Top 5 risk factors
    if plan and plan.preliminary_risk and plan.preliminary_risk.risk_factors:
        lines.append("## Top Risk Factors")
        for rf in sorted(plan.preliminary_risk.risk_factors, key=lambda x: x.points, reverse=True)[:5]:
            lines.append(f"- **{rf.factor}** (+{rf.points} pts)")
        lines.append("")

    # Decision reasoning
    if synthesis and synthesis.decision_reasoning:
        lines.append("## Decision Reasoning")
        lines.append(synthesis.decision_reasoning)
        lines.append("")

    # Required actions
    if synthesis and synthesis.conditions:
        lines.append("## Required Actions")
        for i, cond in enumerate(synthesis.conditions, 1):
            lines.append(f"{i}. {cond}")
        lines.append("")

    # Senior management approval
    if synthesis and synthesis.senior_management_approval_needed:
        lines.append("## Senior Management Approval")
        lines.append("**This client requires senior management approval before onboarding.**")
        lines.append("")
        if synthesis.items_requiring_review:
            lines.append("Items for senior review:")
            for item in synthesis.items_requiring_review:
                lines.append(f"- {item}")
        lines.append("")

    # UBO risk summary (for business clients)
    if plan and plan.ubo_cascade_needed:
        lines.append("## Beneficial Owner Risk Summary")
        lines.append("| Owner | Sanctions | PEP | Adverse Media |")
        lines.append("|-------|-----------|-----|---------------|")
        ubo_screening = {}
        if investigation and hasattr(investigation, 'ubo_screening'):
            ubo_screening = investigation.ubo_screening
        for ubo_name in plan.ubo_names:
            ubo_data = ubo_screening.get(ubo_name, {})
            sanctions_status = _extract_ubo_status(ubo_data, "sanctions", "disposition")
            pep_status = _extract_ubo_status(ubo_data, "pep", "detected_level")
            media_status = _extract_ubo_status(ubo_data, "adverse_media", "overall_level")
            lines.append(f"| {ubo_name} | {sanctions_status} | {pep_status} | {media_status} |")
        lines.append("")

    # Applicable regulations
    if plan and plan.applicable_regulations:
        lines.append("## Regulatory Requirements")
        for reg in plan.applicable_regulations:
            lines.append(f"- {reg}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("*AI investigates. Rules classify. Humans decide.*")

    return "\n".join(lines)
