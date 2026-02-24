"""
Risk Assessment Brief Generator.
Quantitative risk breakdown for Fraud & Risk team.
"""

from datetime import datetime
from typing import Optional

from generators.ubo_helpers import extract_ubo_field as _ubo_field


def generate_risk_assessment_brief(
    client_id: str,
    synthesis=None,
    plan=None,
    investigation=None,
) -> str:
    """Generate a quantitative risk assessment brief in Markdown."""
    lines = []
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    lines.append(f"# Risk Assessment Brief: {client_id}")
    lines.append(f"*Generated: {now}*")
    lines.append("")

    # =========================================================================
    # 1. Risk Score Summary
    # =========================================================================
    lines.append("## Risk Score Summary")
    risk = None
    if synthesis and synthesis.revised_risk_assessment:
        risk = synthesis.revised_risk_assessment
    elif plan and plan.preliminary_risk:
        risk = plan.preliminary_risk

    if risk:
        lines.append(f"- **Total Score:** {risk.total_score} pts")
        lines.append(f"- **Risk Level:** {risk.risk_level.value}")
        lines.append("")

        # Tier thresholds visualization
        lines.append("### Risk Tier Thresholds")
        lines.append("| Tier | Score Range | Status |")
        lines.append("|------|-----------|--------|")
        tiers = [
            ("LOW", "0-15", risk.risk_level.value == "LOW"),
            ("MEDIUM", "16-35", risk.risk_level.value == "MEDIUM"),
            ("HIGH", "36-60", risk.risk_level.value == "HIGH"),
            ("CRITICAL", "61+", risk.risk_level.value == "CRITICAL"),
        ]
        for tier_name, tier_range, is_current in tiers:
            marker = "CURRENT" if is_current else ""
            lines.append(f"| {tier_name} | {tier_range} | {marker} |")
        lines.append("")
    else:
        lines.append("No risk assessment available.")
        lines.append("")

    # =========================================================================
    # 2. Risk Factor Breakdown
    # =========================================================================
    if risk and risk.risk_factors:
        lines.append("## Risk Factor Breakdown")
        lines.append("| Factor | Category | Points | Source |")
        lines.append("|--------|----------|--------|--------|")
        sorted_factors = sorted(risk.risk_factors, key=lambda x: x.points, reverse=True)
        for rf in sorted_factors:
            lines.append(f"| {rf.factor} | {rf.category} | +{rf.points} | {rf.source} |")
        lines.append("")

    # =========================================================================
    # 3. Score Progression
    # =========================================================================
    if risk and risk.score_history:
        lines.append("## Score Progression")
        lines.append("| Stage | Score | Level | Delta |")
        lines.append("|-------|-------|-------|-------|")
        prev_score = 0
        for entry in risk.score_history:
            stage = entry.get("stage", "unknown")
            score = entry.get("score", 0)
            level = entry.get("level", "UNKNOWN")
            delta = score - prev_score
            delta_str = f"+{delta}" if delta > 0 else str(delta) if delta < 0 else "base"
            lines.append(f"| {stage} | {score} | {level} | {delta_str} |")
            prev_score = score
        lines.append("")

    # =========================================================================
    # 4. Financial Profile Flags
    # =========================================================================
    if investigation and investigation.suitability_assessment:
        suit = investigation.suitability_assessment
        lines.append("## Financial Profile Flags")
        details = suit.get("details", {})
        if details:
            income = details.get("income_assessment", {})
            if income:
                lines.append(f"- **Income Assessment:** {income.get('assessment', 'N/A')}")
            wealth_ratio = details.get("wealth_income_ratio", {})
            if wealth_ratio:
                lines.append(f"- **Wealth/Income Ratio:** {wealth_ratio.get('ratio', 'N/A')} ({wealth_ratio.get('assessment', '')})")
            sof = details.get("source_of_funds", {})
            if sof:
                lines.append(f"- **Source of Funds:** {sof.get('source', 'N/A')} (risk: {sof.get('risk_level', 'N/A')})")
        lines.append("")

    # =========================================================================
    # 5. Jurisdiction Risk Matrix
    # =========================================================================
    if investigation and investigation.jurisdiction_risk:
        jr = investigation.jurisdiction_risk
        lines.append("## Jurisdiction Risk Matrix")
        lines.append(f"**Overall Jurisdiction Risk:** {jr.overall_jurisdiction_risk.value}")
        lines.append("")

        if jr.jurisdiction_details:
            lines.append("| Jurisdiction | FATF Status | Sanctions Programs | CPI Score | Basel AML |")
            lines.append("|-------------|-------------|-------------------|-----------|-----------|")
            for jd in jr.jurisdiction_details:
                country = jd.get("country", "N/A")
                fatf = jd.get("fatf_status", "clean")
                cpi = jd.get("cpi_score", "N/A") or "N/A"
                basel = jd.get("basel_aml_score", "N/A") or "N/A"
                # Find sanctions programs for this country
                programs = [
                    sp.get("program", "")
                    for sp in jr.sanctions_programs
                    if sp.get("country", "").lower() == country.lower()
                ]
                programs_str = ", ".join(programs) if programs else "None"
                lines.append(f"| {country} | {fatf} | {programs_str} | {cpi} | {basel} |")
            lines.append("")
        elif jr.jurisdictions_assessed:
            lines.append("| Jurisdiction | FATF Status |")
            lines.append("|-------------|-------------|")
            for country in jr.jurisdictions_assessed:
                fatf = "black_list" if country in jr.fatf_black_list else (
                    "grey_list" if country in jr.fatf_grey_list else "clean"
                )
                lines.append(f"| {country} | {fatf} |")
            lines.append("")

    # =========================================================================
    # 6. Business Risk Analysis (business only)
    # =========================================================================
    if investigation and investigation.business_risk_assessment:
        bra = investigation.business_risk_assessment
        lines.append("## Business Risk Analysis")

        if bra.get("risk_factors"):
            lines.append("### Business Risk Factors")
            for rf in bra["risk_factors"]:
                if isinstance(rf, dict):
                    lines.append(f"- **{rf.get('factor', 'N/A')}** (+{rf.get('points', 0)} pts) — {rf.get('category', '')}")
                else:
                    lines.append(f"- {rf}")
            lines.append("")

        if bra.get("ownership_analysis"):
            lines.append(f"### Ownership Analysis")
            oa = bra["ownership_analysis"]
            if isinstance(oa, dict):
                for key, val in oa.items():
                    lines.append(f"- **{key}:** {val}")
            else:
                lines.append(str(oa))
            lines.append("")

        if bra.get("operational_analysis"):
            lines.append(f"### Operational Analysis")
            op = bra["operational_analysis"]
            if isinstance(op, dict):
                for key, val in op.items():
                    lines.append(f"- **{key}:** {val}")
            else:
                lines.append(str(op))
            lines.append("")

    # =========================================================================
    # 7. UBO Individual Risk Contributions (business only)
    # =========================================================================
    if investigation and investigation.ubo_screening:
        lines.append("## UBO Individual Risk Contributions")
        lines.append("| Owner | Sanctions | PEP | Adverse Media | Risk Contribution |")
        lines.append("|-------|-----------|-----|---------------|-------------------|")
        for ubo_name, ubo_data in investigation.ubo_screening.items():
            s_disp = _ubo_field(ubo_data, "sanctions", "disposition", "Pending")
            p_level = _ubo_field(ubo_data, "pep", "detected_level", "Pending")
            m_level = _ubo_field(ubo_data, "adverse_media", "overall_level", "Pending")
            # Compute risk contribution
            contribution = 0
            if s_disp not in ("Clear", "Pending"):
                contribution += 30
            if p_level not in ("Clear", "Not Pep", "Pending"):
                contribution += 25
            if m_level not in ("Clear", "Pending"):
                contribution += 15
            lines.append(f"| {ubo_name} | {s_disp} | {p_level} | {m_level} | +{contribution} pts |")
        lines.append("")

    # =========================================================================
    # 8. Suitability Assessment Summary
    # =========================================================================
    if investigation and investigation.suitability_assessment:
        suit = investigation.suitability_assessment
        lines.append("## Suitability Assessment")
        lines.append(f"- **Suitable:** {suit.get('suitable', 'N/A')}")
        if suit.get("concerns"):
            lines.append("### Concerns")
            for concern in suit["concerns"]:
                lines.append(f"- {concern}")
        lines.append("")

    # =========================================================================
    # 9. Synthesis Risk Elevations
    # =========================================================================
    if synthesis and synthesis.risk_elevations:
        lines.append("## Synthesis Risk Elevations")
        lines.append("| Factor | Points | Reason |")
        lines.append("|--------|--------|--------|")
        for el in synthesis.risk_elevations:
            factor = el.get("factor", "Unknown")
            points = el.get("points", 0)
            reason = el.get("reason", "")
            lines.append(f"| {factor} | +{points} | {reason} |")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("*AI investigates. Rules classify. Humans decide.*")

    return "\n".join(lines)


