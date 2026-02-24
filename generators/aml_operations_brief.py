"""
AML Operations Brief Generator.
Full investigation deep-dive for AML Analysts.
Replaces the Compliance Officer Brief with richer detail.
"""

from datetime import datetime
from typing import Optional

from generators.ubo_helpers import extract_ubo_field as _extract_ubo_field


def generate_aml_operations_brief(
    client_id: str,
    synthesis=None,
    plan=None,
    evidence_store: list = None,
    review_session=None,
    investigation=None,
) -> str:
    """Generate a detailed AML operations brief in Markdown."""
    lines = []
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    lines.append(f"# AML Operations Brief: {client_id}")
    lines.append(f"*Generated: {now}*")
    lines.append("")

    # =========================================================================
    # 1. Client Identification Summary
    # =========================================================================
    lines.append("## Client Identification Summary")
    if plan:
        lines.append(f"- **Client Type:** {plan.client_type.value}")
        lines.append(f"- **Client ID:** {plan.client_id}")
        if plan.preliminary_risk:
            risk = plan.preliminary_risk
            lines.append(f"- **Risk Level:** {risk.risk_level.value}")
            lines.append(f"- **Risk Score:** {risk.total_score} pts")
    lines.append("")

    # =========================================================================
    # 2. Sanctions Screening
    # =========================================================================
    lines.append("## Sanctions Screening")

    sanctions_results = []
    if investigation:
        if investigation.individual_sanctions:
            sanctions_results.append(("Individual", investigation.individual_sanctions))
        if investigation.entity_sanctions:
            sanctions_results.append(("Entity", investigation.entity_sanctions))

    if sanctions_results:
        for label, sr in sanctions_results:
            lines.append(f"### {label} Screening: {sr.entity_screened}")
            lines.append(f"**Disposition:** {sr.disposition.value}")
            if sr.disposition_reasoning:
                lines.append(f"*Reasoning:* {sr.disposition_reasoning}")
            lines.append("")

            # Screening sources
            if sr.screening_sources:
                lines.append("**Screening Sources:** " + ", ".join(sr.screening_sources))
                lines.append("")

            # Search queries executed
            if sr.search_queries_executed:
                lines.append("**Search Queries Executed:**")
                for q in sr.search_queries_executed:
                    lines.append(f"- `{q}`")
                lines.append("")

            # Match detail table
            if sr.matches:
                lines.append("| List | Matched Name | Score | Disposition | Reasoning |")
                lines.append("|------|-------------|-------|-------------|-----------|")
                for m in sr.matches:
                    list_name = m.get("list_name", "N/A")
                    matched = m.get("matched_name", "N/A")
                    score = m.get("score", "N/A")
                    details = str(m.get("details", ""))[:60]
                    lines.append(f"| {list_name} | {matched} | {score} | {sr.disposition.value} | {details} |")
                lines.append("")
            else:
                lines.append("No matches found across all screening sources.")
                lines.append("")
    else:
        lines.append("No sanctions screening results available.")
        lines.append("")

    # =========================================================================
    # 3. PEP Classification
    # =========================================================================
    lines.append("## PEP Classification")
    if investigation and investigation.pep_classification:
        pep = investigation.pep_classification
        lines.append(f"- **Entity:** {pep.entity_screened}")
        lines.append(f"- **Detected Level:** {pep.detected_level.value}")
        lines.append(f"- **Self-Declared:** {pep.self_declared}")
        lines.append(f"- **EDD Required:** {pep.edd_required}")
        lines.append("")

        # EDD Timeline
        if pep.edd_permanent:
            lines.append("**EDD Timeline:** Permanent (never expires)")
        elif pep.edd_expiry_date:
            lines.append(f"**EDD Timeline:** Expires {pep.edd_expiry_date}")
        lines.append("")

        # Positions table
        if pep.positions_found:
            lines.append("### Positions Found")
            lines.append("| Position | Organization | Dates | Source |")
            lines.append("|----------|-------------|-------|--------|")
            for pos in pep.positions_found:
                position = pos.get("position", "N/A")
                org = pos.get("organization", "N/A")
                dates = pos.get("dates", "N/A")
                source = pos.get("source", "N/A")
                lines.append(f"| {position} | {org} | {dates} | {source} |")
            lines.append("")

        # Search queries
        if pep.search_queries_executed:
            lines.append("**Search Queries Executed:**")
            for q in pep.search_queries_executed:
                lines.append(f"- `{q}`")
            lines.append("")
    else:
        lines.append("No PEP classification results available.")
        lines.append("")

    # =========================================================================
    # 4. Adverse Media Screening
    # =========================================================================
    lines.append("## Adverse Media Screening")

    media_results = []
    if investigation:
        if investigation.individual_adverse_media:
            media_results.append(("Individual", investigation.individual_adverse_media))
        if investigation.business_adverse_media:
            media_results.append(("Business", investigation.business_adverse_media))

    if media_results:
        for label, mr in media_results:
            lines.append(f"### {label} Media: {mr.entity_screened}")
            lines.append(f"**Overall Level:** {mr.overall_level.value}")
            lines.append("")

            if mr.categories:
                lines.append(f"**Categories:** {', '.join(mr.categories)}")
                lines.append("")

            # Articles table with source tier
            if mr.articles_found:
                lines.append("| Tier | Title | Source | Date | Category |")
                lines.append("|------|-------|--------|------|----------|")
                for article in mr.articles_found:
                    tier = article.get("source_tier", "TIER_2")
                    title = str(article.get("title", "N/A"))[:50]
                    source = str(article.get("source", "N/A"))[:25]
                    date = article.get("date", "N/A")
                    category = article.get("category", "N/A")
                    lines.append(f"| {tier} | {title} | {source} | {date} | {category} |")
                lines.append("")

            # Search queries
            if mr.search_queries_executed:
                lines.append("**Search Queries Executed:**")
                for q in mr.search_queries_executed:
                    lines.append(f"- `{q}`")
                lines.append("")
    else:
        lines.append("No adverse media screening results available.")
        lines.append("")

    # =========================================================================
    # 5. UBO Cascade Results (business only)
    # =========================================================================
    if investigation and investigation.ubo_screening:
        lines.append("## UBO Cascade Results")
        lines.append("| Owner | % | Sanctions | PEP | Adverse Media |")
        lines.append("|-------|---|-----------|-----|---------------|")
        for ubo_name, ubo_data in investigation.ubo_screening.items():
            pct = "?"
            # Try to extract percentage from evidence context
            sanctions_disp = _extract_ubo_field(ubo_data, "sanctions", "disposition", "Pending")
            pep_level = _extract_ubo_field(ubo_data, "pep", "detected_level", "Pending")
            media_level = _extract_ubo_field(ubo_data, "adverse_media", "overall_level", "Pending")
            lines.append(f"| {ubo_name} | {pct} | {sanctions_disp} | {pep_level} | {media_level} |")
        lines.append("")

    # =========================================================================
    # 6. Evidence Graph
    # =========================================================================
    if synthesis and synthesis.evidence_graph:
        eg = synthesis.evidence_graph
        lines.append("## Evidence Graph")
        lines.append(f"- **Total Evidence Records:** {eg.total_evidence_records}")
        lines.append(f"- **[V] Verified:** {eg.verified_count}")
        lines.append(f"- **[S] Sourced:** {eg.sourced_count}")
        lines.append(f"- **[I] Inferred:** {eg.inferred_count}")
        lines.append(f"- **[U] Unknown:** {eg.unknown_count}")
        lines.append(f"- **Contradictions:** {len(eg.contradictions)}")
        lines.append(f"- **Corroborations:** {len(eg.corroborations)}")
        lines.append("")

        if eg.contradictions:
            lines.append("### Contradictions")
            for c in eg.contradictions:
                lines.append(f"- {c.get('finding_1', 'N/A')} vs {c.get('finding_2', 'N/A')}")
            lines.append("")

    # =========================================================================
    # 7. Evidence Record Listing
    # =========================================================================
    if evidence_store:
        lines.append("## Evidence Records")
        lines.append(f"Total: {len(evidence_store)}")
        lines.append("")
        lines.append("| ID | Source | Entity | Claim | Level | Disposition |")
        lines.append("|----|--------|--------|-------|-------|-------------|")
        for er in evidence_store[:50]:  # Cap at 50 for readability
            if isinstance(er, dict):
                eid = str(er.get("evidence_id", ""))[:12]
                source = er.get("source_name", "N/A")
                entity = str(er.get("entity_screened", ""))[:20]
                claim = str(er.get("claim", ""))[:40]
                level = er.get("evidence_level", "U")
                disp = er.get("disposition", "PENDING_REVIEW")
                lines.append(f"| {eid} | {source} | {entity} | {claim} | [{level}] | {disp} |")
        if len(evidence_store) > 50:
            lines.append(f"*... and {len(evidence_store) - 50} more records*")
        lines.append("")

    # =========================================================================
    # 8. Disposition Analysis & Officer Decisions
    # =========================================================================
    if synthesis and synthesis.decision_points:
        lines.append("## Disposition Analysis & Officer Decisions")
        lines.append("")
        for dp in synthesis.decision_points:
            lines.append(f"### {dp.title}")
            lines.append("")
            lines.append(f"**System Recommendation:** {dp.disposition} ({dp.confidence:.0%} confidence)")
            lines.append("")
            lines.append(f"**Context:** {dp.context_summary}")
            lines.append("")

            # Counter-argument
            ca = dp.counter_argument
            lines.append("**Counter-Analysis:**")
            lines.append(f"{ca.argument}")
            lines.append("")
            lines.append(f"**Risk if Disposition Incorrect:**")
            lines.append(f"{ca.risk_if_wrong}")
            lines.append("")

            if ca.recommended_mitigations:
                lines.append("**Recommended Mitigations:**")
                for m in ca.recommended_mitigations:
                    lines.append(f"- {m}")
                lines.append("")

            # Officer decision (if made)
            if dp.officer_selection:
                selected_opt = None
                for opt in dp.options:
                    if opt.option_id == dp.officer_selection:
                        selected_opt = opt
                        break
                label = selected_opt.label if selected_opt else dp.officer_selection
                lines.append(f"**Officer Decision:** {label} (Option {dp.officer_selection})")
                if dp.officer_notes:
                    lines.append(f"- Officer Notes: \"{dp.officer_notes}\"")
                lines.append(f"- Counter-argument acknowledged: Yes")
                lines.append("")
            else:
                # Show available options
                lines.append("**Decision Options:**")
                lines.append("")
                lines.append("| Option | Label | Description | Onboarding Impact | Timeline |")
                lines.append("|--------|-------|-------------|-------------------|----------|")
                for opt in dp.options:
                    lines.append(f"| {opt.option_id} | {opt.label} | {opt.description} | {opt.onboarding_impact} | {opt.timeline} |")
                lines.append("")
                lines.append("*Awaiting officer decision*")
                lines.append("")

    # =========================================================================
    # 9. Review Session Log
    # =========================================================================
    if review_session and review_session.actions:
        lines.append("## Review Session Log")
        lines.append(f"- **Officer:** {review_session.officer_name or 'Not specified'}")
        lines.append(f"- **Started:** {review_session.started_at}")
        lines.append(f"- **Finalized:** {review_session.finalized}")
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

    # Footer
    lines.append("---")
    lines.append("*Evidence: [V] Verified | [S] Sourced | [I] Inferred | [U] Unknown*")
    lines.append("*AI investigates. Rules classify. Humans decide.*")

    return "\n".join(lines)


