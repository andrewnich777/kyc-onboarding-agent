"""
Reports mixin for KYC Pipeline.

Handles brief generation (proto and final), file I/O, and decision point display.
"""

import json
from pathlib import Path

from rich.console import Console

from logger import get_logger
from models import InvestigationResults, ReviewSession

logger = get_logger(__name__)

console = Console(force_terminal=True, legacy_windows=True)


# Brief generator table: (module_path, function_name, output_filename, accepts_extra_kwargs)
# All generators accept: client_id, synthesis, plan
# "extra_kwargs" lists additional keyword args the generator accepts
BRIEF_GENERATORS = [
    (
        "generators.aml_operations_brief",
        "generate_aml_operations_brief",
        "aml_operations_brief",
        {"evidence_store", "review_session", "investigation"},
    ),
    (
        "generators.risk_assessment_brief",
        "generate_risk_assessment_brief",
        "risk_assessment_brief",
        {"investigation"},
    ),
    (
        "generators.regulatory_actions_brief",
        "generate_regulatory_actions_brief",
        "regulatory_actions_brief",
        {"investigation"},
    ),
    (
        "generators.onboarding_summary",
        "generate_onboarding_summary",
        "onboarding_decision_brief",
        {"investigation"},
    ),
]


class ReportsMixin:
    """Report generation and file I/O."""

    def _generate_briefs(
        self,
        output_dir: Path,
        client_id: str,
        synthesis,
        plan,
        *,
        prefix: str = "",
        evidence_store: list = None,
        review_session=None,
        investigation: InvestigationResults = None,
        generate_pdfs: bool = False,
        risk_level: str = None,
    ):
        """Generate department-targeted briefs.

        Args:
            output_dir: Directory to write files into.
            client_id: Client identifier.
            synthesis: KYCSynthesisOutput.
            plan: InvestigationPlan.
            prefix: Filename prefix (e.g. "proto_" for stage 3).
            evidence_store: Evidence records list (for AML brief).
            review_session: ReviewSession (for AML brief, final only).
            investigation: InvestigationResults (for final briefs).
            generate_pdfs: Whether to also generate PDFs.
            risk_level: Risk level string for PDF headers.
        """
        import importlib

        output_dir.mkdir(parents=True, exist_ok=True)

        # Build pool of available extra kwargs
        available_kwargs = {}
        if evidence_store is not None:
            available_kwargs["evidence_store"] = evidence_store
        if review_session is not None:
            available_kwargs["review_session"] = review_session
        if investigation is not None:
            available_kwargs["investigation"] = investigation

        for module_path, func_name, filename, accepted_extras in BRIEF_GENERATORS:
            try:
                module = importlib.import_module(module_path)
                func = getattr(module, func_name)

                # Build kwargs: base + accepted extras that are available
                kwargs = dict(client_id=client_id, synthesis=synthesis, plan=plan)
                for key in accepted_extras:
                    if key in available_kwargs:
                        kwargs[key] = available_kwargs[key]

                brief = func(**kwargs)
                (output_dir / f"{prefix}{filename}.md").write_text(brief, encoding="utf-8")
                self.log(f"  [green]{prefix}{filename} generated[/green]")
            except Exception as e:
                if prefix:
                    logger.warning(f"{prefix}{filename} failed: {e}")
                else:
                    self.log(f"  [red]{filename} error: {e}[/red]")
                    logger.exception(f"{filename} generation failed")

        # Generate PDFs
        if generate_pdfs:
            try:
                from generators.pdf_generator import generate_kyc_pdf
                for _, _, filename, _ in BRIEF_GENERATORS:
                    md_path = output_dir / f"{filename}.md"
                    if md_path.exists():
                        md_content = md_path.read_text(encoding="utf-8")
                        pdf_path = output_dir / f"{filename}.pdf"
                        generate_kyc_pdf(md_content, str(pdf_path), filename, risk_level=risk_level)
                        self.log(f"  [green]PDF generated: {filename}.pdf[/green]")
            except Exception as e:
                self.log(f"  [yellow]PDF generation skipped: {e}[/yellow]")

    def _save_stage3_outputs(self, client_id: str, synthesis, plan):
        """Save Stage 3 synthesis outputs and proto-reports."""
        synth_path = self.output_dir / client_id / "03_synthesis"
        synth_path.mkdir(parents=True, exist_ok=True)

        if synthesis:
            (synth_path / "evidence_graph.json").write_text(
                json.dumps(synthesis.evidence_graph.model_dump(), indent=2, default=str),
                encoding="utf-8"
            )
            (synth_path / "risk_assessment.json").write_text(
                json.dumps(
                    synthesis.revised_risk_assessment.model_dump() if synthesis.revised_risk_assessment else {},
                    indent=2, default=str
                ),
                encoding="utf-8"
            )

            # Save decision points
            if synthesis.decision_points:
                (synth_path / "decision_points.json").write_text(
                    json.dumps(
                        [dp.model_dump() for dp in synthesis.decision_points],
                        indent=2, default=str
                    ),
                    encoding="utf-8"
                )

            # Generate proto-reports (4 department-targeted briefs)
            self._generate_briefs(
                output_dir=synth_path,
                client_id=client_id,
                synthesis=synthesis,
                plan=plan,
                prefix="proto_",
                evidence_store=self.evidence_store,
            )

    async def _run_final_reports(self, client_id: str, synthesis, plan, review_session,
                                investigation: InvestigationResults = None):
        """Stage 5: Generate final 4 department-targeted briefs + PDFs."""
        output_dir = self.output_dir / client_id / "05_output"

        # Load evidence store
        es_path = self.output_dir / client_id / "02_investigation" / "evidence_store.json"
        evidence_store = []
        if es_path.exists():
            evidence_store = json.loads(es_path.read_text(encoding="utf-8"))

        risk_level = None
        if plan and plan.preliminary_risk:
            risk_level = plan.preliminary_risk.risk_level.value

        self._generate_briefs(
            output_dir=output_dir,
            client_id=client_id,
            synthesis=synthesis,
            plan=plan,
            evidence_store=evidence_store,
            review_session=review_session,
            investigation=investigation,
            generate_pdfs=True,
            risk_level=risk_level,
        )

    # =========================================================================
    # File I/O Helpers
    # =========================================================================

    def _save_stage_results(self, client_id: str, stage_dir: str, data: dict):
        """Save stage results to appropriate directory."""
        stage_path = self.output_dir / client_id / stage_dir
        stage_path.mkdir(parents=True, exist_ok=True)
        for filename, content in data.items():
            file_path = stage_path / f"{filename}.json"
            file_path.write_text(
                json.dumps(content, indent=2, default=str),
                encoding="utf-8"
            )

    def _save_evidence_store(self, client_id: str):
        """Save the central evidence store."""
        inv_path = self.output_dir / client_id / "02_investigation"
        inv_path.mkdir(parents=True, exist_ok=True)
        (inv_path / "evidence_store.json").write_text(
            json.dumps(self.evidence_store, indent=2, default=str),
            encoding="utf-8"
        )

    def _display_decision_points(self, synthesis):
        """Display decision points requiring officer review in the terminal."""
        if not synthesis or not synthesis.decision_points:
            return

        console.print("\n[bold]Decision Points Requiring Officer Review:[/bold]\n")
        for dp in synthesis.decision_points:
            console.print(f"[bold yellow]{'━' * 60}[/bold yellow]")
            console.print(f"[bold yellow]  {dp.title}[/bold yellow]")
            console.print(f"[bold yellow]{'━' * 60}[/bold yellow]")
            console.print(f"  Disposition: {dp.disposition} ({dp.confidence:.0%} confidence)")
            console.print(f"  [dim]{dp.context_summary}[/dim]\n")
            console.print(f"  [bold red]Counter-case:[/bold red]")
            console.print(f"  {dp.counter_argument.argument}\n")
            console.print(f"  [bold red]Risk if wrong:[/bold red] {dp.counter_argument.risk_if_wrong}\n")
            if dp.counter_argument.recommended_mitigations:
                mitigations = ", ".join(dp.counter_argument.recommended_mitigations)
                console.print(f"  [dim]Mitigations: {mitigations}[/dim]\n")
            console.print(f"  [bold]Options:[/bold]")
            for opt in dp.options:
                console.print(f"    [{opt.option_id}] [bold]{opt.label}[/bold] — {opt.description}")
                for consequence in opt.consequences:
                    console.print(f"        • {consequence}")
                console.print(f"        Onboarding: {opt.onboarding_impact}")
                console.print(f"        Timeline: {opt.timeline}")
            console.print()

    def _save_review_session(self, client_id: str, session: ReviewSession):
        """Save review session data."""
        review_path = self.output_dir / client_id / "04_review"
        review_path.mkdir(parents=True, exist_ok=True)
        (review_path / "review_session.json").write_text(
            json.dumps(session.model_dump(), indent=2, default=str),
            encoding="utf-8"
        )
