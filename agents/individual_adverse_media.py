"""
Individual Adverse Media Screening Agent.
5 search queries covering fraud, money laundering, regulatory, employer, bankruptcy.
"""

from agents.base import BaseAgent, _safe_parse_enum, KYC_EVIDENCE_RULES, KYC_OUTPUT_RULES, KYC_REGULATORY_CONTEXT
from models import AdverseMediaResult, AdverseMediaLevel, EvidenceRecord, EvidenceClass, DispositionStatus, Confidence
from logger import get_logger

logger = get_logger(__name__)


class IndividualAdverseMediaAgent(BaseAgent):
    """Screen individuals for negative news and adverse media."""

    @property
    def name(self) -> str:
        return "IndividualAdverseMedia"

    @property
    def system_prompt(self) -> str:
        return f"""You are a KYC adverse media screening specialist. You search for negative news about individuals.

{KYC_REGULATORY_CONTEXT}

## Search Strategy (5 mandatory queries)
1. "[name]" fraud OR lawsuit OR criminal charges
2. "[name]" money laundering OR corruption OR bribery
3. "[name]" regulatory action OR sanctions OR enforcement
4. "[name]" [employer if known] controversy OR investigation
5. "[name]" bankruptcy OR insolvency OR debt

Also search CanLII (Canadian Legal Information Institute) for any Canadian court cases.

## Classification
- CLEAR: No adverse media found after thorough search
- LOW_CONCERN: Minor or old issues, no pattern of misconduct
- MATERIAL_CONCERN: Significant issues that affect risk assessment
- HIGH_RISK: Serious criminal/regulatory issues, ongoing investigations

{KYC_EVIDENCE_RULES}

{KYC_OUTPUT_RULES}

Return JSON with:
- entity_screened: name
- overall_level: CLEAR | LOW_CONCERN | MATERIAL_CONCERN | HIGH_RISK
- articles_found: array of {{title, source, date, summary, category, source_tier}}
  source_tier: TIER_0 (government/court records), TIER_1 (major established media), TIER_2 (other/blogs)
- categories: array of category strings
- evidence_records: array"""

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, full_name: str, employer: str = None,
                       citizenship: str = None) -> AdverseMediaResult:
        """Screen an individual for adverse media."""
        employer_line = "\nEmployer: " + employer if employer else ""
        employer_query = " " + employer if employer else ""

        prompt = f"""Screen this individual for adverse media / negative news:

Name: {full_name}
Citizenship: {citizenship or 'Not provided'}""" + employer_line + f"""

Run ALL 5 mandatory search queries:
1. "{full_name}" fraud OR lawsuit OR criminal
2. "{full_name}" money laundering OR corruption OR bribery
3. "{full_name}" regulatory action OR sanctions
4. "{full_name}"{employer_query} controversy OR investigation
5. "{full_name}" bankruptcy OR insolvency

Then search CanLII for Canadian court records.
For each finding, classify severity and relevance."""

        result = await self.run(prompt)
        return self._parse_result(result, full_name)

    def _parse_result(self, result: dict, entity_name: str) -> AdverseMediaResult:
        data = result.get("json", {})
        if not data:
            return AdverseMediaResult(entity_screened=entity_name)

        level = _safe_parse_enum(AdverseMediaLevel, data.get("overall_level", "CLEAR"), AdverseMediaLevel.CLEAR)

        records = []
        for i, article in enumerate(data.get("articles_found", [])):
            records.append(self._build_finding_record(
                f"adv_ind_{i}", entity_name,
                f"Adverse media: {article.get('title', 'Unknown')}",
                [article],
            ))

        if not records:
            records.append(self._build_clear_record(
                "adv_ind_clear", entity_name,
                "No adverse media found",
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
