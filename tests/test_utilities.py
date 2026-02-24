"""Tests for deterministic utility functions.

Each utility is pure Python with no API calls.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    IndividualClient, BusinessClient, RiskAssessment, RiskLevel,
    InvestigationResults, SanctionsResult, PEPClassification,
    DispositionStatus, PEPLevel, AdverseMediaResult, AdverseMediaLevel,
)


class TestIdVerification:
    def test_individual_verification(self, individual_client_low):
        from utilities.id_verification import assess_id_verification
        result = assess_id_verification(individual_client_low)
        assert isinstance(result, dict)
        assert "method" in result or "requirements" in result
        assert "status" in result

    def test_business_verification(self, business_client_critical):
        from utilities.id_verification import assess_id_verification
        result = assess_id_verification(business_client_critical)
        assert isinstance(result, dict)
        assert "requirements" in result
        # Business should require incorporation documents
        reqs = result.get("requirements", [])
        assert len(reqs) > 0


class TestSuitability:
    def test_case1_suitability(self, individual_client_low):
        from utilities.suitability import assess_suitability
        result = assess_suitability(individual_client_low)
        assert isinstance(result, dict)
        assert "suitable" in result
        # Sarah Thompson should be suitable — stable income, reasonable investment
        assert result["suitable"] is True

    def test_case2_suitability(self, individual_client_pep):
        from utilities.suitability import assess_suitability
        result = assess_suitability(individual_client_pep)
        assert isinstance(result, dict)
        assert "suitable" in result

    def test_business_suitability(self, business_client_critical):
        from utilities.suitability import assess_suitability
        result = assess_suitability(business_client_critical)
        assert isinstance(result, dict)


class TestIndividualFATCACRS:
    def test_case1_no_fatca(self, individual_client_low):
        from utilities.individual_fatca_crs import classify_individual_fatca_crs
        result = classify_individual_fatca_crs(individual_client_low)
        assert isinstance(result, dict)
        assert "fatca" in result
        # Canadian, non-US person → no FATCA reporting
        fatca = result["fatca"]
        assert fatca.get("us_person") is False or fatca.get("reporting_required") is False

    def test_case2_crs_triggered(self, individual_client_pep):
        from utilities.individual_fatca_crs import classify_individual_fatca_crs
        result = classify_individual_fatca_crs(individual_client_pep)
        assert isinstance(result, dict)
        assert "crs" in result
        # Hong Kong tax residency → CRS reporting
        crs = result["crs"]
        crs_jurisdictions = crs.get("reportable_jurisdictions", [])
        assert len(crs_jurisdictions) > 0 or crs.get("reporting_required") is True


class TestEntityFATCACRS:
    def test_case3_entity_classification(self, business_client_critical):
        from utilities.entity_fatca_crs import classify_entity_fatca_crs
        result = classify_entity_fatca_crs(business_client_critical)
        assert isinstance(result, dict)
        assert "entity_classification" in result
        # Trading corp should be Active NFFE or similar
        classification = result["entity_classification"]
        assert classification is not None


class TestEDDRequirements:
    def test_case1_no_edd(self, individual_client_low):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = assess_edd_requirements(individual_client_low, risk)
        assert isinstance(result, dict)
        assert "edd_required" in result
        # LOW risk, no flags → likely no EDD
        assert result["edd_required"] is False

    def test_case2_edd_required(self, individual_client_pep):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = assess_edd_requirements(individual_client_pep, risk)
        assert isinstance(result, dict)
        assert result["edd_required"] is True
        assert len(result.get("triggers", [])) > 0
        assert len(result.get("measures", [])) > 0

    def test_case3_edd_required(self, business_client_critical):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=45, risk_level=RiskLevel.HIGH)
        result = assess_edd_requirements(business_client_critical, risk)
        assert isinstance(result, dict)
        assert result["edd_required"] is True


class TestComplianceActions:
    def test_case1_minimal_actions(self, individual_client_low):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = determine_compliance_actions(individual_client_low, risk)
        assert isinstance(result, dict)
        assert "reports" in result
        assert "actions" in result

    def test_case2_actions(self, individual_client_pep):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = determine_compliance_actions(individual_client_pep, risk)
        assert isinstance(result, dict)
        # CRS reporting for Hong Kong tax residency
        reports = result.get("reports", [])
        # PEP with Hong Kong tax residency should trigger CRS reporting at minimum
        assert isinstance(reports, list)

    def test_case3_actions(self, business_client_critical):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=45, risk_level=RiskLevel.HIGH)
        result = determine_compliance_actions(business_client_critical, risk)
        assert isinstance(result, dict)
        assert "escalations" in result


class TestBusinessRiskAssessment:
    def test_case3_risk_factors(self, business_client_critical):
        from utilities.business_risk_assessment import assess_business_risk_factors
        result = assess_business_risk_factors(business_client_critical)
        assert isinstance(result, dict)
        assert "risk_factors" in result
        assert "ownership_analysis" in result
        assert "operational_analysis" in result
        assert "overall_narrative" in result
        # Should identify high-risk factors
        assert len(result["risk_factors"]) > 0

    def test_narrative_not_empty(self, business_client_critical):
        from utilities.business_risk_assessment import assess_business_risk_factors
        result = assess_business_risk_factors(business_client_critical)
        assert len(result["overall_narrative"]) > 0


class TestDocumentRequirements:
    def test_individual_requirements(self, individual_client_low):
        from utilities.document_requirements import consolidate_document_requirements
        from utilities.investigation_planner import build_investigation_plan
        plan = build_investigation_plan(individual_client_low)
        # Build a minimal investigation with id_verification
        investigation = InvestigationResults()
        investigation.id_verification = {
            "method": "dual_process",
            "status": "pending",
            "requirements": ["Government-issued photo ID", "Proof of address"],
        }
        result = consolidate_document_requirements(individual_client_low, plan, investigation)
        assert isinstance(result, dict)
        assert "requirements" in result
        assert isinstance(result["requirements"], list)
        assert len(result["requirements"]) > 0
        # Each requirement should have document and regulatory_basis keys
        for req in result["requirements"]:
            assert "document" in req
            assert "regulatory_basis" in req

    def test_business_requirements(self, business_client_critical):
        from utilities.document_requirements import consolidate_document_requirements
        from utilities.investigation_planner import build_investigation_plan
        plan = build_investigation_plan(business_client_critical)
        investigation = InvestigationResults()
        investigation.id_verification = {
            "method": "corporate_registry",
            "status": "pending",
            "requirements": [],
        }
        result = consolidate_document_requirements(business_client_critical, plan, investigation)
        assert isinstance(result, dict)
        assert "requirements" in result
        # Business should have entity verification docs
        docs = [r["document"].lower() for r in result["requirements"]]
        assert any("incorporation" in d for d in docs)
        assert "total_required" in result
        assert "total_outstanding" in result


class TestComplianceActionsDateCalc:
    def test_computed_deadline_present(self, individual_client_low):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = determine_compliance_actions(individual_client_low, risk)
        timelines = result.get("timelines", {})
        # risk_review should have computed_deadline
        assert "risk_review" in timelines
        assert "computed_deadline" in timelines["risk_review"]
        # Verify it's a valid date string
        deadline = timelines["risk_review"]["computed_deadline"]
        assert len(deadline) == 10  # YYYY-MM-DD format

    def test_report_deadlines_computed(self, individual_client_pep):
        from utilities.compliance_actions import determine_compliance_actions
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = determine_compliance_actions(individual_client_pep, risk)
        timelines = result.get("timelines", {})
        # Any report timeline entry should have computed_deadline
        for key, tl in timelines.items():
            if key in ("STR", "TPR", "FATCA", "CRS", "LCTR"):
                assert "computed_deadline" in tl, f"Missing computed_deadline for {key}"


class TestEDDMonitoringSchedule:
    def test_monitoring_schedule_present(self, individual_client_low):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=5, risk_level=RiskLevel.LOW)
        result = assess_edd_requirements(individual_client_low, risk)
        assert "monitoring_schedule" in result
        schedule = result["monitoring_schedule"]
        assert "frequency" in schedule
        assert "next_review_date" in schedule
        assert "review_interval_days" in schedule
        # Verify next_review_date is a valid date string
        assert len(schedule["next_review_date"]) == 10

    def test_high_risk_monitoring_frequency(self, individual_client_pep):
        from utilities.edd_requirements import assess_edd_requirements
        risk = RiskAssessment(total_score=52, risk_level=RiskLevel.HIGH)
        result = assess_edd_requirements(individual_client_pep, risk)
        schedule = result["monitoring_schedule"]
        # HIGH risk should be quarterly (90 days)
        assert schedule["frequency"] == "quarterly"
        assert schedule["review_interval_days"] == 90


class TestReferenceData:
    def test_fatf_lists_populated(self):
        from utilities.reference_data import FATF_GREY_LIST, FATF_BLACK_LIST
        assert len(FATF_GREY_LIST) > 0
        assert len(FATF_BLACK_LIST) > 0

    def test_high_risk_industries(self):
        from utilities.reference_data import HIGH_RISK_INDUSTRIES
        assert len(HIGH_RISK_INDUSTRIES) > 0

    def test_offshore_jurisdictions(self):
        from utilities.reference_data import OFFSHORE_JURISDICTIONS
        assert len(OFFSHORE_JURISDICTIONS) > 0

    def test_source_of_funds_risk(self):
        from utilities.reference_data import SOURCE_OF_FUNDS_RISK
        assert "employment_income" in SOURCE_OF_FUNDS_RISK
        assert SOURCE_OF_FUNDS_RISK["employment_income"] == 0
