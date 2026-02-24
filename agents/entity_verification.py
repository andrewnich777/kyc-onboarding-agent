"""
Entity Verification Agent.
Business registration + beneficial ownership verification.
"""

from agents.base import BaseAgent, KYC_EVIDENCE_RULES, KYC_OUTPUT_RULES, KYC_REGULATORY_CONTEXT
from models import EntityVerification, EvidenceRecord, EvidenceClass, DispositionStatus, Confidence
from logger import get_logger

logger = get_logger(__name__)


class EntityVerificationAgent(BaseAgent):
    """Verify business entity registration and ownership structure."""

    @property
    def name(self) -> str:
        return "EntityVerification"

    @property
    def system_prompt(self) -> str:
        return f"""You are a KYC entity verification specialist. You verify business registrations and ownership structures.

{KYC_REGULATORY_CONTEXT}

## Verification Process
1. Search corporate registries for the entity (Canadian provincial/federal registries)
2. Search OpenCorporates for global corporate data
3. Verify the registered name, jurisdiction, incorporation date
4. Cross-reference beneficial ownership structure with declared UBOs
5. Flag any discrepancies between declared and discovered information

## Key Checks
- Is the entity registered and in good standing?
- Does the registered name match the declared name?
- Is the incorporation jurisdiction consistent?
- Are the declared beneficial owners consistent with public records?
- Are there undisclosed related entities or subsidiaries?

{KYC_EVIDENCE_RULES}
{KYC_OUTPUT_RULES}

Return JSON with:
- entity_name: legal name
- verified_registration: boolean
- registry_sources: list of registries checked
- registration_details: {{jurisdiction, status, date, registry_number}}
- ubo_structure_verified: boolean
- discrepancies: array of discrepancy descriptions
- evidence_records: array"""

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, legal_name: str, jurisdiction: str = None,
                       business_number: str = None,
                       declared_ubos: list = None) -> EntityVerification:
        """Verify a business entity."""
        ubo_str = ""
        if declared_ubos:
            ubo_lines = []
            for u in declared_ubos:
                name = u.get("full_name", u) if isinstance(u, dict) else u
                ubo_lines.append(f"  - {name}")
            ubo_str = "\nDeclared Beneficial Owners:\n" + "\n".join(ubo_lines)

        prompt = f"""Verify this business entity:

Legal Name: {legal_name}
Jurisdiction: {jurisdiction or 'Not provided'}
Business Number: {business_number or 'Not provided'}""" + ubo_str + """

Steps:
1. Search Canadian corporate registries (Corporations Canada, provincial registries)
2. Search OpenCorporates for the entity
3. Verify registration status and details
4. Cross-reference beneficial ownership if public records available
5. Flag any discrepancies"""

        result = await self.run(prompt)
        return self._parse_result(result, legal_name)

    def _parse_result(self, result: dict, entity_name: str) -> EntityVerification:
        data = result.get("json", {})
        if not data:
            return EntityVerification(entity_name=entity_name)

        verified = data.get("verified_registration", False)

        records = []
        records.append(EvidenceRecord(
            evidence_id="ev_reg_0",
            source_type="agent",
            source_name=self.name,
            entity_screened=entity_name,
            claim="Entity registration: " + ("Verified" if verified else "Not verified"),
            evidence_level=EvidenceClass.SOURCED if verified else EvidenceClass.UNKNOWN,
            supporting_data=[data.get("registration_details", {})],
            disposition=DispositionStatus.CLEAR if verified else DispositionStatus.PENDING_REVIEW,
            confidence=Confidence.HIGH if verified else Confidence.LOW,
        ))

        for i, disc in enumerate(data.get("discrepancies", [])):
            records.append(EvidenceRecord(
                evidence_id=f"ev_disc_{i}",
                source_type="agent",
                source_name=self.name,
                entity_screened=entity_name,
                claim=f"Discrepancy: {disc}",
                evidence_level=EvidenceClass.SOURCED,
                disposition=DispositionStatus.PENDING_REVIEW,
                confidence=Confidence.MEDIUM,
            ))

        return EntityVerification(
            entity_name=data.get("entity_name", entity_name),
            verified_registration=verified,
            registry_sources=data.get("registry_sources", []),
            registration_details=data.get("registration_details", {}),
            ubo_structure_verified=data.get("ubo_structure_verified", False),
            discrepancies=data.get("discrepancies", []),
            evidence_records=records,
        )
