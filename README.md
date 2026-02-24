# KYC Client Onboarding Intelligence System

An AI-powered regulatory screening and risk assessment pipeline for financial client onboarding, designed for the Canadian securities dealer context (FINTRAC/CIRO). Built as a practical demonstration of multi-agent AI systems applied to compliance workflows.

**Design Principles:**
1. **AI investigates. Rules classify. Humans decide.** — AI agents gather evidence; deterministic utilities score risk; compliance officers make final decisions.
2. **Individual and business are separate paths through the same pipeline.** — Client type determines which agents run and which utilities apply.
3. **The conversational review IS the terminal.** — After generating proto-reports, the system pauses for the compliance officer to ask questions, approve/override dispositions, then finalize.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    5-Stage Pipeline                   │
├──────────┬──────────┬──────────┬──────────┬──────────┤
│ Stage 1  │ Stage 2  │ Stage 3  │ Stage 4  │ Stage 5  │
│ Intake & │ Investi- │ Synthe-  │ Review   │ Final    │
│ Classify │ gation   │ sis      │ (Human)  │ Reports  │
├──────────┼──────────┼──────────┼──────────┼──────────┤
│Determin- │AI Agents │Opus AI   │Terminal  │Generators│
│istic     │+Utilities│          │Chat      │+ PDF     │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

### Stage 1: Intake & Classification (Deterministic)
- Parses client JSON (individual or business)
- Calculates preliminary risk score using point-based tables
- Detects applicable regulations (FINTRAC, CIRO, OFAC, FATCA, CRS)
- Builds investigation plan (which agents and utilities to run)

### Stage 2: Investigation (AI + Deterministic)
**AI Agents** (Sonnet 4.6 — web search + screening tools):
| Agent | Individual | Business | Description |
|-------|-----------|----------|-------------|
| IndividualSanctions | ✓ | UBO cascade | CSL, OpenSanctions, Canadian/UN lists |
| PEPDetection | ✓ | UBO cascade | FINTRAC PEP classification |
| IndividualAdverseMedia | ✓ | UBO cascade | Negative news, CanLII |
| EntityVerification | | ✓ | Corporate registry, UBO structure |
| EntitySanctions | | ✓ | Entity screening + OFAC 50% rule |
| BusinessAdverseMedia | | ✓ | Trade compliance, regulatory actions |
| JurisdictionRisk | ✓ | ✓ | FATF grey/black, OFAC programs |

**Deterministic Utilities** (pure Python, no API calls):
| Utility | Individual | Business | Description |
|---------|-----------|----------|-------------|
| id_verification | ✓ | ✓ | FINTRAC ID verification pathway |
| suitability | ✓ | ✓ | CIRO 3202 suitability assessment |
| individual_fatca_crs | ✓ | | 7 US indicia, CRS self-certification |
| entity_fatca_crs | | ✓ | FI/Active NFFE/Passive NFFE classification |
| edd_requirements | ✓ | ✓ | EDD trigger logic and measures |
| compliance_actions | ✓ | ✓ | STR, TPR, FATCA/CRS reporting |
| business_risk_assessment | | ✓ | Industry, ownership, transaction analysis |

**UBO Cascade** (business clients only): Each beneficial owner is individually screened through IndividualSanctions, PEPDetection, and IndividualAdverseMedia. Results feed back into risk score revision.

### Stage 3: Synthesis (Opus 4.6)
- Cross-references all findings across agents and utilities
- Detects contradictions and corroborations
- Revises risk score with UBO cascade data + synthesis-discovered factors
- Recommends APPROVE / CONDITIONAL / ESCALATE / DECLINE
- Generates proto-reports for review

### Stage 4: Review (Human-in-the-Loop)
The pipeline pauses after Stage 3. The compliance officer continues in the terminal:
- "Explain the Petrov sanctions match"
- "Approve the false positive"
- "Finalize"

Actions are logged to `review_session.json`.

### Stage 5: Final Reports
- Compliance Officer Brief (detailed Markdown + PDF)
- Onboarding Summary (one-page decision document + PDF)
- Incorporates review session log and any disposition overrides

## Risk Scoring

Two-pass point-based scoring:

| Score Range | Risk Level |
|-------------|-----------|
| 0-15 | LOW |
| 16-35 | MEDIUM |
| 36-60 | HIGH |
| 61+ | CRITICAL |

**Individual factors:** PEP status (+25/+30/+40), citizenship, country of birth, occupation, source of funds, wealth/income ratio, US person, tax residencies, third-party transactions.

**Business factors:** Entity age, industry, countries of operation (FATF/sanctions), transaction volume, ownership complexity, US nexus, incorporation jurisdiction, UBO cascade (`max(ubo_scores) × 0.5`).

## Evidence Classification (V/S/I/U)

Every finding is tagged with an evidence level:
- **V (Verified)** — URL + direct quote + Tier 0/1 source (government registry, official list)
- **S (Sourced)** — URL + excerpt + Tier 1/2 source (major news, regulatory database)
- **I (Inferred)** — Derived from signals, no direct evidence
- **U (Unknown)** — Explicitly searched but not found

## Quick Start

### Prerequisites
- Python 3.10+
- Anthropic API key (Claude Max or API access)

### Setup
```bash
cd fluency-research-agent
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Run
```bash
# Individual client (LOW risk)
python main.py --client test_cases/case1_individual_low.json

# Individual with PEP (HIGH risk)
python main.py --client test_cases/case2_individual_pep.json

# Business with UBO cascade (CRITICAL risk)
python main.py --client test_cases/case3_business_critical.json

# Resume from checkpoint
python main.py --client test_cases/case1_individual_low.json --resume

# Finalize after review
python main.py --finalize results/sarah_thompson_20260223
```

### Test Cases

| Case | Client | Type | Expected Risk | Key Features |
|------|--------|------|--------------|--------------|
| 1 | Sarah Thompson | Individual | LOW | Canadian nurse, clean profile |
| 2 | Maria Chen-Dubois | Individual | HIGH | Domestic PEP, Hong Kong birth, dual tax |
| 3 | Northern Maple Trading | Business | CRITICAL | Import/export, Russia trade corridor, UBO cascade, OFAC 50% rule |

### Run Tests
```bash
pytest tests/ -v
```

## Results Directory

```
results/{client_id}/
  checkpoint.json
  01_intake/
    classification.json
    investigation_plan.json
  02_investigation/
    evidence_store.json
    individual_sanctions.json | entity_sanctions.json
    pep_analysis.json         | entity_verification.json
    ...
    ubo_screening/            # Business only
  03_synthesis/
    evidence_graph.json
    risk_assessment.json
    proto_compliance_brief.md
    proto_onboarding_summary.md
  04_review/
    review_session.json
  05_output/
    compliance_officer_brief.md + .pdf
    onboarding_summary.md + .pdf
```

## Model Routing

| Component | Model | Rationale |
|-----------|-------|-----------|
| Research agents (7) | Sonnet 4.6 | Fast, cost-effective for search + analysis |
| Synthesis | Opus 4.6 | Complex cross-referencing and reasoning |
| Review session | Opus 4.6 | Nuanced compliance Q&A |

## Data Sources
- **Trade.gov Consolidated Screening List** — US sanctions, denied persons, entity lists
- **Web search** — OpenSanctions, Canadian sanctions lists, UN lists, CanLII, corporate registries, news
- **FATF** — Grey list and black list countries
- **FINTRAC** — PEP definitions, EDD triggers, reporting obligations
- **CIRO** — Rule 3202 suitability requirements

## Tech Stack
- Python 3.10+ with Pydantic v2
- Anthropic Claude API (Opus 4.6 + Sonnet 4.6)
- fpdf2 for PDF generation
- Rich for terminal UI
- rapidfuzz for sanctions list fuzzy matching
