"""
Business Adverse Media Screening Agent.
Entity-specific searches including trade compliance, environmental, labor violations.
"""

from agents.base import BaseAgent, _safe_parse_enum, KYC_EVIDENCE_RULES, KYC_OUTPUT_RULES, KYC_REGULATORY_CONTEXT
from models import AdverseMediaResult, AdverseMediaLevel, EvidenceRecord, EvidenceClass, DispositionStatus, Confidence
from logger import get_logger

logger = get_logger(__name__)


class BusinessAdverseMediaAgent(BaseAgent):
    """Screen business entities for adverse media."""

    @property
    def name(self) -> str:
        return "BusinessAdverseMedia"

    @property
    def system_prompt(self) -> str:
        return f"""You are a KYC business adverse media screening specialist.

{KYC_REGULATORY_CONTEXT}

## Search Strategy
1. "[entity name]" fraud OR investigation OR enforcement
2. "[entity name]" sanctions OR trade compliance violation
3. "[entity name]" environmental violation OR labor violation
4. "[entity name]" money laundering OR terrorism financing
5. "[entity name]" regulatory action OR fine OR penalty

Also check:
- CanLII for Canadian court cases
- FINTRAC enforcement actions
- Provincial securities commission decisions

{KYC_EVIDENCE_RULES}
{KYC_OUTPUT_RULES}

Return JSON with:
- entity_screened: entity name
- overall_level: CLEAR | LOW_CONCERN | MATERIAL_CONCERN | HIGH_RISK
- articles_found: array of {{title, source, date, summary, category, source_tier}}
  source_tier: TIER_0 (government/court records), TIER_1 (major established media), TIER_2 (other/blogs)
- categories: array
- evidence_records: array"""

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, legal_name: str, industry: str = None,
                       countries: list = None) -> AdverseMediaResult:
        """Screen a business entity for adverse media."""
        prompt = f"""Screen this business for adverse media:

Entity: {legal_name}
Industry: {industry or 'Not provided'}
Countries: {', '.join(countries or ['Not provided'])}

Run ALL mandatory searches and classify findings by severity."""

        result = await self.run(prompt)
        return self._parse_result(result, legal_name)

    def _parse_result(self, result: dict, entity_name: str) -> AdverseMediaResult:
        data = result.get("json", {})
        if not data:
            return AdverseMediaResult(entity_screened=entity_name)

        level = _safe_parse_enum(AdverseMediaLevel, data.get("overall_level", "CLEAR"), AdverseMediaLevel.CLEAR)

        records = []
        for i, article in enumerate(data.get("articles_found", [])):
            records.append(self._build_finding_record(
                f"adv_biz_{i}", entity_name,
                f"Business adverse media: {article.get('title', 'Unknown')}",
                [article],
            ))

        if not records:
            records.append(self._build_clear_record(
                "adv_biz_clear", entity_name,
                "No business adverse media found",
            ))

        amr = AdverseMediaResult(
            entity_screened=data.get("entity_screened", entity_name),
            overall_level=level,
            articles_found=data.get("articles_found", []),
            categories=data.get("categories", []),
            evidence_records=records,
        )
        self._attach_search_queries(amr, result)
        return amr
