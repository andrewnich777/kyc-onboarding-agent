"""
PEP Detection Agent.
Classifies individuals per FINTRAC PEP categories.
"""

import json
import re as _re
from agents.base import BaseAgent, KYC_EVIDENCE_RULES, KYC_OUTPUT_RULES, KYC_REGULATORY_CONTEXT
from models import PEPClassification, PEPLevel, EvidenceRecord, EvidenceClass, DispositionStatus, Confidence
from logger import get_logger

logger = get_logger(__name__)


class PEPDetectionAgent(BaseAgent):
    """Detect and classify Politically Exposed Persons."""

    @property
    def name(self) -> str:
        return "PEPDetection"

    @property
    def system_prompt(self) -> str:
        return f"""You are a KYC PEP (Politically Exposed Person) detection specialist.

{KYC_REGULATORY_CONTEXT}

## PEP Categories (FINTRAC/PCMLTFA)
- FOREIGN_PEP: Person who holds/held a prescribed position in a foreign state. EDD is PERMANENT.
- DOMESTIC_PEP: Person who holds/held a prescribed position in Canada. EDD for 5 years after leaving office.
- HIO: Head of International Organization (UN, World Bank, IMF, etc.). EDD for 5 years.
- PEP_FAMILY: Family member (spouse, parent, child, sibling) of a PEP.
- PEP_ASSOCIATE: Close associate (business partner, close personal relationship) of a PEP.

## Prescribed Positions Include
Cabinet ministers, members of parliament/senate, mayors of major cities,
supreme court justices, ambassadors, military generals, central bank governors,
heads of state-owned enterprises, senior political party officials.

{KYC_EVIDENCE_RULES}

{KYC_OUTPUT_RULES}

Return JSON with:
- entity_screened: name
- self_declared: boolean
- detected_level: NOT_PEP | FOREIGN_PEP | DOMESTIC_PEP | HIO | PEP_FAMILY | PEP_ASSOCIATE
- positions_found: array of {{position, organization, dates, source}}
- family_associations: array of {{name, relationship, pep_details}}
- edd_required: boolean
- evidence_records: array"""

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, full_name: str, citizenship: str = None,
                       pep_self_declaration: bool = False,
                       pep_details: str = None) -> PEPClassification:
        """Detect PEP status for an individual."""
        verify_msg = "Verify the self-declaration — search for their political role"
        search_msg = "Search for any political positions held"
        step1 = verify_msg if pep_self_declaration else search_msg

        prompt = f"""Determine the PEP (Politically Exposed Person) status of this individual:

Name: {full_name}
Citizenship: {citizenship or 'Not provided'}
Self-declared PEP: {pep_self_declaration}
Self-declared details: {pep_details or 'None provided'}

Steps:
1. {step1}
2. Search for government positions, political appointments, military rank
3. Search for connections to known PEPs (family/associate)
4. Classify per FINTRAC categories
5. Determine if EDD is required

For domestic PEPs: check if they left office within the last 5 years.
For foreign PEPs: EDD is permanent regardless of when they left office."""

        result = await self.run(prompt)
        return self._parse_result(result, full_name, pep_self_declaration)

    def _parse_result(self, result: dict, entity_name: str, self_declared: bool) -> PEPClassification:
        """Parse agent response into PEPClassification."""
        data = result.get("json", {})
        if not data:
            return PEPClassification(
                entity_screened=entity_name,
                self_declared=self_declared,
                detected_level=PEPLevel.NOT_PEP,
            )

        level = PEPLevel.NOT_PEP
        level_str = data.get("detected_level", "NOT_PEP").upper()
        try:
            level = PEPLevel(level_str)
        except ValueError:
            pass

        # EDD timeline calculation
        edd_permanent = False
        edd_expiry_date = None
        if level == PEPLevel.FOREIGN_PEP:
            edd_permanent = True
        elif level in (PEPLevel.DOMESTIC_PEP, PEPLevel.HIO):
            positions = data.get("positions_found", [])
            latest_end = None
            for pos in positions:
                dates = str(pos.get("dates", ""))
                if "present" in dates.lower() or "current" in dates.lower():
                    edd_permanent = True
                    break
                years = _re.findall(r'20\d{2}', dates)
                if years:
                    end_year = max(int(y) for y in years)
                    if latest_end is None or end_year > latest_end:
                        latest_end = end_year
            if not edd_permanent and latest_end:
                edd_expiry_date = f"{latest_end + 5}-01-01"
        elif level in (PEPLevel.PEP_FAMILY, PEPLevel.PEP_ASSOCIATE):
            edd_permanent = True

        pep = PEPClassification(
            entity_screened=data.get("entity_screened", entity_name),
            self_declared=data.get("self_declared", self_declared),
            detected_level=level,
            positions_found=data.get("positions_found", []),
            family_associations=data.get("family_associations", []),
            edd_required=data.get("edd_required", level != PEPLevel.NOT_PEP),
            edd_expiry_date=edd_expiry_date,
            edd_permanent=edd_permanent,
            evidence_records=self._build_evidence_records(data, entity_name, level),
        )
        pep.search_queries_executed = result.get("search_stats", {}).get("search_queries", [])
        return pep

    def _build_evidence_records(self, data: dict, entity_name: str, level: PEPLevel) -> list[EvidenceRecord]:
        records = []
        if level != PEPLevel.NOT_PEP:
            for i, pos in enumerate(data.get("positions_found", [])):
                records.append(EvidenceRecord(
                    evidence_id=f"pep_{i}",
                    source_type="agent",
                    source_name=self.name,
                    entity_screened=entity_name,
                    claim=f"PEP position: {pos.get('position', 'unknown')} at {pos.get('organization', 'unknown')}",
                    evidence_level=EvidenceClass.SOURCED,
                    supporting_data=[pos],
                    disposition=DispositionStatus.PENDING_REVIEW,
                    confidence=Confidence.MEDIUM,
                ))
        else:
            records.append(EvidenceRecord(
                evidence_id="pep_clear",
                source_type="agent",
                source_name=self.name,
                entity_screened=entity_name,
                claim="No PEP status detected",
                evidence_level=EvidenceClass.SOURCED,
                supporting_data=[],
                disposition=DispositionStatus.CLEAR,
                confidence=Confidence.HIGH,
            ))
        return records
