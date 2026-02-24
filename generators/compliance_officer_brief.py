"""
Compliance Officer Brief Generator.
Produces detailed markdown compliance brief for officer review.
"""

from datetime import datetime
from typing import Optional


def generate_compliance_brief(
    client_id: str,
    synthesis=None,
    plan=None,
    evidence_store: list = None,
    review_session=None,
) -> str:
    """Generate a detailed compliance officer brief in Markdown."""
    lines = []
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    lines.append(f"# KYC Compliance Brief: {client_id}")
    lines.append(f"*Generated: {now}*")
    lines.append("")

    # Risk Classification
    lines.append("## Risk Classification")
    if plan and plan.preliminary_risk:
        risk = plan.preliminary_risk
        lines.append(f"- **Risk Level:** {risk.risk_level.value}")
        lines.append(f"- **Risk Score:** {risk.total_score}")
        lines.append(f"- **Preliminary:** {'Yes' if risk.is_preliminary else 'No (revised)'}")
        lines.append("")

        if risk.risk_factors:
            lines.append("### Risk Factors")
            lines.append("| Factor | Points | Category |")
            lines.append("|--------|--------|----------|")
            for rf in risk.risk_factors:
                lines.append(f"| {rf.factor} | {rf.points} | {rf.category} |")
            lines.append("")

        if risk.score_history:
            lines.append("### Score Progression")
            for entry in risk.score_history:
                lines.append(f"- {entry.get('stage', 'unknown')}: {entry.get('score', 0)} pts ({entry.get('level', 'UNKNOWN')})")
            lines.append("")

    # Applicable Regulations
    if plan and plan.applicable_regulations:
        lines.append("## Applicable Regulations")
        for reg in plan.applicable_regulations:
            lines.append(f"- **{reg}**")
        lines.append("")

    # Screening Results
    lines.append("## Screening Results")
    if synthesis:
        if synthesis.key_findings:
            lines.append("### Key Findings")
            for finding in synthesis.key_findings:
                lines.append(f"- {finding}")
            lines.append("")

        if synthesis.contradictions:
            lines.append("### Contradictions")
            for c in synthesis.contradictions:
                lines.append(f"- **Finding 1:** {c.get('finding_1', 'N/A')}")
                lines.append(f"  **Finding 2:** {c.get('finding_2', 'N/A')}")
                lines.append(f"  **Resolution:** {c.get('resolution', 'Unresolved')}")
            lines.append("")

        if synthesis.risk_elevations:
            lines.append("### Risk Elevations (Synthesis-Discovered)")
            for el in synthesis.risk_elevations:
                lines.append(f"- {el.get('factor', 'Unknown')}: +{el.get('points', 0)} pts — {el.get('reason', '')}")
            lines.append("")

    # Evidence Summary
    if evidence_store:
        lines.append("## Evidence Summary")
        lines.append(f"Total evidence records: {len(evidence_store)}")
        lines.append("")

        # Count by evidence level
        levels = {}
        dispositions = {}
        for er in evidence_store:
            level = er.get("evidence_level", "U") if isinstance(er, dict) else "U"
            levels[level] = levels.get(level, 0) + 1
            disp = er.get("disposition", "PENDING_REVIEW") if isinstance(er, dict) else "PENDING_REVIEW"
            dispositions[disp] = dispositions.get(disp, 0) + 1

        lines.append("### By Evidence Level")
        for level, count in sorted(levels.items()):
            lines.append(f"- [{level}]: {count}")
        lines.append("")

        lines.append("### By Disposition")
        for disp, count in sorted(dispositions.items()):
            lines.append(f"- {disp}: {count}")
        lines.append("")

    # Decision Recommendation
    if synthesis:
        lines.append("## Recommended Decision")
        lines.append(f"**{synthesis.recommended_decision.value}**")
        lines.append("")
        if synthesis.decision_reasoning:
            lines.append(f"*Reasoning:* {synthesis.decision_reasoning}")
            lines.append("")

        if synthesis.conditions:
            lines.append("### Conditions (for CONDITIONAL approval)")
            for cond in synthesis.conditions:
                lines.append(f"- [ ] {cond}")
            lines.append("")

        if synthesis.items_requiring_review:
            lines.append("### Items Requiring Officer Review")
            for item in synthesis.items_requiring_review:
                lines.append(f"- [ ] {item}")
            lines.append("")

        if synthesis.senior_management_approval_needed:
            lines.append("### **Senior Management Approval Required**")
            lines.append("")

    # Review Session Log
    if review_session and review_session.actions:
        lines.append("## Review Session Log")
        lines.append(f"Officer: {review_session.officer_name or 'Not specified'}")
        lines.append(f"Started: {review_session.started_at}")
        lines.append(f"Finalized: {review_session.finalized}")
        lines.append("")

        for action in review_session.actions:
            lines.append(f"- **{action.action_type}** ({action.timestamp})")
            if action.query:
                lines.append(f"  Query: {action.query}")
            if action.response_summary:
                lines.append(f"  Response: {action.response_summary}")
            if action.officer_note:
                lines.append(f"  Note: {action.officer_note}")
        lines.append("")

    # Evidence Legend
    lines.append("---")
    lines.append("*Evidence: [V] Verified | [S] Sourced | [I] Inferred | [U] Unknown*")
    lines.append("*AI investigates. Rules classify. Humans decide.*")

    return "\n".join(lines)
