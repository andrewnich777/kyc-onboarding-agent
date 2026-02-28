"""
Review mixin for KYC Pipeline.

Handles Stage 4: Interactive compliance officer review loop.
Officers can ask questions (answered by Opus), approve dispositions,
add notes, and finalize — all recorded as an auditable ReviewSession.
"""

import asyncio
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from logger import get_logger
from models import (
    ReviewSession, ReviewAction, DecisionPoint, KYCSynthesisOutput,
    InvestigationPlan, ReviewIntelligence,
)
from agents.base import SimpleAgent

logger = get_logger(__name__)

console = Console(force_terminal=True, legacy_windows=True)

REVIEW_HELP = """
[bold]Interactive Review Commands:[/bold]

  [cyan]<question>[/cyan]        Ask any question about the case (answered by Opus)
  [cyan]decide <id> <option>[/cyan]  Approve a disposition (e.g. decide dp_1 B)
  [cyan]note <text>[/cyan]       Add an officer note to the review record
  [cyan]status[/cyan]            Show unresolved decision points
  [cyan]finalize[/cyan]          End review and proceed to final reports
  [cyan]help[/cyan]              Show this help message
""".strip()


def _build_review_context(
    synthesis: KYCSynthesisOutput,
    plan: InvestigationPlan,
    review_intel: ReviewIntelligence,
    evidence_store: list[dict],
) -> str:
    """Build context string for the review assistant agent."""
    parts = []

    # Key findings
    if synthesis and synthesis.key_findings:
        parts.append("KEY FINDINGS:")
        for f in synthesis.key_findings:
            parts.append(f"  - {f}")

    # Decision points
    if synthesis and synthesis.decision_points:
        parts.append("\nDECISION POINTS:")
        for dp in synthesis.decision_points:
            parts.append(f"  [{dp.decision_id}] {dp.title}")
            parts.append(f"    Disposition: {dp.disposition} ({dp.confidence:.0%} confidence)")
            parts.append(f"    Context: {dp.context_summary}")
            parts.append(f"    Counter-argument: {dp.counter_argument.argument}")
            for opt in dp.options:
                parts.append(f"    Option {opt.option_id}: {opt.label} — {opt.description}")

    # Risk assessment
    if synthesis and synthesis.revised_risk_assessment:
        ra = synthesis.revised_risk_assessment
        parts.append(f"\nRISK ASSESSMENT: {ra.risk_level.value} ({ra.total_score} pts)")
        for rf in ra.risk_factors:
            parts.append(f"  - {rf.factor} (+{rf.points} pts, {rf.category})")

    # Review intelligence highlights
    if review_intel:
        if review_intel.contradictions:
            parts.append(f"\nCONTRADICTIONS ({len(review_intel.contradictions)}):")
            for c in review_intel.contradictions:
                parts.append(f"  [{c.severity.value}] {c.agent_a} vs {c.agent_b}: {c.finding_a} vs {c.finding_b}")

        if review_intel.discussion_points:
            parts.append(f"\nDISCUSSION POINTS ({len(review_intel.discussion_points)}):")
            for dp in review_intel.discussion_points:
                parts.append(f"  [{dp.severity.value}] {dp.title}: {dp.reason}")

        conf = review_intel.confidence
        parts.append(f"\nEVIDENCE QUALITY: Grade {conf.overall_confidence_grade} "
                      f"(V:{conf.verified_pct:.0f}% S:{conf.sourced_pct:.0f}% "
                      f"I:{conf.inferred_pct:.0f}% U:{conf.unknown_pct:.0f}%)")

    # Evidence records (summarized)
    if evidence_store:
        parts.append(f"\nEVIDENCE STORE ({len(evidence_store)} records):")
        for ev in evidence_store[:30]:  # Cap at 30 to stay within context
            eid = ev.get("evidence_id", "?")
            claim = ev.get("claim", "")[:120]
            level = ev.get("evidence_level", "?")
            source = ev.get("source_name", "?")
            disp = ev.get("disposition", "?")
            parts.append(f"  [{eid}] ({level}) {source}: {claim} -> {disp}")
        if len(evidence_store) > 30:
            parts.append(f"  ... and {len(evidence_store) - 30} more records")

    # Regulations
    if plan and plan.applicable_regulations:
        parts.append(f"\nAPPLICABLE REGULATIONS: {', '.join(plan.applicable_regulations)}")

    # Recommended decision
    if synthesis:
        parts.append(f"\nRECOMMENDED DECISION: {synthesis.recommended_decision.value}")
        parts.append(f"REASONING: {synthesis.decision_reasoning}")

    return "\n".join(parts)


REVIEW_SYSTEM_PROMPT = """You are a KYC review assistant embedded in a compliance officer's terminal.
Your role is to answer questions about the current case using the evidence and findings provided.

Rules:
- Cite specific evidence IDs (e.g. [EV_001]) when referencing findings
- Be precise about what is verified vs inferred
- If you don't know something, say so — never fabricate evidence
- Keep answers concise but thorough — this is a compliance context
- Reference specific regulations when relevant (FINTRAC, CIRO, OFAC, FATCA)

Case context is provided below."""


class ReviewMixin:
    """Stage 4: Interactive compliance officer review."""

    async def _run_interactive_review(
        self,
        client_id: str,
        synthesis: KYCSynthesisOutput,
        plan: InvestigationPlan,
        review_intel: ReviewIntelligence,
        evidence_store: list[dict],
    ) -> ReviewSession:
        """Run the interactive review loop. Returns the finalized ReviewSession."""
        session = ReviewSession(client_id=client_id)

        # Build context for the review assistant
        case_context = _build_review_context(synthesis, plan, review_intel, evidence_store)

        # Build decision point lookup
        dp_lookup: dict[str, DecisionPoint] = {}
        if synthesis and synthesis.decision_points:
            for dp in synthesis.decision_points:
                dp_lookup[dp.decision_id] = dp

        console.print("\n[bold yellow]Stage 4: Interactive Review[/bold yellow]")
        console.print(Panel(
            REVIEW_HELP,
            title="Review Session",
            border_style="yellow",
        ))

        if dp_lookup:
            unresolved = [dp for dp in dp_lookup.values() if dp.officer_selection is None]
            console.print(f"  {len(unresolved)} decision point(s) awaiting review\n")
        else:
            console.print("  No decision points to review. Type [cyan]finalize[/cyan] to proceed.\n")

        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("[review] > ")
                )
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Review cancelled — session saved but not finalized[/yellow]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Parse commands
            cmd_lower = user_input.lower()

            if cmd_lower == "help":
                console.print(REVIEW_HELP)

            elif cmd_lower == "status":
                self._display_review_status(dp_lookup, session)

            elif cmd_lower == "finalize":
                session.finalized = True
                session.finalized_at = datetime.now()
                session.actions.append(ReviewAction(
                    action_type="finalize",
                    officer_note="Review session finalized by officer",
                ))
                self._save_review_session(client_id, session)
                console.print("[bold green]Review finalized. Proceeding to final reports.[/bold green]\n")
                break

            elif cmd_lower.startswith("decide "):
                self._handle_decide(user_input, dp_lookup, session, client_id)

            elif cmd_lower.startswith("note "):
                note_text = user_input[5:].strip()
                session.actions.append(ReviewAction(
                    action_type="add_note",
                    officer_note=note_text,
                ))
                self._save_review_session(client_id, session)
                console.print(f"  [green]Note recorded.[/green]")

            else:
                # Free-text question — send to review assistant
                await self._handle_review_question(
                    user_input, case_context, session, client_id
                )

        return session

    async def _handle_review_question(
        self,
        question: str,
        case_context: str,
        session: ReviewSession,
        client_id: str,
    ):
        """Send a free-text question to the Opus review assistant."""
        console.print("  [dim]Thinking...[/dim]")

        try:
            agent = SimpleAgent(
                agent_name="ReviewSession",
                system=REVIEW_SYSTEM_PROMPT + "\n\n" + case_context,
                agent_tools=[],  # No tools — pure reasoning
            )
            result = await agent.run(question)
            answer = result.get("text", "No response generated.")

            console.print(Panel(
                answer,
                title="Review Assistant",
                border_style="cyan",
                padding=(1, 2),
            ))

            session.actions.append(ReviewAction(
                action_type="query",
                query=question,
                response_summary=answer[:500],  # Truncate for audit log
            ))
            self._save_review_session(client_id, session)

        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")
            logger.exception("Review assistant error")

    def _handle_decide(
        self,
        user_input: str,
        dp_lookup: dict[str, DecisionPoint],
        session: ReviewSession,
        client_id: str,
    ):
        """Handle a decide command: decide <decision_id> <option>."""
        parts = user_input.split(None, 2)
        if len(parts) < 3:
            console.print("  [red]Usage: decide <decision_id> <option>[/red]")
            console.print(f"  Available: {', '.join(dp_lookup.keys())}")
            return

        decision_id = parts[1]
        option_id = parts[2].upper()

        if decision_id not in dp_lookup:
            console.print(f"  [red]Unknown decision point: {decision_id}[/red]")
            console.print(f"  Available: {', '.join(dp_lookup.keys())}")
            return

        dp = dp_lookup[decision_id]
        valid_options = {opt.option_id for opt in dp.options}
        if option_id not in valid_options:
            console.print(f"  [red]Invalid option '{option_id}' for {decision_id}[/red]")
            console.print(f"  Valid options: {', '.join(sorted(valid_options))}")
            return

        # Record the decision
        dp.officer_selection = option_id
        selected = next(opt for opt in dp.options if opt.option_id == option_id)

        session.actions.append(ReviewAction(
            action_type="approve_disposition",
            evidence_id=decision_id,
            officer_note=f"Selected option {option_id}: {selected.label}",
        ))
        self._save_review_session(client_id, session)

        console.print(f"  [green]Decision recorded: {dp.title}[/green]")
        console.print(f"    Selected: [{option_id}] {selected.label} — {selected.description}")

    def _display_review_status(
        self,
        dp_lookup: dict[str, DecisionPoint],
        session: ReviewSession,
    ):
        """Show unresolved decision points and session summary."""
        if not dp_lookup:
            console.print("  No decision points for this case.")
            console.print(f"  Actions taken: {len(session.actions)}")
            return

        table = Table(title="Decision Points", show_lines=False)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("Title", ratio=3)
        table.add_column("Status", width=12)

        for dp_id, dp in dp_lookup.items():
            if dp.officer_selection:
                status = f"[green]{dp.officer_selection}[/green]"
            else:
                status = "[yellow]PENDING[/yellow]"
            table.add_row(dp_id, dp.title[:50], status)

        console.print(table)

        unresolved = sum(1 for dp in dp_lookup.values() if dp.officer_selection is None)
        console.print(f"\n  {unresolved} unresolved, {len(session.actions)} actions taken")
