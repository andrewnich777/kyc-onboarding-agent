"""
Pipeline metrics for KYC system.

Captures per-stage timing, per-agent token usage, search stats,
evidence quality grading, and estimated cost. Displays as a Rich dashboard.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(force_terminal=True, legacy_windows=True)

# Pricing per 1M tokens (USD) — Anthropic published rates
MODEL_PRICING = {
    "claude-opus-4-6":   {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0},
}


@dataclass
class AgentMetric:
    """Metrics for a single agent run."""
    name: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0
    web_fetches: int = 0
    duration_seconds: float = 0.0


@dataclass
class StageMetric:
    """Timing for a pipeline stage."""
    name: str
    duration_seconds: float = 0.0


@dataclass
class PipelineMetrics:
    """Aggregated metrics for a full pipeline run."""
    stages: list[StageMetric] = field(default_factory=list)
    agents: list[AgentMetric] = field(default_factory=list)

    # Evidence quality (from review intelligence)
    evidence_grade: str = ""
    evidence_verified: int = 0
    evidence_sourced: int = 0
    evidence_inferred: int = 0
    evidence_unknown: int = 0
    evidence_total: int = 0

    @property
    def total_input_tokens(self) -> int:
        return sum(a.input_tokens for a in self.agents)

    @property
    def total_output_tokens(self) -> int:
        return sum(a.output_tokens for a in self.agents)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_searches(self) -> int:
        return sum(a.web_searches for a in self.agents)

    @property
    def total_duration(self) -> float:
        return sum(s.duration_seconds for s in self.stages)

    @property
    def estimated_cost_usd(self) -> float:
        cost = 0.0
        for a in self.agents:
            pricing = MODEL_PRICING.get(a.model, MODEL_PRICING.get("claude-sonnet-4-6", {}))
            cost += (a.input_tokens / 1_000_000) * pricing.get("input", 3.0)
            cost += (a.output_tokens / 1_000_000) * pricing.get("output", 15.0)
        return cost

    def to_dict(self) -> dict:
        return {
            "stages": [{"name": s.name, "duration_seconds": round(s.duration_seconds, 1)} for s in self.stages],
            "agents": [
                {
                    "name": a.name, "model": a.model,
                    "input_tokens": a.input_tokens, "output_tokens": a.output_tokens,
                    "web_searches": a.web_searches, "web_fetches": a.web_fetches,
                    "duration_seconds": round(a.duration_seconds, 1),
                }
                for a in self.agents
            ],
            "totals": {
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "total_tokens": self.total_tokens,
                "web_searches": self.total_searches,
                "duration_seconds": round(self.total_duration, 1),
                "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            },
            "evidence": {
                "grade": self.evidence_grade,
                "total": self.evidence_total,
                "verified": self.evidence_verified,
                "sourced": self.evidence_sourced,
                "inferred": self.evidence_inferred,
                "unknown": self.evidence_unknown,
            },
        }


def display_metrics(metrics: PipelineMetrics, target_console: Console = None):
    """Display a Rich metrics dashboard."""
    c = target_console or console

    c.print("\n[bold blue]Pipeline Metrics[/bold blue]\n")

    # Stage timing table
    stage_table = Table(title="Stage Timing", show_lines=False)
    stage_table.add_column("Stage", style="cyan", ratio=3)
    stage_table.add_column("Duration", justify="right", width=10)

    for s in metrics.stages:
        stage_table.add_row(s.name, f"{s.duration_seconds:.1f}s")

    stage_table.add_row("[bold]Total[/bold]", f"[bold]{metrics.total_duration:.1f}s[/bold]")
    c.print(stage_table)

    # Agent breakdown table
    if metrics.agents:
        c.print()
        agent_table = Table(title="Agent Breakdown", show_lines=False)
        agent_table.add_column("Agent", style="cyan", ratio=2)
        agent_table.add_column("Model", style="dim", ratio=2)
        agent_table.add_column("Tokens In", justify="right", width=10)
        agent_table.add_column("Tokens Out", justify="right", width=10)
        agent_table.add_column("Searches", justify="right", width=9)
        agent_table.add_column("Time", justify="right", width=8)

        for a in metrics.agents:
            model_short = a.model.replace("claude-", "").replace("-4-6", " 4.6")
            agent_table.add_row(
                a.name,
                model_short,
                f"{a.input_tokens:,}",
                f"{a.output_tokens:,}",
                str(a.web_searches + a.web_fetches),
                f"{a.duration_seconds:.1f}s",
            )

        agent_table.add_row(
            "[bold]Total[/bold]", "",
            f"[bold]{metrics.total_input_tokens:,}[/bold]",
            f"[bold]{metrics.total_output_tokens:,}[/bold]",
            f"[bold]{metrics.total_searches}[/bold]",
            "",
        )
        c.print(agent_table)

    # Summary panel
    grade_color = {"A": "green", "B": "green", "C": "yellow", "D": "red", "F": "red"}.get(
        metrics.evidence_grade, "white")

    summary_lines = [
        f"Total tokens: {metrics.total_tokens:,}",
        f"Estimated cost: ${metrics.estimated_cost_usd:.2f}",
        f"Web searches: {metrics.total_searches}",
    ]

    if metrics.evidence_grade:
        summary_lines.append(
            f"Evidence quality: [{grade_color}]Grade {metrics.evidence_grade}[/{grade_color}] "
            f"(V:{metrics.evidence_verified} S:{metrics.evidence_sourced} "
            f"I:{metrics.evidence_inferred} U:{metrics.evidence_unknown})"
        )

    c.print(Panel(
        "\n".join(summary_lines),
        title="Summary",
        border_style="blue",
    ))


def save_metrics(metrics: PipelineMetrics, output_dir: Path, client_id: str):
    """Save metrics to JSON file."""
    metrics_path = output_dir / client_id
    metrics_path.mkdir(parents=True, exist_ok=True)
    (metrics_path / "pipeline_metrics.json").write_text(
        json.dumps(metrics.to_dict(), indent=2),
        encoding="utf-8",
    )
