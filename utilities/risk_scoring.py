"""
Risk scoring engine for KYC client assessment.

Two-pass design:
- Pass 1 (Stage 1): Preliminary score from client intake data alone
- Pass 2 (Stage 3): Revised score incorporating UBO cascade + synthesis findings

Tiers: 0-15 LOW, 16-35 MEDIUM, 36-60 HIGH, 61+ CRITICAL
"""

from models import (
    RiskAssessment, RiskFactor, RiskLevel,
    IndividualClient, BusinessClient, BeneficialOwner,
    ClientType,
)
from utilities.reference_data import (
    FATF_GREY_LIST, FATF_BLACK_LIST, OFAC_SANCTIONED_COUNTRIES,
    HIGH_RISK_INDUSTRIES, OFFSHORE_JURISDICTIONS,
    HIGH_RISK_OCCUPATIONS, SOURCE_OF_FUNDS_RISK,
)


def _score_to_risk_level(score: int) -> RiskLevel:
    """Convert numeric score to risk level."""
    if score <= 15:
        return RiskLevel.LOW
    elif score <= 35:
        return RiskLevel.MEDIUM
    elif score <= 60:
        return RiskLevel.HIGH
    else:
        return RiskLevel.CRITICAL


def calculate_individual_risk_score(
    client: IndividualClient,
    ubo_scores: dict[str, int] | None = None,
) -> RiskAssessment:
    """
    Calculate risk score for an individual client.
    
    Args:
        client: Individual client data
        ubo_scores: Optional dict of {ubo_name: score} from cascade (Stage 3 only)
    
    Returns:
        RiskAssessment with total score, level, and contributing factors
    """
    factors = []
    
    # PEP risk
    if client.pep_self_declaration:
        pep_details = (client.pep_details or "").lower()
        if any(kw in pep_details for kw in ["foreign", "international"]):
            factors.append(RiskFactor(factor="Foreign PEP (self-declared)", points=40, category="pep", source="client_intake"))
        elif any(kw in pep_details for kw in ["head of international", "hio"]):
            factors.append(RiskFactor(factor="Head of International Organization", points=30, category="pep", source="client_intake"))
        else:
            factors.append(RiskFactor(factor="Domestic PEP (self-declared)", points=25, category="pep", source="client_intake"))
    
    # Citizenship risk
    citizenship = (client.citizenship or "").strip()
    if citizenship in FATF_BLACK_LIST:
        factors.append(RiskFactor(factor=f"Citizenship: {citizenship} (FATF black list)", points=30, category="citizenship", source="client_intake"))
    elif citizenship in FATF_GREY_LIST:
        factors.append(RiskFactor(factor=f"Citizenship: {citizenship} (FATF grey list)", points=15, category="citizenship", source="client_intake"))
    elif citizenship in OFAC_SANCTIONED_COUNTRIES:
        factors.append(RiskFactor(factor=f"Citizenship: {citizenship} (OFAC sanctioned)", points=20, category="citizenship", source="client_intake"))
    
    # Country of birth
    cob = (client.country_of_birth or "").strip()
    if cob and cob != citizenship:
        if cob in FATF_BLACK_LIST:
            factors.append(RiskFactor(factor=f"Country of birth: {cob} (FATF black list)", points=15, category="country_of_birth", source="client_intake"))
        elif cob in FATF_GREY_LIST:
            factors.append(RiskFactor(factor=f"Country of birth: {cob} (FATF grey list)", points=8, category="country_of_birth", source="client_intake"))
    
    # Occupation risk
    if client.employment and client.employment.occupation:
        occ = client.employment.occupation.lower().replace(" ", "_")
        if occ in HIGH_RISK_OCCUPATIONS or any(hr in occ for hr in HIGH_RISK_OCCUPATIONS):
            factors.append(RiskFactor(factor=f"High-risk occupation: {client.employment.occupation}", points=10, category="occupation", source="client_intake"))
    
    # Source of funds
    if client.source_of_funds:
        sof_key = client.source_of_funds.lower().replace(" ", "_")
        sof_points = SOURCE_OF_FUNDS_RISK.get(sof_key, 0)
        if sof_points > 0:
            factors.append(RiskFactor(factor=f"Source of funds: {client.source_of_funds}", points=sof_points, category="source_of_funds", source="client_intake"))
    
    # Wealth/income ratio
    if client.net_worth and client.annual_income and client.annual_income > 0:
        ratio = client.net_worth / client.annual_income
        if ratio > 50:
            factors.append(RiskFactor(factor=f"Wealth/income ratio: {ratio:.0f}x (very high)", points=15, category="wealth_ratio", source="client_intake"))
        elif ratio > 20:
            factors.append(RiskFactor(factor=f"Wealth/income ratio: {ratio:.0f}x (elevated)", points=8, category="wealth_ratio", source="client_intake"))
    
    # US person
    if client.us_person:
        factors.append(RiskFactor(factor="US person — FATCA reporting required", points=5, category="us_nexus", source="client_intake"))
    
    # Tax residencies
    non_ca_residencies = [t for t in client.tax_residencies if t.lower() not in ("canada", "ca")]
    if non_ca_residencies:
        for tr in non_ca_residencies:
            if tr in FATF_BLACK_LIST:
                factors.append(RiskFactor(factor=f"Tax residency: {tr} (FATF black list)", points=20, category="tax_residency", source="client_intake"))
            elif tr in FATF_GREY_LIST:
                factors.append(RiskFactor(factor=f"Tax residency: {tr} (FATF grey list)", points=10, category="tax_residency", source="client_intake"))
            elif tr in OFFSHORE_JURISDICTIONS:
                factors.append(RiskFactor(factor=f"Tax residency: {tr} (offshore jurisdiction)", points=8, category="tax_residency", source="client_intake"))
            else:
                factors.append(RiskFactor(factor=f"Non-Canadian tax residency: {tr}", points=3, category="tax_residency", source="client_intake"))
    
    # Third-party determination
    if client.third_party_determination:
        factors.append(RiskFactor(factor="Third-party account determination", points=15, category="third_party", source="client_intake"))
    
    total = sum(f.points for f in factors)
    level = _score_to_risk_level(total)
    
    return RiskAssessment(
        total_score=total,
        risk_level=level,
        risk_factors=factors,
        is_preliminary=ubo_scores is None,
        score_history=[{"stage": "intake", "score": total, "level": level.value}],
    )


def calculate_business_risk_score(
    client: BusinessClient,
    ubo_scores: dict[str, int] | None = None,
) -> RiskAssessment:
    """
    Calculate risk score for a business client.
    
    When ubo_scores is None (Stage 1): skips UBO risk factor.
    When ubo_scores is provided (Stage 3): adds max(ubo_scores) * 0.5.
    """
    factors = []
    
    # Entity age
    if client.incorporation_date:
        try:
            from datetime import datetime
            inc_date = datetime.strptime(client.incorporation_date, "%Y-%m-%d")
            years = (datetime.now() - inc_date).days / 365.25
            if years < 1:
                factors.append(RiskFactor(factor="Entity age < 1 year (shell company risk)", points=15, category="entity_age", source="client_intake"))
            elif years < 3:
                factors.append(RiskFactor(factor="Entity age < 3 years", points=8, category="entity_age", source="client_intake"))
        except (ValueError, TypeError):
            pass
    
    # Industry risk
    if client.industry:
        industry_key = client.industry.lower().replace(" ", "_").replace("/", "_")
        if industry_key in HIGH_RISK_INDUSTRIES or any(hr in industry_key for hr in HIGH_RISK_INDUSTRIES):
            factors.append(RiskFactor(factor=f"High-risk industry: {client.industry}", points=15, category="industry", source="client_intake"))
    
    # Countries of operation
    for country in client.countries_of_operation:
        if country.lower() in ("canada", "ca"):
            continue
        if country in FATF_BLACK_LIST:
            factors.append(RiskFactor(factor=f"Operations in {country} (FATF black list)", points=25, category="jurisdiction", source="client_intake"))
        elif country in FATF_GREY_LIST:
            factors.append(RiskFactor(factor=f"Operations in {country} (FATF grey list)", points=12, category="jurisdiction", source="client_intake"))
        elif country in OFAC_SANCTIONED_COUNTRIES:
            factors.append(RiskFactor(factor=f"Operations in {country} (OFAC sanctioned)", points=15, category="jurisdiction", source="client_intake"))
        elif country in OFFSHORE_JURISDICTIONS:
            factors.append(RiskFactor(factor=f"Operations in {country} (offshore jurisdiction)", points=8, category="jurisdiction", source="client_intake"))
    
    # Transaction volume
    if client.expected_transaction_volume:
        if client.expected_transaction_volume > 10_000_000:
            factors.append(RiskFactor(factor="Transaction volume > $10M", points=10, category="transaction_volume", source="client_intake"))
        elif client.expected_transaction_volume > 1_000_000:
            factors.append(RiskFactor(factor="Transaction volume > $1M", points=5, category="transaction_volume", source="client_intake"))
    
    # Ownership complexity
    if len(client.beneficial_owners) > 4:
        factors.append(RiskFactor(factor=f"Complex ownership ({len(client.beneficial_owners)} beneficial owners)", points=10, category="ownership_complexity", source="client_intake"))
    elif len(client.beneficial_owners) == 0:
        factors.append(RiskFactor(factor="No beneficial owners declared", points=15, category="ownership_complexity", source="client_intake"))
    
    # US nexus
    if client.us_nexus:
        factors.append(RiskFactor(factor="US nexus — FATCA/OFAC compliance required", points=10, category="us_nexus", source="client_intake"))
    
    # Incorporation jurisdiction
    if client.incorporation_jurisdiction:
        if client.incorporation_jurisdiction in OFFSHORE_JURISDICTIONS:
            factors.append(RiskFactor(factor=f"Incorporated in {client.incorporation_jurisdiction} (offshore)", points=12, category="incorporation", source="client_intake"))
    
    # UBO cascade scores (Pass 2 only)
    if ubo_scores:
        max_ubo_score = max(ubo_scores.values()) if ubo_scores else 0
        if max_ubo_score > 0:
            ubo_contribution = int(max_ubo_score * 0.5)
            max_ubo_name = max(ubo_scores, key=ubo_scores.get)
            factors.append(RiskFactor(
                factor=f"UBO cascade: {max_ubo_name} (score {max_ubo_score} x 0.5)",
                points=ubo_contribution,
                category="ubo_cascade",
                source="synthesis",
            ))
    
    # Third-party
    if client.third_party_determination:
        factors.append(RiskFactor(factor="Third-party account determination", points=15, category="third_party", source="client_intake"))
    
    total = sum(f.points for f in factors)
    level = _score_to_risk_level(total)
    
    return RiskAssessment(
        total_score=total,
        risk_level=level,
        risk_factors=factors,
        is_preliminary=ubo_scores is None,
        score_history=[{"stage": "intake", "score": total, "level": level.value}],
    )


def revise_risk_score(
    preliminary: RiskAssessment,
    ubo_scores: dict[str, int] | None = None,
    synthesis_factors: list[RiskFactor] | None = None,
) -> RiskAssessment:
    """
    Revise risk score with UBO cascade results and synthesis findings.
    Called by Stage 3 pipeline.
    """
    factors = list(preliminary.risk_factors)
    
    # Add UBO cascade contribution
    if ubo_scores:
        max_ubo_score = max(ubo_scores.values()) if ubo_scores else 0
        if max_ubo_score > 0:
            ubo_contribution = int(max_ubo_score * 0.5)
            max_ubo_name = max(ubo_scores, key=ubo_scores.get)
            factors.append(RiskFactor(
                factor=f"UBO cascade: {max_ubo_name} (score {max_ubo_score} x 0.5)",
                points=ubo_contribution,
                category="ubo_cascade",
                source="synthesis",
            ))
    
    # Add synthesis-discovered factors
    if synthesis_factors:
        factors.extend(synthesis_factors)
    
    total = sum(f.points for f in factors)
    level = _score_to_risk_level(total)
    
    history = list(preliminary.score_history)
    history.append({"stage": "synthesis_revision", "score": total, "level": level.value})
    
    return RiskAssessment(
        total_score=total,
        risk_level=level,
        risk_factors=factors,
        is_preliminary=False,
        score_history=history,
    )
