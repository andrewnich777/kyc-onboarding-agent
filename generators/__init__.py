"""
KYC Client Onboarding Intelligence System - Generator exports.
"""

from generators.compliance_officer_brief import generate_compliance_brief
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

__all__ = [
    "generate_compliance_brief",
    "generate_onboarding_summary",
    "recommend_decision",
    "generate_kyc_pdf",
    "BriefDeduplicator",
    "deduplicate_items",
    "deduplicate_claims",
    "deduplicate_by_field",
    "deduplicate_evidence_urls",
]
