"""
KYC Client Onboarding Intelligence System - Generator exports.
"""

from generators.aml_operations_brief import generate_aml_operations_brief
from generators.risk_assessment_brief import generate_risk_assessment_brief
from generators.regulatory_actions_brief import generate_regulatory_actions_brief
from generators.onboarding_summary import generate_onboarding_summary
from generators.recommendation_engine import recommend_decision
from generators.pdf_generator import generate_kyc_pdf
from generators.dedup import (
    BriefDeduplicator,
    deduplicate_items,
    deduplicate_claims,
    deduplicate_by_field,
    deduplicate_evidence_urls,
)

# Backward compatibility — alias old name to new AML operations brief
from generators.compliance_officer_brief import generate_compliance_brief

__all__ = [
    "generate_aml_operations_brief",
    "generate_risk_assessment_brief",
    "generate_regulatory_actions_brief",
    "generate_onboarding_summary",
    "generate_compliance_brief",
    "recommend_decision",
    "generate_kyc_pdf",
    "BriefDeduplicator",
    "deduplicate_items",
    "deduplicate_claims",
    "deduplicate_by_field",
    "deduplicate_evidence_urls",
]
