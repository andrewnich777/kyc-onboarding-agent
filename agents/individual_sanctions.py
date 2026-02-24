"""
Individual Sanctions Screening Agent.
Screens individuals against CSL, OpenSanctions, Canadian sanctions, UN list.
"""

import json
from agents.base import BaseAgent, KYC_EVIDENCE_RULES, KYC_OUTPUT_RULES, KYC_FALSE_POSITIVE_RULES, KYC_REGULATORY_CONTEXT
from models import SanctionsResult, EvidenceRecord, EvidenceClass, DispositionStatus, Confidence
from logger import get_logger

logger = get_logger(__name__)


class IndividualSanctionsAgent(BaseAgent):
    """Screen individual names against sanctions lists."""

    @property
    def name(self) -> str:
        return "IndividualSanctions"

    @property
    def system_prompt(self) -> str:
        return f"""You are a KYC sanctions screening specialist. Your job is to screen individual names against global sanctions lists and determine if there are any matches.

{KYC_REGULATORY_CONTEXT}

## Screening Process
1. Use screening_list_lookup to check the Trade.gov Consolidated Screening List
2. Use web_search to check OpenSanctions, Canadian sanctions (SEMA), and UN Security Council lists
3. Use web_fetch to retrieve details on any potential matches
4. Apply false positive analysis for any matches found

{KYC_FALSE_POSITIVE_RULES}

{KYC_EVIDENCE_RULES}

{KYC_OUTPUT_RULES}

Return a JSON object with:
- entity_screened: name screened
- screening_sources: list of sources checked
- matches: array of {{list_name, matched_name, score, details, secondary_identifiers}}
- disposition: CLEAR | POTENTIAL_MATCH | CONFIRMED_MATCH | FALSE_POSITIVE
- disposition_reasoning: detailed explanation
- evidence_records: array of evidence with evidence_id, claim, evidence_level, supporting_data"""

    @property
    def tools(self) -> list[str]:
        return ["web_search", "screening_list_lookup", "web_fetch"]

    async def research(self, full_name: str, date_of_birth: str = None,
                       citizenship: str = None, context: str = None) -> SanctionsResult:
        """Screen an individual against sanctions lists."""
        prompt = f"""Screen this individual against all available sanctions lists:

Name: {full_name}
Date of Birth: {date_of_birth or 'Not provided'}
Citizenship: {citizenship or 'Not provided'}
Context: {context or 'Primary account holder'}

Steps:
1. Search the Consolidated Screening List for name matches
2. Search OpenSanctions database for the name
3. Search Canadian SEMA (Special Economic Measures Act) sanctions
4. Search UN Security Council consolidated list
5. For any potential matches, verify using secondary identifiers (DOB, citizenship)
6. Classify each match and provide disposition

Be thorough but precise. Common names will have many results — focus on identifying the RIGHT person."""

        result = await self.run(prompt)
        return self._parse_result(result, full_name)

    def _parse_result(self, result: dict, entity_name: str) -> SanctionsResult:
        """Parse agent response into SanctionsResult."""
        data = result.get("json", {})
        if not data:
            return SanctionsResult(
                entity_screened=entity_name,
                screening_sources=["CSL", "OpenSanctions", "Canadian SEMA", "UN SCSL"],
                disposition=DispositionStatus.PENDING_REVIEW,
                disposition_reasoning="Agent did not return structured data — manual review required",
            )

        disposition = DispositionStatus.CLEAR
        disp_str = data.get("disposition", "CLEAR").upper()
        try:
            disposition = DispositionStatus(disp_str)
        except ValueError:
            disposition = DispositionStatus.PENDING_REVIEW

        sr = SanctionsResult(
            entity_screened=data.get("entity_screened", entity_name),
            screening_sources=data.get("screening_sources", []),
            matches=data.get("matches", []),
            disposition=disposition,
            disposition_reasoning=data.get("disposition_reasoning", ""),
            evidence_records=self._build_evidence_records(data, entity_name),
        )
        sr.search_queries_executed = result.get("search_stats", {}).get("search_queries", [])
        return sr

    def _build_evidence_records(self, data: dict, entity_name: str) -> list[EvidenceRecord]:
        """Build evidence records from parsed data."""
        records = []
        for i, match in enumerate(data.get("matches", [])):
            records.append(EvidenceRecord(
                evidence_id=f"san_ind_{i}",
                source_type="agent",
                source_name=self.name,
                entity_screened=entity_name,
                claim=f"Sanctions match: {match.get('matched_name', 'unknown')} on {match.get('list_name', 'unknown')}",
                evidence_level=EvidenceClass.SOURCED,
                supporting_data=[match],
                disposition=DispositionStatus.PENDING_REVIEW,
                confidence=Confidence.MEDIUM,
            ))

        if not records:
            records.append(EvidenceRecord(
                evidence_id="san_ind_clear",
                source_type="agent",
                source_name=self.name,
                entity_screened=entity_name,
                claim="No sanctions matches found across all screening sources",
                evidence_level=EvidenceClass.SOURCED,
                supporting_data=[{"sources_checked": data.get("screening_sources", [])}],
                disposition=DispositionStatus.CLEAR,
                disposition_reasoning=data.get("disposition_reasoning", "No matches"),
                confidence=Confidence.HIGH,
            ))

        return records
