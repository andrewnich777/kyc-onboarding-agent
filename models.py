"""
Pydantic models for the KYC Client Onboarding Intelligence System.

Defines all data structures for the 5-stage pipeline:
1. Intake & Classification
2. Investigation (AI agents + deterministic utilities)
3. Synthesis & Proto-Reports
4. Conversational Review
5. Final Reports
"""

from enum import Enum
from typing import Optional, Union
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# =============================================================================
# Preserved Enums (from original system)
# =============================================================================

class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SourceTier(str, Enum):
    TIER_0 = "TIER_0"  # Primary sources (government registries, official sanctions lists)
    TIER_1 = "TIER_1"  # Strong secondary (major news, regulatory databases)
    TIER_2 = "TIER_2"  # Weak sources (blogs, forums, unverified)


class EvidenceClass(str, Enum):
    """Classification of how a claim is supported."""
    VERIFIED = "V"    # URL + direct quote + Tier 0/1 source
    SOURCED = "S"     # URL + excerpt + Tier 1/2 source
    INFERRED = "I"    # Derived from signals, no direct evidence
    UNKNOWN = "U"     # Explicitly searched but not found


# =============================================================================
# KYC-Specific Enums
# =============================================================================

class ClientType(str, Enum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DispositionStatus(str, Enum):
    """Screening result disposition."""
    CLEAR = "CLEAR"
    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    CONFIRMED_MATCH = "CONFIRMED_MATCH"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    PENDING_REVIEW = "PENDING_REVIEW"


class PEPLevel(str, Enum):
    """Politically Exposed Person classification per FINTRAC."""
    NOT_PEP = "NOT_PEP"
    FOREIGN_PEP = "FOREIGN_PEP"        # Permanent - never expires
    DOMESTIC_PEP = "DOMESTIC_PEP"       # 5-year window after leaving office
    HIO = "HIO"                         # Head of International Organization - 5yr
    PEP_FAMILY = "PEP_FAMILY"           # Family member of PEP
    PEP_ASSOCIATE = "PEP_ASSOCIATE"     # Close associate of PEP


class OnboardingDecision(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL = "CONDITIONAL"
    ESCALATE = "ESCALATE"
    DECLINE = "DECLINE"


class AdverseMediaLevel(str, Enum):
    CLEAR = "CLEAR"
    LOW_CONCERN = "LOW_CONCERN"
    MATERIAL_CONCERN = "MATERIAL_CONCERN"
    HIGH_RISK = "HIGH_RISK"


# =============================================================================
# Input Models — Client Data
# =============================================================================

class Address(BaseModel):
    """Physical address."""
    street: Optional[str] = None
    city: Optional[str] = None
    province_state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "Canada"


class AccountRequest(BaseModel):
    """Account type being requested."""
    account_type: str = Field(description="e.g., 'personal_investment', 'corporate_trading'")
    investment_objectives: Optional[str] = None
    risk_tolerance: Optional[str] = None
    time_horizon: Optional[str] = None
    initial_deposit: Optional[float] = None
    expected_activity: Optional[str] = None


class EmploymentInfo(BaseModel):
    """Employment details for individual clients."""
    status: str = Field(description="employed, self_employed, retired, student, unemployed")
    employer: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    years_employed: Optional[int] = None


class BeneficialOwner(BaseModel):
    """Beneficial owner of a business entity (for UBO cascade)."""
    full_name: str
    date_of_birth: Optional[str] = None
    citizenship: Optional[str] = None
    country_of_residence: Optional[str] = None
    country_of_birth: Optional[str] = None
    ownership_percentage: float = Field(ge=0, le=100)
    role: Optional[str] = None
    pep_self_declaration: bool = False
    pep_details: Optional[str] = None
    us_person: bool = False
    tax_residencies: list[str] = Field(default_factory=list)
    address: Optional[Address] = None


class IndividualClient(BaseModel):
    """Individual client intake data — exact field names from spec."""
    client_type: ClientType = ClientType.INDIVIDUAL
    full_name: str
    date_of_birth: Optional[str] = None
    citizenship: Optional[str] = "Canada"
    country_of_residence: Optional[str] = "Canada"
    country_of_birth: Optional[str] = None
    address: Optional[Address] = None
    sin_last4: Optional[str] = None
    us_person: bool = False
    us_tin: Optional[str] = None
    tax_residencies: list[str] = Field(default_factory=lambda: ["Canada"])
    pep_self_declaration: bool = False
    pep_details: Optional[str] = None
    employment: Optional[EmploymentInfo] = None
    annual_income: Optional[float] = None
    net_worth: Optional[float] = None
    source_of_funds: Optional[str] = None
    source_of_wealth: Optional[str] = None
    intended_use: Optional[str] = None
    account_requests: list[AccountRequest] = Field(default_factory=list)
    third_party_determination: bool = False
    third_party_details: Optional[str] = None


class BusinessClient(BaseModel):
    """Business client intake data — exact field names from spec."""
    client_type: ClientType = ClientType.BUSINESS
    legal_name: str
    operating_name: Optional[str] = None
    operating_names: list[str] = Field(default_factory=list)
    business_number: Optional[str] = None
    incorporation_date: Optional[str] = None
    incorporation_jurisdiction: Optional[str] = None
    entity_type: Optional[str] = None
    business_type: Optional[str] = None
    industry: Optional[str] = None
    naics_code: Optional[str] = None
    nature_of_business: Optional[str] = None
    address: Optional[Address] = None
    countries_of_operation: list[str] = Field(default_factory=lambda: ["Canada"])
    us_nexus: bool = False
    us_nexus_details: Optional[str] = None
    us_tin: Optional[str] = None
    annual_revenue: Optional[float] = None
    expected_transaction_volume: Optional[float] = None
    expected_transaction_frequency: Optional[str] = None
    source_of_funds: Optional[str] = None
    intended_use: Optional[str] = None
    beneficial_owners: list[BeneficialOwner] = Field(default_factory=list)
    authorized_signatories: list[str] = Field(default_factory=list)
    account_requests: list[AccountRequest] = Field(default_factory=list)
    third_party_determination: bool = False


# =============================================================================
# Stage 1: Intake & Classification
# =============================================================================

class RiskFactor(BaseModel):
    """Individual risk factor contributing to overall score."""
    factor: str = Field(description="Description of the risk factor")
    points: int = Field(description="Points assigned")
    category: str = Field(description="e.g., pep, citizenship, industry, jurisdiction")
    source: str = Field(description="Where this factor was identified")


class RiskAssessment(BaseModel):
    """Risk classification result from Stage 1."""
    total_score: int = Field(default=0)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    is_preliminary: bool = Field(default=True, description="True until UBO cascade + synthesis revise it")
    score_history: list[dict] = Field(default_factory=list, description="Track score progression")


class InvestigationPlan(BaseModel):
    """Plan of which agents and utilities to run."""
    client_type: ClientType
    client_id: str
    agents_to_run: list[str] = Field(default_factory=list)
    utilities_to_run: list[str] = Field(default_factory=list)
    ubo_cascade_needed: bool = False
    ubo_names: list[str] = Field(default_factory=list)
    applicable_regulations: list[str] = Field(default_factory=list)
    preliminary_risk: RiskAssessment = Field(default_factory=RiskAssessment)


# =============================================================================
# Stage 2: Investigation Results
# =============================================================================

class EvidenceRecord(BaseModel):
    """Central evidence record — all findings flow through this."""
    evidence_id: str = Field(description="Unique identifier")
    source_type: str = Field(description="'agent' or 'utility'")
    source_name: str = Field(description="Agent/utility that produced this")
    entity_screened: str = Field(description="Name of person/entity screened")
    entity_context: Optional[str] = Field(default=None, description="Role context, e.g., 'UBO (45% owner)'")
    claim: str = Field(description="The factual finding")
    evidence_level: EvidenceClass = Field(default=EvidenceClass.UNKNOWN)
    supporting_data: list[dict] = Field(default_factory=list, description="URLs, quotes, document references")
    disposition: DispositionStatus = Field(default=DispositionStatus.PENDING_REVIEW)
    disposition_reasoning: Optional[str] = None
    confidence: Confidence = Field(default=Confidence.MEDIUM)
    timestamp: datetime = Field(default_factory=datetime.now)
    related_evidence: list[str] = Field(default_factory=list, description="IDs of related evidence records")


class SanctionsResult(BaseModel):
    """Result from sanctions screening."""
    entity_screened: str
    screening_sources: list[str] = Field(default_factory=list)
    matches: list[dict] = Field(default_factory=list, description="[{list_name, matched_name, score, details}]")
    disposition: DispositionStatus = Field(default=DispositionStatus.CLEAR)
    disposition_reasoning: Optional[str] = None
    ofac_50_percent_rule_applicable: bool = False
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


class PEPClassification(BaseModel):
    """Result from PEP detection."""
    entity_screened: str
    self_declared: bool = False
    detected_level: PEPLevel = Field(default=PEPLevel.NOT_PEP)
    positions_found: list[dict] = Field(default_factory=list, description="[{position, organization, dates, source}]")
    family_associations: list[dict] = Field(default_factory=list)
    edd_required: bool = False
    edd_expiry_date: Optional[str] = Field(default=None, description="ISO date when EDD expires (None=permanent)")
    edd_permanent: bool = Field(default=False, description="True for FOREIGN_PEP — EDD never expires")
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


class AdverseMediaResult(BaseModel):
    """Result from adverse media screening."""
    entity_screened: str
    overall_level: AdverseMediaLevel = Field(default=AdverseMediaLevel.CLEAR)
    articles_found: list[dict] = Field(default_factory=list, description="[{title, source, date, summary, category, source_tier}]")
    categories: list[str] = Field(default_factory=list, description="fraud, money_laundering, regulatory, etc.")
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


class EntityVerification(BaseModel):
    """Result from business entity verification."""
    entity_name: str
    verified_registration: bool = False
    registry_sources: list[str] = Field(default_factory=list)
    registration_details: dict = Field(default_factory=dict)
    ubo_structure_verified: bool = False
    discrepancies: list[str] = Field(default_factory=list)
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


class JurisdictionRiskResult(BaseModel):
    """Result from jurisdiction risk assessment."""
    jurisdictions_assessed: list[str] = Field(default_factory=list)
    fatf_grey_list: list[str] = Field(default_factory=list)
    fatf_black_list: list[str] = Field(default_factory=list)
    sanctions_programs: list[dict] = Field(default_factory=list)
    fintrac_directives: list[str] = Field(default_factory=list)
    overall_jurisdiction_risk: RiskLevel = Field(default=RiskLevel.LOW)
    jurisdiction_details: list[dict] = Field(default_factory=list, description="[{country, fatf_status, cpi_score, basel_aml_score}]")
    search_queries_executed: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


class InvestigationResults(BaseModel):
    """Container for all Stage 2 investigation findings."""
    # Individual screening
    individual_sanctions: Optional[SanctionsResult] = None
    pep_classification: Optional[PEPClassification] = None
    individual_adverse_media: Optional[AdverseMediaResult] = None

    # Business screening
    entity_verification: Optional[EntityVerification] = None
    entity_sanctions: Optional[SanctionsResult] = None
    business_adverse_media: Optional[AdverseMediaResult] = None

    # Shared
    jurisdiction_risk: Optional[JurisdictionRiskResult] = None

    # Utility results (stored as dicts for flexibility)
    id_verification: Optional[dict] = None
    suitability_assessment: Optional[dict] = None
    fatca_crs: Optional[dict] = None
    edd_requirements: Optional[dict] = None
    compliance_actions: Optional[dict] = None
    business_risk_assessment: Optional[dict] = None
    document_requirements: Optional[dict] = None

    # UBO cascade results (business only)
    ubo_screening: dict[str, dict] = Field(
        default_factory=dict,
        description="UBO name -> {sanctions, pep, adverse_media}"
    )


# =============================================================================
# Stage 3: Synthesis
# =============================================================================

class KYCEvidenceGraph(BaseModel):
    """Cross-referenced evidence graph from synthesis."""
    total_evidence_records: int = 0
    verified_count: int = 0
    sourced_count: int = 0
    inferred_count: int = 0
    unknown_count: int = 0
    contradictions: list[dict] = Field(default_factory=list)
    corroborations: list[dict] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class CounterArgument(BaseModel):
    """Adversarial analysis against a disposition."""
    evidence_id: str = Field(description="Evidence record being challenged")
    disposition_challenged: str = Field(description="The disposition being argued against, e.g. FALSE_POSITIVE")
    argument: str = Field(description="The strongest case against the disposition, citing evidence")
    risk_if_wrong: str = Field(description="What happens if this disposition is incorrect")
    recommended_mitigations: list[str] = Field(default_factory=list, description="Steps to reduce residual risk")


class DecisionOption(BaseModel):
    """One selectable path for the compliance officer."""
    option_id: str = Field(description="A, B, C, D etc.")
    label: str = Field(description="Short label: CLEAR, ESCALATE, REQUEST_DOCS, REJECT")
    description: str = Field(description="One-line description of what this means")
    consequences: list[str] = Field(description="Downstream regulatory/operational consequences")
    onboarding_impact: str = Field(description="What happens to the client's onboarding")
    timeline: str = Field(description="Expected time to resolution")


class DecisionPoint(BaseModel):
    """A decision the officer needs to make, with options."""
    decision_id: str
    title: str = Field(description="e.g. 'Sanctions Disposition: Alexander Petrov'")
    context_summary: str = Field(description="Brief summary of the finding")
    disposition: str = Field(description="System's recommended disposition")
    confidence: float = Field(default=0.0)
    counter_argument: CounterArgument
    options: list[DecisionOption] = Field(default_factory=list)
    officer_selection: Optional[str] = None
    officer_notes: Optional[str] = None


class KYCSynthesisOutput(BaseModel):
    """Output from Stage 3 synthesis."""
    evidence_graph: KYCEvidenceGraph = Field(default_factory=KYCEvidenceGraph)
    revised_risk_assessment: Optional[RiskAssessment] = None
    key_findings: list[str] = Field(default_factory=list)
    contradictions: list[dict] = Field(default_factory=list)
    risk_elevations: list[dict] = Field(default_factory=list, description="Factors discovered by synthesis")
    recommended_decision: OnboardingDecision = Field(default=OnboardingDecision.ESCALATE)
    decision_reasoning: str = ""
    conditions: list[str] = Field(default_factory=list, description="Conditions for CONDITIONAL approval")
    items_requiring_review: list[str] = Field(default_factory=list)
    senior_management_approval_needed: bool = False
    decision_points: list[DecisionPoint] = Field(default_factory=list)


# =============================================================================
# Stage 3.5: Review Intelligence (deterministic, between Synthesis and Review)
# =============================================================================

class SeverityLevel(str, Enum):
    """Severity levels for review intelligence findings."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    ADVISORY = "ADVISORY"


class CriticalDiscussionPoint(BaseModel):
    """A finding that demands the compliance officer's attention."""
    point_id: str
    title: str
    severity: SeverityLevel
    reason: str = Field(description="Why this requires discussion")
    evidence_ids: list[str] = Field(default_factory=list)
    source_agents: list[str] = Field(default_factory=list)
    recommended_action: str = ""


class Contradiction(BaseModel):
    """A contradiction detected between two findings or agents."""
    contradiction_id: str
    finding_a: str
    finding_b: str
    agent_a: str
    agent_b: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity: SeverityLevel = SeverityLevel.MEDIUM
    resolution_guidance: str = ""


class ConfidenceDegradationAlert(BaseModel):
    """Assessment of overall evidence quality."""
    overall_confidence_grade: str = Field(default="F", description="Letter grade A-F")
    verified_pct: float = 0.0
    sourced_pct: float = 0.0
    inferred_pct: float = 0.0
    unknown_pct: float = 0.0
    degraded: bool = False
    follow_up_actions: list[str] = Field(default_factory=list)


class RegulatoryTag(BaseModel):
    """A regulatory obligation mapped to a specific finding."""
    regulation: str
    obligation: str
    trigger_description: str = ""
    evidence_id: str = ""
    filing_required: bool = False
    timeline: str = ""


class FindingWithRegulations(BaseModel):
    """An evidence finding annotated with its regulatory implications."""
    evidence_id: str
    claim: str
    source_name: str
    regulatory_tags: list[RegulatoryTag] = Field(default_factory=list)


class BatchCaseSignature(BaseModel):
    """Compact fingerprint for cross-case analytics."""
    client_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    risk_level: str = ""
    risk_score: int = 0
    jurisdictions: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    client_type: str = ""
    regulations_triggered: list[str] = Field(default_factory=list)
    confidence_grade: str = ""
    contradictions_count: int = 0


class BatchPattern(BaseModel):
    """A pattern detected across multiple cases."""
    pattern_type: str = Field(description="jurisdiction_cluster, industry_cluster, regulation_surge, risk_trend")
    description: str
    count: int = 0
    case_ids: list[str] = Field(default_factory=list)
    significance: str = ""


class BatchAnalytics(BaseModel):
    """Cross-case pattern analytics."""
    total_cases_in_window: int = 0
    patterns: list[BatchPattern] = Field(default_factory=list)


class ReviewIntelligence(BaseModel):
    """Composite model holding all five review intelligence facets."""
    discussion_points: list[CriticalDiscussionPoint] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    confidence: ConfidenceDegradationAlert = Field(default_factory=ConfidenceDegradationAlert)
    regulatory_mappings: list[FindingWithRegulations] = Field(default_factory=list)
    batch_analytics: BatchAnalytics = Field(default_factory=BatchAnalytics)


# =============================================================================
# Stage 4: Review Session
# =============================================================================

class ReviewAction(BaseModel):
    """A single action taken during conversational review."""
    action_type: str = Field(description="query, approve_disposition, override_risk, add_note, finalize")
    query: Optional[str] = None
    response_summary: Optional[str] = None
    evidence_id: Optional[str] = None
    approved_disposition: Optional[DispositionStatus] = None
    previous_disposition: Optional[DispositionStatus] = None
    officer_note: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ReviewSession(BaseModel):
    """Record of the conversational review session."""
    client_id: str
    officer_name: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.now)
    actions: list[ReviewAction] = Field(default_factory=list)
    finalized: bool = False
    finalized_at: Optional[datetime] = None


# =============================================================================
# Final Output
# =============================================================================

class KYCOutput(BaseModel):
    """Complete KYC pipeline output."""
    client_id: str
    client_type: ClientType
    client_data: dict = Field(description="Original client intake data")
    intake_classification: InvestigationPlan
    investigation_results: InvestigationResults = Field(default_factory=InvestigationResults)
    synthesis: Optional[KYCSynthesisOutput] = None
    review_intelligence: Optional[ReviewIntelligence] = None
    review_session: Optional[ReviewSession] = None
    final_decision: Optional[OnboardingDecision] = None
    compliance_brief: str = ""
    onboarding_summary: str = ""
    aml_operations_brief: str = ""
    risk_assessment_brief: str = ""
    regulatory_actions_brief: str = ""
    onboarding_decision_brief: str = ""
    metrics: Optional[dict] = Field(default=None, description="Pipeline metrics (timing, tokens, cost)")
    generated_at: datetime = Field(default_factory=datetime.now)
    duration_seconds: float = 0.0
