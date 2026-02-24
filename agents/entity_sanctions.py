"""
Entity Sanctions Screening Agent.
Entity screening + OFAC 50% rule.
"""

from agents.base import BaseAgent, KYC_EVIDENCE_RULES, KYC_OUTPUT_RULES, KYC_FALSE_POSITIVE_RULES, KYC_REGULATORY_CONTEXT
from models import SanctionsResult, EvidenceRecord, EvidenceClass, DispositionStatus, Confidence
from logger import get_logger

logger = get_logger(__name__)


class EntitySanctionsAgent(BaseAgent):
    """Screen business entities against sanctions lists with OFAC 50% rule."""

    @property
    def name(self) -> str:
        return "EntitySanctions"

    @property
    def system_prompt(self) -> str:
        return f"""You are a KYC entity sanctions screening specialist.

{KYC_REGULATORY_CONTEXT}

## OFAC 50% Rule
If a person on the SDN list owns 50% or more of an entity (directly or indirectly),
that entity is BLOCKED even if not itself listed. This applies to:
- Direct ownership >= 50%
- Aggregate ownership by multiple SDN-listed persons >= 50%
- Indirect ownership through intermediary entities

## Screening Process
1. Search the Consolidated Screening List for the entity name
2. Search OpenSanctions for the entity
3. Search OFAC SDN list specifically
4. Check if any beneficial owners are SDN-listed (50% rule)
5. Search for entity aliases and related entities

{KYC_FALSE_POSITIVE_RULES}
{KYC_EVIDENCE_RULES}
{KYC_OUTPUT_RULES}

Return JSON with:
- entity_screened: entity name
- screening_sources: list of sources
- matches: array of matches
- disposition: CLEAR | POTENTIAL_MATCH | CONFIRMED_MATCH | FALSE_POSITIVE
- disposition_reasoning: explanation
- ofac_50_percent_rule_applicable: boolean
- evidence_records: array"""

    @property
    def tools(self) -> list[str]:
        return ["web_search", "screening_list_lookup", "web_fetch"]

    async def research(self, legal_name: str, beneficial_owners: list = None,
                       countries: list = None, us_nexus: bool = False) -> SanctionsResult:
        """Screen a business entity against sanctions lists."""
        ubo_section = ""
        if beneficial_owners:
            ubo_lines = []
            for ubo in beneficial_owners:
                name = ubo.get("full_name", ubo) if isinstance(ubo, dict) else str(ubo)
                pct = ubo.get("ownership_percentage", "?") if isinstance(ubo, dict) else "?"
                ubo_lines.append(f"  - {name} ({pct}%)")
            ubo_section = "\nBeneficial Owners:\n" + "\n".join(ubo_lines)
            ubo_section += "\n\nIMPORTANT: Check OFAC 50% rule — if any owner with >=50% is SDN-listed, the entity is BLOCKED."

        ofac_msg = "Search OFAC SDN list specifically (US nexus present)" if us_nexus else "Check OFAC SDN if relevant"
        countries_str = ", ".join(countries or ["Not provided"])

        prompt = f"""Screen this business entity against sanctions lists:

Entity: {legal_name}
Countries of Operation: {countries_str}
US Nexus: {us_nexus}""" + ubo_section + f"""

Steps:
1. Search Consolidated Screening List for entity name and aliases
2. Search OpenSanctions for the entity
3. {ofac_msg}
4. Check if any beneficial owners trigger the 50% rule
5. Document all findings with evidence"""

        result = await self.run(prompt)
        return self._parse_result(result, legal_name)

    def _parse_result(self, result: dict, entity_name: str) -> SanctionsResult:
        data = result.get("json", {})
        if not data:
            return SanctionsResult(
                entity_screened=entity_name,
                disposition=DispositionStatus.PENDING_REVIEW,
            )

        disposition = DispositionStatus.CLEAR
        try:
            disposition = DispositionStatus(data.get("disposition", "CLEAR").upper())
        except ValueError:
            disposition = DispositionStatus.PENDING_REVIEW

        records = []
        for i, match in enumerate(data.get("matches", [])):
            records.append(EvidenceRecord(
                evidence_id=f"san_ent_{i}",
                source_type="agent",
                source_name=self.name,
                entity_screened=entity_name,
                claim=f"Entity sanctions match: {match.get('matched_name', 'unknown')}",
                evidence_level=EvidenceClass.SOURCED,
                supporting_data=[match],
                disposition=DispositionStatus.PENDING_REVIEW,
                confidence=Confidence.MEDIUM,
            ))

        if not records:
            records.append(EvidenceRecord(
                evidence_id="san_ent_clear",
                source_type="agent",
                source_name=self.name,
                entity_screened=entity_name,
                claim="No entity sanctions matches found",
                evidence_level=EvidenceClass.SOURCED,
                disposition=DispositionStatus.CLEAR,
                confidence=Confidence.HIGH,
            ))

        return SanctionsResult(
            entity_screened=data.get("entity_screened", entity_name),
            screening_sources=data.get("screening_sources", []),
            matches=data.get("matches", []),
            disposition=disposition,
            disposition_reasoning=data.get("disposition_reasoning", ""),
            ofac_50_percent_rule_applicable=data.get("ofac_50_percent_rule_applicable", False),
            evidence_records=records,
        )
