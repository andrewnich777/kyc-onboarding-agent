"""
Jurisdiction Risk Assessment Agent.
Shared agent for FATF status, OFAC programs, FINTRAC directives, CRS participation.
"""

from agents.base import BaseAgent, KYC_EVIDENCE_RULES, KYC_OUTPUT_RULES, KYC_REGULATORY_CONTEXT
from models import JurisdictionRiskResult, RiskLevel, EvidenceRecord, EvidenceClass, DispositionStatus, Confidence
from logger import get_logger

logger = get_logger(__name__)


class JurisdictionRiskAgent(BaseAgent):
    """Assess jurisdiction-level AML/CFT risk."""

    @property
    def name(self) -> str:
        return "JurisdictionRisk"

    @property
    def system_prompt(self) -> str:
        return f"""You are a KYC jurisdiction risk assessment specialist.

{KYC_REGULATORY_CONTEXT}

## Assessment Framework
For each jurisdiction, determine:
1. FATF status: grey list (increased monitoring) or black list (high-risk, call for action)
2. Active OFAC sanctions programs
3. FINTRAC directives or advisories
4. CRS participation status
5. Corruption Perception Index ranking
6. Basel AML Index score (if available)

## Risk Classification
- LOW: Established financial center, strong AML framework, no FATF concerns
- MEDIUM: Some AML weaknesses, FATF monitoring, but cooperating
- HIGH: FATF grey list, active sanctions, weak AML framework
- CRITICAL: FATF black list, comprehensive sanctions, non-cooperative

{KYC_EVIDENCE_RULES}
{KYC_OUTPUT_RULES}

Return JSON with:
- jurisdictions_assessed: array of country names
- fatf_grey_list: array of countries on grey list
- fatf_black_list: array of countries on black list
- sanctions_programs: array of {{country, program, administering_body}}
- fintrac_directives: array of directive descriptions
- overall_jurisdiction_risk: LOW | MEDIUM | HIGH | CRITICAL
- jurisdiction_details: array of {{country, fatf_status, cpi_score, cpi_rank, basel_aml_score}}
  cpi_score: Transparency International CPI score (0-100, higher=less corrupt)
  basel_aml_score: Basel AML Index score (0-10, higher=more risk)
- evidence_records: array"""

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, jurisdictions: list[str]) -> JurisdictionRiskResult:
        """Assess risk for a list of jurisdictions."""
        prompt = f"""Assess AML/CFT risk for these jurisdictions:

{chr(10).join(f'- {j}' for j in jurisdictions)}

For EACH jurisdiction:
1. Check current FATF grey/black list status
2. Check active OFAC sanctions programs
3. Check for FINTRAC directives
4. Look up Corruption Perception Index (CPI) score and rank
5. Look up Basel AML Index score if available
6. Assess overall AML framework strength

Include per-jurisdiction details with CPI and Basel scores.
Provide an overall jurisdiction risk level."""

        result = await self.run(prompt)
        return self._parse_result(result, jurisdictions)

    def _parse_result(self, result: dict, jurisdictions: list) -> JurisdictionRiskResult:
        data = result.get("json", {})
        if not data:
            return JurisdictionRiskResult(jurisdictions_assessed=jurisdictions)

        level = RiskLevel.LOW
        try:
            level = RiskLevel(data.get("overall_jurisdiction_risk", "LOW").upper())
        except ValueError:
            pass

        records = []
        for country in data.get("fatf_grey_list", []):
            records.append(EvidenceRecord(
                evidence_id=f"jur_grey_{country[:3].lower()}",
                source_type="agent",
                source_name=self.name,
                entity_screened=country,
                claim=f"{country} is on FATF grey list (increased monitoring)",
                evidence_level=EvidenceClass.SOURCED,
                disposition=DispositionStatus.PENDING_REVIEW,
                confidence=Confidence.HIGH,
            ))
        for country in data.get("fatf_black_list", []):
            records.append(EvidenceRecord(
                evidence_id=f"jur_black_{country[:3].lower()}",
                source_type="agent",
                source_name=self.name,
                entity_screened=country,
                claim=f"{country} is on FATF black list (call for action)",
                evidence_level=EvidenceClass.VERIFIED,
                disposition=DispositionStatus.PENDING_REVIEW,
                confidence=Confidence.HIGH,
            ))

        if not records:
            records.append(EvidenceRecord(
                evidence_id="jur_clear",
                source_type="agent",
                source_name=self.name,
                entity_screened=", ".join(jurisdictions),
                claim="All jurisdictions assessed as standard risk",
                evidence_level=EvidenceClass.SOURCED,
                disposition=DispositionStatus.CLEAR,
                confidence=Confidence.HIGH,
            ))

        # Build jurisdiction_details from agent response or fallback from FATF lists
        jurisdiction_details = data.get("jurisdiction_details", [])
        if not jurisdiction_details:
            for country in data.get("jurisdictions_assessed", jurisdictions):
                fatf_status = "clean"
                if country in data.get("fatf_black_list", []):
                    fatf_status = "black_list"
                elif country in data.get("fatf_grey_list", []):
                    fatf_status = "grey_list"
                jurisdiction_details.append({
                    "country": country,
                    "fatf_status": fatf_status,
                    "cpi_score": None,
                    "basel_aml_score": None,
                })

        jr = JurisdictionRiskResult(
            jurisdictions_assessed=data.get("jurisdictions_assessed", jurisdictions),
            fatf_grey_list=data.get("fatf_grey_list", []),
            fatf_black_list=data.get("fatf_black_list", []),
            sanctions_programs=data.get("sanctions_programs", []),
            fintrac_directives=data.get("fintrac_directives", []),
            overall_jurisdiction_risk=level,
            jurisdiction_details=jurisdiction_details,
            evidence_records=records,
        )
        jr.search_queries_executed = result.get("search_stats", {}).get("search_queries", [])
        return jr
