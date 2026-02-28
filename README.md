# KYC Client Onboarding Intelligence System

**What can a compliance officer now do that they couldn't before?**

A single command screens a client across sanctions lists, PEP databases, adverse media, corporate registries, and jurisdiction risk — across every beneficial owner — in minutes instead of hours. The officer gets an evidence-linked risk profile, counter-arguments against every disposition, and an interactive review session where they can interrogate the findings before making a decision.

This is investigative depth at scale. Not automation of existing workflows — expansion of what's possible in a compliance review.

**AI investigates. Rules classify. Humans decide.**

## Quick Start

```bash
cd fluency-research-agent
pip install -r requirements.txt
cp .env.example .env    # Add your ANTHROPIC_API_KEY

# Demo mode — runs the CRITICAL-risk business case with guided narration
python main.py --demo

# Or run individual cases
python main.py --client test_cases/case1_individual_low.json
python main.py --client test_cases/case3_business_critical.json
```

### What Happens

1. **Intake** classifies risk and plans the investigation (deterministic)
2. **Investigation** runs 7 AI agents + UBO cascades across 5 jurisdictions
3. **Synthesis** (Opus) cross-references 40+ evidence records, surfaces contradictions
4. **Review** — the officer asks questions, approves dispositions, decides
5. **Reports** — 4 department briefs + PDFs from a single investigation pass

```
[review] > Why is Viktor Petrov flagged?
┌─ Review Assistant ────────────────────────────┐
│ Viktor Petrov [EV_012] triggered a POTENTIAL   │
│ MATCH against OFAC SDN list entry for Viktor   │
│ Petrov (DOB mismatch: 1972 vs 1968). The 51%  │
│ ownership stake triggers the OFAC 50% rule...  │
└────────────────────────────────────────────────┘
[review] > decide dp_1 B
  Decision recorded: Sanctions Disposition: Alexander Petrov
    Selected: [B] ESCALATE — Refer to senior compliance for review
[review] > finalize
```

### Pipeline Metrics (Sample Case 3 Run)

| Metric | Value |
|--------|-------|
| Total time | ~90s |
| Agents | 7 + 3 UBO cascades |
| Total tokens | ~50K |
| Estimated cost | ~$0.45 |
| Evidence grade | B |
| Web searches | ~30 |

## Architecture

```
Stage 1          Stage 2           Stage 3          Stage 4        Stage 5
Intake &    -->  Investigation -->  Synthesis   -->  Interactive -> Final
Classification   (AI + Rules)      (Opus AI)        Review         Reports
                                                    (Human)
deterministic    7 agents +        cross-ref        ask questions  4 briefs
risk scoring     UBO cascades      contradict       decide         + PDFs
reg detection    12 utilities      counter-args     approve
```

### Stage 2: Investigation Agents

| Agent | Individual | Business | What It Does |
|-------|-----------|----------|-------------|
| IndividualSanctions | Y | UBO cascade | CSL, OpenSanctions, Canadian/UN lists |
| PEPDetection | Y | UBO cascade | FINTRAC PEP classification (5 levels) |
| IndividualAdverseMedia | Y | UBO cascade | Negative news, CanLII legal databases |
| EntityVerification | | Y | Corporate registry, UBO structure |
| EntitySanctions | | Y | Entity screening + OFAC 50% rule |
| BusinessAdverseMedia | | Y | Trade compliance, regulatory actions |
| JurisdictionRisk | Y | Y | FATF grey/black, OFAC sanctions programs |

Plus 12 deterministic utilities: ID verification, suitability (CIRO 3202), FATCA/CRS, EDD triggers, compliance actions, business risk assessment, document requirements.

### Evidence Classification (V/S/I/U)

Every finding is tagged with an evidence level — this is what makes AI confidence legible to humans:

- **V (Verified)** — URL + direct quote from government registry or official list
- **S (Sourced)** — URL + excerpt from major news or regulatory database
- **I (Inferred)** — Derived from multiple signals, reasoning chain documented
- **U (Unknown)** — Explicitly searched but not found

Evidence quality is auto-graded (A-F). Grade A requires 60%+ Verified/Sourced. Low grades trigger extended review time and follow-up actions.

### Model Routing

| Component | Model | Rationale |
|-----------|-------|-----------|
| 7 research agents | Sonnet 4.6 | Fast, cost-effective search + analysis |
| Synthesis | Opus 4.6 | Complex cross-referencing and reasoning |
| Review assistant | Opus 4.6 | Nuanced compliance Q&A with evidence |

### Risk Scoring

Two-pass point-based scoring (deterministic):

| Score | Level | Action |
|-------|-------|--------|
| 0-15 | LOW | Standard onboarding |
| 16-35 | MEDIUM | Enhanced monitoring |
| 36-60 | HIGH | Senior review required |
| 61+ | CRITICAL | Senior management + EDD |

## Test Cases

| Case | Client | Risk | Key Features |
|------|--------|------|-------------|
| 1 | Sarah Thompson | LOW | Canadian nurse, clean profile — fast path |
| 2 | Maria Chen-Dubois | HIGH | Domestic PEP, Hong Kong birth, dual tax residency |
| 3 | Northern Maple Trading | CRITICAL | Import/export, Russia corridor, 3 UBOs, OFAC 50% rule |

```bash
# Run all tests
pytest tests/ -v

# Non-interactive mode (original pause + finalize behavior)
python main.py --client test_cases/case1_individual_low.json --non-interactive
python main.py --finalize results/sarah_thompson_20260228
```

## Results Directory

```
results/{client_id}/
  pipeline_metrics.json      # Timing, tokens, cost, evidence grade
  checkpoint.json
  01_intake/                 # Risk classification + investigation plan
  02_investigation/          # Evidence store + screening results
  03_synthesis/              # Evidence graph + proto-reports + review intelligence
  04_review/                 # Review session log (queries, decisions, notes)
  05_output/                 # Final briefs (MD + PDF)
```

## Design Decisions

See [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) for:
- What breaks at scale (the review queue, not the AI)
- Why AI must stop at disposition (accountability, incomplete world models)
- Evidence classification as core architecture
- Graceful degradation strategies

## Tech Stack

- Python 3.10+ with Pydantic v2
- Anthropic Claude API (Opus 4.6 + Sonnet 4.6)
- Rich for terminal UI and interactive review
- fpdf2 for PDF generation
- rapidfuzz for sanctions list fuzzy matching
- Trade.gov CSL API for sanctions screening
