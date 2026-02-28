"""
Review Intelligence Engine.

Deterministic computation pass between Synthesis (Stage 3) and Review (Stage 4).
Analyzes the pipeline's own output and surfaces what the compliance officer needs
to focus on. Five facets, one cohesive system:

1. Critical discussion points
2. Contradiction surfacing
3. Confidence degradation alerts
4. Regulatory mapping per finding
5. Batch analytics across cases
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

from logger import get_logger
from models import (
    SeverityLevel,
    CriticalDiscussionPoint,
    Contradiction,
    ConfidenceDegradationAlert,
    RegulatoryTag,
    FindingWithRegulations,
    BatchCaseSignature,
    BatchPattern,
    BatchAnalytics,
    ReviewIntelligence,
    InvestigationResults,
    InvestigationPlan,
    KYCSynthesisOutput,
    EvidenceClass,
    DispositionStatus,
    Confidence,
    PEPLevel,
)

logger = get_logger(__name__)


# =============================================================================
# Public API
# =============================================================================

def compute_review_intelligence(
    evidence_store: list[dict],
    synthesis: KYCSynthesisOutput,
    plan: InvestigationPlan,
    investigation: InvestigationResults,
    analytics_dir: Path = None,
) -> ReviewIntelligence:
    """Compute all five facets of review intelligence.

    Args:
        evidence_store: Central evidence store (list of dicts).
        synthesis: KYCSynthesisOutput from Stage 3.
        plan: InvestigationPlan from Stage 1.
        investigation: InvestigationResults from Stage 2.
        analytics_dir: Directory for batch analytics JSONL storage.

    Returns:
        ReviewIntelligence composite model.
    """
    discussion_points = _extract_discussion_points(evidence_store, synthesis)
    contradictions = _detect_contradictions(evidence_store, synthesis, investigation)
    confidence = _assess_confidence(evidence_store)
    regulatory_mappings = _map_regulations_to_findings(evidence_store, plan, investigation)
    batch_analytics = _compute_batch_analytics(analytics_dir) if analytics_dir else BatchAnalytics()

    return ReviewIntelligence(
        discussion_points=discussion_points,
        contradictions=contradictions,
        confidence=confidence,
        regulatory_mappings=regulatory_mappings,
        batch_analytics=batch_analytics,
    )


def record_case_signature(
    client_id: str,
    plan: InvestigationPlan,
    synthesis: KYCSynthesisOutput,
    investigation: InvestigationResults,
    confidence_grade: str,
    contradictions_count: int,
    analytics_dir: Path,
):
    """Append a case signature to the analytics JSONL file."""
    analytics_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = analytics_dir / "case_signatures.jsonl"

    # Build jurisdictions list
    jurisdictions = []
    if investigation.jurisdiction_risk:
        jurisdictions = list(investigation.jurisdiction_risk.jurisdictions_assessed)

    # Build industries list
    industries = []
    if plan.client_type.value == "business":
        # Try to extract from plan or investigation
        for factor in plan.preliminary_risk.risk_factors:
            if factor.category == "industry":
                industries.append(factor.source)

    # Build regulations triggered
    regulations = list(plan.applicable_regulations)

    risk = synthesis.revised_risk_assessment or plan.preliminary_risk

    sig = BatchCaseSignature(
        client_id=client_id,
        timestamp=datetime.now(),
        risk_level=risk.risk_level.value,
        risk_score=risk.total_score,
        jurisdictions=jurisdictions,
        industries=industries,
        client_type=plan.client_type.value,
        regulations_triggered=regulations,
        confidence_grade=confidence_grade,
        contradictions_count=contradictions_count,
    )

    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(sig.model_dump(), default=str) + "\n")

    logger.info(f"Recorded case signature for {client_id}")


# =============================================================================
# Facet 1: Critical Discussion Points
# =============================================================================

def _extract_discussion_points(
    evidence_store: list[dict],
    synthesis: KYCSynthesisOutput,
) -> list[CriticalDiscussionPoint]:
    """Walk evidence store + synthesis output to flag items needing officer attention."""
    points: list[CriticalDiscussionPoint] = []
    point_counter = 0

    def _add(title, severity, reason, evidence_ids=None, source_agents=None, action=""):
        nonlocal point_counter
        point_counter += 1
        points.append(CriticalDiscussionPoint(
            point_id=f"CDP-{point_counter:03d}",
            title=title,
            severity=severity,
            reason=reason,
            evidence_ids=evidence_ids or [],
            source_agents=source_agents or [],
            recommended_action=action,
        ))

    # Scan evidence store
    for er in evidence_store:
        eid = er.get("evidence_id", "")
        disp = er.get("disposition", "")
        conf = er.get("confidence", "MEDIUM")
        ev_level = er.get("evidence_level", "U")
        claim = er.get("claim", "")[:80]
        source = er.get("source_name", "")

        # CRITICAL: POTENTIAL_MATCH or CONFIRMED_MATCH with LOW/MEDIUM confidence
        if disp in ("POTENTIAL_MATCH", "CONFIRMED_MATCH") and conf in ("LOW", "MEDIUM"):
            _add(
                title=f"Match with low confidence: {claim}",
                severity=SeverityLevel.CRITICAL,
                reason=f"Disposition is {disp} but confidence is only {conf}. "
                       f"Requires manual verification before proceeding.",
                evidence_ids=[eid],
                source_agents=[source],
                action="Verify match through primary sources; consider requesting additional documentation",
            )

        # HIGH: Inferred/Unknown evidence where disposition is not CLEAR
        if ev_level in ("I", "U") and disp not in ("CLEAR", "FALSE_POSITIVE"):
            severity = SeverityLevel.HIGH if disp != "PENDING_REVIEW" else SeverityLevel.MEDIUM
            _add(
                title=f"Weak evidence for non-clear disposition: {claim}",
                severity=severity,
                reason=f"Evidence level is [{ev_level}] but disposition is {disp}. "
                       f"Finding lacks strong source support.",
                evidence_ids=[eid],
                source_agents=[source],
                action="Seek corroborating evidence from primary sources",
            )

        # ADVISORY: Low-confidence CLEAR dispositions
        if disp == "CLEAR" and conf == "LOW":
            _add(
                title=f"Low-confidence clearance: {claim}",
                severity=SeverityLevel.ADVISORY,
                reason=f"Disposition is CLEAR but confidence is LOW. "
                       f"The clearance might be premature.",
                evidence_ids=[eid],
                source_agents=[source],
                action="Review supporting evidence; confirm clearance is warranted",
            )

    # Scan synthesis decision points with low confidence
    if synthesis and synthesis.decision_points:
        for dp in synthesis.decision_points:
            if dp.confidence < 0.7:
                _add(
                    title=f"Low-confidence decision: {dp.title}",
                    severity=SeverityLevel.CRITICAL,
                    reason=f"Decision point confidence is {dp.confidence:.0%}, below 70% threshold. "
                           f"Context: {dp.context_summary[:100]}",
                    evidence_ids=[dp.counter_argument.evidence_id] if dp.counter_argument.evidence_id else [],
                    source_agents=[],
                    action="Review counter-arguments carefully before selecting disposition",
                )

    # Scan synthesis items_requiring_review
    if synthesis and synthesis.items_requiring_review:
        for item in synthesis.items_requiring_review:
            _add(
                title=f"Synthesis flagged: {item[:60]}",
                severity=SeverityLevel.HIGH,
                reason=f"The synthesis agent explicitly flagged this for officer review.",
                evidence_ids=[],
                source_agents=["KYCSynthesis"],
                action="Address before finalizing decision",
            )

    # Scan synthesis risk_elevations
    if synthesis and synthesis.risk_elevations:
        for elevation in synthesis.risk_elevations:
            factor = elevation.get("factor", "Unknown factor")
            reason_text = elevation.get("reason", "")
            _add(
                title=f"Risk elevation: {factor}",
                severity=SeverityLevel.HIGH,
                reason=f"Synthesis discovered additional risk: {reason_text}",
                evidence_ids=[],
                source_agents=["KYCSynthesis"],
                action="Evaluate whether risk score adjustment is warranted",
            )

    # Sort: severity desc (CRITICAL first), then by point_id
    severity_order = {SeverityLevel.CRITICAL: 0, SeverityLevel.HIGH: 1,
                      SeverityLevel.MEDIUM: 2, SeverityLevel.ADVISORY: 3}
    points.sort(key=lambda p: (severity_order.get(p.severity, 99), p.point_id))

    # Cap at 15 items
    return points[:15]


# =============================================================================
# Facet 2: Contradiction Surfacing
# =============================================================================

def _detect_contradictions(
    evidence_store: list[dict],
    synthesis: KYCSynthesisOutput,
    investigation: InvestigationResults,
) -> list[Contradiction]:
    """Detect contradictions from synthesis output and cross-agent rules."""
    contradictions: list[Contradiction] = []
    c_counter = 0

    def _add(finding_a, finding_b, agent_a, agent_b, severity, guidance, evidence_ids=None):
        nonlocal c_counter
        c_counter += 1
        contradictions.append(Contradiction(
            contradiction_id=f"CTR-{c_counter:03d}",
            finding_a=finding_a,
            finding_b=finding_b,
            agent_a=agent_a,
            agent_b=agent_b,
            evidence_ids=evidence_ids or [],
            severity=severity,
            resolution_guidance=guidance,
        ))

    # Source 1: Parse synthesis contradictions
    if synthesis and synthesis.contradictions:
        for c in synthesis.contradictions:
            _add(
                finding_a=c.get("finding_1", c.get("finding_a", "Unknown")),
                finding_b=c.get("finding_2", c.get("finding_b", "Unknown")),
                agent_a=c.get("agent_1", c.get("agent_a", "Synthesis")),
                agent_b=c.get("agent_2", c.get("agent_b", "Synthesis")),
                severity=SeverityLevel.HIGH,
                guidance=c.get("resolution", c.get("resolution_guidance", "Review both findings")),
            )

    # Source 2: Deterministic cross-agent detection rules

    # Build lookup helpers
    sanctions_disp = None
    sanctions_matches = []
    if investigation.individual_sanctions:
        sanctions_disp = investigation.individual_sanctions.disposition.value
        sanctions_matches = investigation.individual_sanctions.matches
    elif investigation.entity_sanctions:
        sanctions_disp = investigation.entity_sanctions.disposition.value
        sanctions_matches = investigation.entity_sanctions.matches

    adverse_categories = []
    if investigation.individual_adverse_media:
        adverse_categories = investigation.individual_adverse_media.categories
    elif investigation.business_adverse_media:
        adverse_categories = investigation.business_adverse_media.categories

    pep_level = None
    if investigation.pep_classification:
        pep_level = investigation.pep_classification.detected_level

    # Rule: Sanctions CLEAR but adverse media includes sanctions_evasion → CRITICAL
    if sanctions_disp == "CLEAR" and "sanctions_evasion" in adverse_categories:
        media_agent = "IndividualAdverseMedia" if investigation.individual_adverse_media else "BusinessAdverseMedia"
        sanctions_agent = "IndividualSanctions" if investigation.individual_sanctions else "EntitySanctions"
        _add(
            finding_a="Sanctions screening: CLEAR",
            finding_b="Adverse media reports sanctions evasion activity",
            agent_a=sanctions_agent,
            agent_b=media_agent,
            severity=SeverityLevel.CRITICAL,
            guidance="Sanctions evasion media contradicts clear sanctions screening. "
                     "Re-screen against secondary lists and consider STR filing.",
        )

    # Rule: Sanctions FALSE_POSITIVE but match score > 0.85 → HIGH
    if sanctions_disp == "FALSE_POSITIVE":
        for match in sanctions_matches:
            score = match.get("score", 0)
            if isinstance(score, (int, float)) and score > 0.85:
                sanctions_agent = "IndividualSanctions" if investigation.individual_sanctions else "EntitySanctions"
                _add(
                    finding_a=f"Sanctions match scored {score:.2f} (high similarity)",
                    finding_b="Disposition marked as FALSE_POSITIVE",
                    agent_a=sanctions_agent,
                    agent_b=sanctions_agent,
                    severity=SeverityLevel.HIGH,
                    guidance="High match score contradicts FALSE_POSITIVE disposition. "
                             "Residual risk remains. Verify with additional identity documents.",
                )
                break  # One alert per case is enough

    # Rule: PEP NOT_PEP but adverse media references political positions → HIGH
    if pep_level == PEPLevel.NOT_PEP and adverse_categories:
        political_keywords = {"political", "government", "corruption", "bribery"}
        political_categories = [c for c in adverse_categories if any(kw in c.lower() for kw in political_keywords)]
        if political_categories:
            media_agent = "IndividualAdverseMedia" if investigation.individual_adverse_media else "BusinessAdverseMedia"
            _add(
                finding_a="PEP classification: NOT_PEP",
                finding_b=f"Adverse media references political activity: {', '.join(political_categories)}",
                agent_a="PEPDetection",
                agent_b=media_agent,
                severity=SeverityLevel.HIGH,
                guidance="Media references to political positions may indicate undisclosed PEP status. "
                         "Re-evaluate PEP classification with additional screening.",
            )

    # Rule: Entity verification discrepancies → MEDIUM
    if investigation.entity_verification and investigation.entity_verification.discrepancies:
        for disc in investigation.entity_verification.discrepancies:
            _add(
                finding_a=f"Entity verification discrepancy: {disc[:80]}",
                finding_b="Other agent findings on same entity",
                agent_a="EntityVerification",
                agent_b="Multiple",
                severity=SeverityLevel.MEDIUM,
                guidance="Verify entity details against primary registry sources.",
            )

    return contradictions


# =============================================================================
# Facet 3: Confidence Degradation
# =============================================================================

def _assess_confidence(evidence_store: list[dict]) -> ConfidenceDegradationAlert:
    """Count V/S/I/U evidence, compute percentages and letter grade."""
    counts = {"V": 0, "S": 0, "I": 0, "U": 0}
    total = 0

    for er in evidence_store:
        level = er.get("evidence_level", "U")
        if level in counts:
            counts[level] += 1
            total += 1
        else:
            counts["U"] += 1
            total += 1

    if total == 0:
        return ConfidenceDegradationAlert(
            overall_confidence_grade="F",
            degraded=True,
            follow_up_actions=["No evidence records found — investigation may have failed"],
        )

    v_pct = counts["V"] / total * 100
    s_pct = counts["S"] / total * 100
    i_pct = counts["I"] / total * 100
    u_pct = counts["U"] / total * 100
    strong_pct = (counts["V"] + counts["S"]) / total * 100

    # Letter grade
    if strong_pct >= 70:
        grade = "A"
    elif strong_pct >= 50:
        grade = "B"
    elif strong_pct >= 30:
        grade = "C"
    elif strong_pct >= 15:
        grade = "D"
    else:
        grade = "F"

    degraded = grade in ("C", "D", "F")

    # Build follow-up actions
    follow_up: list[str] = []
    if degraded:
        # Find which agents contributed the most I/U evidence
        agent_iu: dict[str, int] = {}
        for er in evidence_store:
            level = er.get("evidence_level", "U")
            if level in ("I", "U"):
                agent = er.get("source_name", "unknown")
                agent_iu[agent] = agent_iu.get(agent, 0) + 1

        for agent, count in sorted(agent_iu.items(), key=lambda x: -x[1])[:3]:
            follow_up.append(f"Agent '{agent}' produced {count} inferred/unknown records — "
                             f"consider re-running with additional search terms")

        if grade in ("D", "F"):
            follow_up.append("Request primary documentation from client to verify key claims")

        if grade == "F":
            follow_up.append("Consider escalating — evidence base is insufficient for confident decision")

    return ConfidenceDegradationAlert(
        overall_confidence_grade=grade,
        verified_pct=round(v_pct, 1),
        sourced_pct=round(s_pct, 1),
        inferred_pct=round(i_pct, 1),
        unknown_pct=round(u_pct, 1),
        degraded=degraded,
        follow_up_actions=follow_up,
    )


# =============================================================================
# Facet 4: Regulatory Mapping Per Finding
# =============================================================================

def _map_regulations_to_findings(
    evidence_store: list[dict],
    plan: InvestigationPlan,
    investigation: InvestigationResults,
) -> list[FindingWithRegulations]:
    """Rule-based tagging of regulatory obligations per evidence record."""
    mappings: list[FindingWithRegulations] = []

    # Pre-compute flags from investigation
    has_us_nexus = False
    has_non_ca_tax = False
    fatf_black = []
    fatf_grey = []

    if investigation.jurisdiction_risk:
        fatf_black = investigation.jurisdiction_risk.fatf_black_list
        fatf_grey = investigation.jurisdiction_risk.fatf_grey_list

    if investigation.fatca_crs:
        fatca = investigation.fatca_crs.get("fatca", {})
        has_us_nexus = fatca.get("us_person", False) or bool(fatca.get("indicia"))
        crs = investigation.fatca_crs.get("crs", {})
        has_non_ca_tax = crs.get("reporting_required", False)

    for er in evidence_store:
        eid = er.get("evidence_id", "")
        claim = er.get("claim", "")
        source = er.get("source_name", "")
        disp = er.get("disposition", "")
        tags: list[RegulatoryTag] = []

        claim_lower = claim.lower()

        # Sanctions match → FINTRAC PCMLTFA s.11.41
        if disp in ("POTENTIAL_MATCH", "CONFIRMED_MATCH") and "sanction" in source.lower():
            tags.append(RegulatoryTag(
                regulation="FINTRAC PCMLTFA s.11.41",
                obligation="Suspicious Transaction Report consideration",
                trigger_description="Sanctions screening match detected",
                evidence_id=eid,
                filing_required=True,
                timeline="30 days from detection",
            ))

        # Confirmed terrorist match → FINTRAC PCMLTFA s.11.42
        if disp == "CONFIRMED_MATCH" and any(kw in claim_lower for kw in ("terrorist", "terrorism")):
            tags.append(RegulatoryTag(
                regulation="FINTRAC PCMLTFA s.11.42",
                obligation="Terrorist Property Report — IMMEDIATE",
                trigger_description="Confirmed terrorist financing match",
                evidence_id=eid,
                filing_required=True,
                timeline="Immediately upon detection",
            ))

        # PEP detected → FINTRAC PCMLTFA Part 1.1
        if "pep" in source.lower() and disp not in ("CLEAR", "FALSE_POSITIVE"):
            pep_level = None
            if investigation.pep_classification:
                pep_level = investigation.pep_classification.detected_level

            if pep_level and pep_level != PEPLevel.NOT_PEP:
                tags.append(RegulatoryTag(
                    regulation="FINTRAC PCMLTFA Part 1.1",
                    obligation="Enhanced Due Diligence — source of wealth verification",
                    trigger_description=f"PEP classification: {pep_level.value}",
                    evidence_id=eid,
                    filing_required=False,
                    timeline="Before account activation",
                ))

                # Foreign PEP → CIRO 3202 senior management approval
                if pep_level == PEPLevel.FOREIGN_PEP:
                    tags.append(RegulatoryTag(
                        regulation="CIRO 3202",
                        obligation="Senior management approval required",
                        trigger_description="Foreign PEP detected",
                        evidence_id=eid,
                        filing_required=False,
                        timeline="Before account activation",
                    ))

        # Adverse media: financial crime categories → FINTRAC STR consideration
        financial_crime_keywords = {"fraud", "money_laundering", "money laundering",
                                    "financial_crime", "embezzlement", "tax_evasion"}
        if "adverse" in source.lower() or "media" in source.lower():
            for kw in financial_crime_keywords:
                if kw in claim_lower:
                    tags.append(RegulatoryTag(
                        regulation="FINTRAC PCMLTFA s.11.41",
                        obligation="STR consideration — financial crime media",
                        trigger_description=f"Adverse media references: {kw}",
                        evidence_id=eid,
                        filing_required=True,
                        timeline="30 days from detection",
                    ))
                    break  # One tag per evidence for this rule

            # Adverse media: sanctions_evasion + US nexus → OFAC
            if "sanctions_evasion" in claim_lower or "sanction" in claim_lower:
                if has_us_nexus:
                    tags.append(RegulatoryTag(
                        regulation="OFAC SDN / 50% Rule",
                        obligation="OFAC compliance review — US nexus with sanctions evasion media",
                        trigger_description="Sanctions evasion media + US nexus",
                        evidence_id=eid,
                        filing_required=True,
                        timeline="Immediate review",
                    ))

        # Jurisdiction-based tagging
        if "jurisdiction" in source.lower():
            for j in fatf_black:
                if j.lower() in claim_lower:
                    tags.append(RegulatoryTag(
                        regulation="FINTRAC Ministerial Directive",
                        obligation="Countermeasures required — FATF black list jurisdiction",
                        trigger_description=f"FATF black list: {j}",
                        evidence_id=eid,
                        filing_required=False,
                        timeline="Before account activation",
                    ))

            for j in fatf_grey:
                if j.lower() in claim_lower:
                    tags.append(RegulatoryTag(
                        regulation="FINTRAC PCMLTFA s.9.6",
                        obligation="Enhanced Due Diligence — FATF grey list jurisdiction",
                        trigger_description=f"FATF grey list: {j}",
                        evidence_id=eid,
                        filing_required=False,
                        timeline="Before account activation",
                    ))

        # FATCA/CRS tagging
        if has_us_nexus and "fatca" in source.lower():
            tags.append(RegulatoryTag(
                regulation="FATCA Part XVIII ITA",
                obligation="US person reporting",
                trigger_description="US person or US indicia detected",
                evidence_id=eid,
                filing_required=True,
                timeline="Annual reporting cycle",
            ))

        if has_non_ca_tax and "crs" in source.lower():
            tags.append(RegulatoryTag(
                regulation="CRS Part XIX ITA",
                obligation="Non-Canadian tax residency reporting",
                trigger_description="Non-CA tax residency detected",
                evidence_id=eid,
                filing_required=True,
                timeline="Annual reporting cycle",
            ))

        # Ownership opacity → CIRO 3202(2)(c)
        if ("ubo" in source.lower() or "verification" in source.lower()) and \
                any(kw in claim_lower for kw in ("opaque", "unclear", "unverified", "not verified", "discrepanc")):
            tags.append(RegulatoryTag(
                regulation="CIRO 3202(2)(c)",
                obligation="Suitability — beneficial ownership verification",
                trigger_description="Ownership structure opacity detected",
                evidence_id=eid,
                filing_required=False,
                timeline="Before account activation",
            ))

        if tags:
            mappings.append(FindingWithRegulations(
                evidence_id=eid,
                claim=claim,
                source_name=source,
                regulatory_tags=tags,
            ))

    return mappings


# =============================================================================
# Facet 5: Batch Analytics
# =============================================================================

def _compute_batch_analytics(analytics_dir: Path, window_days: int = 7) -> BatchAnalytics:
    """Read JSONL case signatures, detect patterns within rolling window."""
    jsonl_path = analytics_dir / "case_signatures.jsonl"
    if not jsonl_path.exists():
        return BatchAnalytics()

    # Load signatures within window
    cutoff = datetime.now() - timedelta(days=window_days)
    signatures: list[dict] = []

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    sig = json.loads(line)
                    ts = sig.get("timestamp", "")
                    if isinstance(ts, str):
                        try:
                            sig_time = datetime.fromisoformat(ts)
                        except ValueError:
                            sig_time = datetime.now()
                    else:
                        sig_time = datetime.now()

                    if sig_time >= cutoff:
                        signatures.append(sig)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"Could not read batch analytics: {e}")
        return BatchAnalytics()

    if not signatures:
        return BatchAnalytics()

    patterns: list[BatchPattern] = []

    # Pattern: Jurisdiction cluster (≥ 3 cases share same non-CA jurisdiction)
    jurisdiction_counter: dict[str, list[str]] = {}
    for sig in signatures:
        for j in sig.get("jurisdictions", []):
            if j.upper() not in ("CANADA", "CA"):
                jurisdiction_counter.setdefault(j, []).append(sig.get("client_id", ""))

    for jurisdiction, case_ids in jurisdiction_counter.items():
        if len(case_ids) >= 3:
            patterns.append(BatchPattern(
                pattern_type="jurisdiction_cluster",
                description=f"{len(case_ids)} cases involve jurisdiction: {jurisdiction}",
                count=len(case_ids),
                case_ids=case_ids,
                significance="Multiple clients from same high-risk jurisdiction may indicate coordinated activity",
            ))

    # Pattern: Industry cluster (≥ 3 cases in same industry)
    industry_counter: dict[str, list[str]] = {}
    for sig in signatures:
        for ind in sig.get("industries", []):
            industry_counter.setdefault(ind, []).append(sig.get("client_id", ""))

    for industry, case_ids in industry_counter.items():
        if len(case_ids) >= 3:
            patterns.append(BatchPattern(
                pattern_type="industry_cluster",
                description=f"{len(case_ids)} cases in industry: {industry}",
                count=len(case_ids),
                case_ids=case_ids,
                significance="Cluster of clients in same industry may warrant sector-level review",
            ))

    # Pattern: Regulation surge (≥ 5 cases trigger same regulation)
    reg_counter: dict[str, list[str]] = {}
    for sig in signatures:
        for reg in sig.get("regulations_triggered", []):
            reg_counter.setdefault(reg, []).append(sig.get("client_id", ""))

    for reg, case_ids in reg_counter.items():
        if len(case_ids) >= 5:
            patterns.append(BatchPattern(
                pattern_type="regulation_surge",
                description=f"{len(case_ids)} cases trigger regulation: {reg}",
                count=len(case_ids),
                case_ids=case_ids,
                significance="High volume of cases triggering same regulation may indicate systemic exposure",
            ))

    # Pattern: Risk trend (average score rising vs previous window)
    current_scores = [s.get("risk_score", 0) for s in signatures]
    if current_scores:
        current_avg = sum(current_scores) / len(current_scores)

        # Load previous window
        prev_cutoff = cutoff - timedelta(days=window_days)
        prev_signatures = []
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sig = json.loads(line)
                        ts = sig.get("timestamp", "")
                        if isinstance(ts, str):
                            try:
                                sig_time = datetime.fromisoformat(ts)
                            except ValueError:
                                continue
                        else:
                            continue
                        if prev_cutoff <= sig_time < cutoff:
                            prev_signatures.append(sig)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            prev_signatures = []

        if prev_signatures:
            prev_scores = [s.get("risk_score", 0) for s in prev_signatures]
            prev_avg = sum(prev_scores) / len(prev_scores)
            if current_avg > prev_avg * 1.25:  # 25% increase threshold
                patterns.append(BatchPattern(
                    pattern_type="risk_trend",
                    description=f"Average risk score increased from {prev_avg:.0f} to {current_avg:.0f} "
                                f"({((current_avg - prev_avg) / prev_avg * 100):.0f}% increase)",
                    count=len(current_scores),
                    case_ids=[s.get("client_id", "") for s in signatures],
                    significance="Rising average risk scores may indicate changing client mix or emerging threats",
                ))

    return BatchAnalytics(
        total_cases_in_window=len(signatures),
        patterns=patterns,
    )
