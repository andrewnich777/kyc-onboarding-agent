#!/usr/bin/env python3
"""
KYC Client Onboarding Intelligence System

AI-powered KYC screening for individual and business client onboarding.
AI investigates. Rules classify. Humans decide.

Usage:
    python main.py --client test_cases/case1_individual_low.json
    python main.py --client test_cases/case3_business_critical.json --output results
    python main.py --client test_cases/case2_individual_pep.json --resume
    python main.py --finalize results/sarah_thompson
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Load .env file before other imports
from config import get_config

from agents import set_api_key
from pipeline import KYCPipeline


# Use legacy_windows mode for better Windows compatibility
console = Console(force_terminal=True, legacy_windows=True)


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="kyc-onboarding",
        description="KYC Client Onboarding Intelligence System - AI investigates. Rules classify. Humans decide.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --client test_cases/case1_individual_low.json
    %(prog)s --client test_cases/case2_individual_pep.json --output ./results
    %(prog)s --client test_cases/case3_business_critical.json --resume
    %(prog)s --finalize results/northern_maple_trading_corp

The system will:
  1. Classify client risk and plan investigation
  2. Run AI screening agents + deterministic utilities
  3. Synthesize findings into evidence-linked risk profile
  4. Pause for conversational review (ask questions, approve dispositions)
  5. Generate final compliance brief and onboarding summary

Output structure:
  results/{client_id}/
    01_intake/          Risk classification and investigation plan
    02_investigation/   Evidence store and screening results
    03_synthesis/       Evidence graph and proto-reports
    04_review/          Review session log
    05_output/          Final compliance brief + onboarding summary (MD + PDF)
        """
    )

    parser.add_argument(
        "--client",
        help="Path to client JSON file (individual or business)"
    )

    parser.add_argument(
        "-o", "--output",
        default="results",
        help="Output directory for results (default: results/)"
    )

    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress output"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0"
    )

    parser.add_argument(
        "--api-key",
        help="Anthropic API key (can also use ANTHROPIC_API_KEY env var)"
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint if available (skips completed stages)"
    )

    parser.add_argument(
        "--finalize",
        type=str,
        metavar="RESULTS_DIR",
        help="Finalize a paused review session. Pass the results directory path."
    )

    return parser


def display_summary(output):
    """Display a summary of the KYC results."""
    plan = output.intake_classification
    synthesis = output.synthesis

    # Risk level color mapping
    risk_colors = {
        "LOW": "green",
        "MEDIUM": "yellow",
        "HIGH": "red",
        "CRITICAL": "bold red",
    }

    # Client info panel
    client_data = output.client_data
    client_name = client_data.get("full_name") or client_data.get("legal_name", "Unknown")
    risk_level = plan.preliminary_risk.risk_level.value
    risk_color = risk_colors.get(risk_level, "white")

    info_lines = [
        f"[bold]{client_name}[/bold]",
        f"Type: {output.client_type.value.title()}",
        f"Client ID: {output.client_id}",
        f"Risk Level: [{risk_color}]{risk_level}[/{risk_color}] ({plan.preliminary_risk.total_score} pts)",
    ]

    if plan.applicable_regulations:
        info_lines.append(f"Regulations: {', '.join(plan.applicable_regulations)}")

    console.print(Panel(
        "\n".join(info_lines),
        title="KYC Client Profile",
        border_style="blue"
    ))

    # Risk factors table
    if plan.preliminary_risk.risk_factors:
        table = Table(title="Risk Factors")
        table.add_column("Factor", style="cyan")
        table.add_column("Points", justify="right")
        table.add_column("Category", style="dim")

        for rf in plan.preliminary_risk.risk_factors:
            table.add_row(rf.factor, str(rf.points), rf.category)

        console.print(table)

    # Synthesis results if available
    if synthesis:
        decision_colors = {
            "APPROVE": "green",
            "CONDITIONAL": "yellow",
            "ESCALATE": "red",
            "DECLINE": "bold red",
        }
        decision = synthesis.recommended_decision.value
        dec_color = decision_colors.get(decision, "white")

        console.print(f"\n[bold]Recommended Decision:[/bold] [{dec_color}]{decision}[/{dec_color}]")

        if synthesis.key_findings:
            console.print("\n[bold]Key Findings:[/bold]")
            for finding in synthesis.key_findings[:5]:
                console.print(f"  - {finding}")

        if synthesis.conditions:
            console.print("\n[bold yellow]Conditions:[/bold yellow]")
            for cond in synthesis.conditions:
                console.print(f"  - {cond}")

        if synthesis.items_requiring_review:
            console.print("\n[bold red]Items Requiring Review:[/bold red]")
            for item in synthesis.items_requiring_review:
                console.print(f"  - {item}")


async def main_async(args: argparse.Namespace) -> int:
    """Async main function."""
    verbose = not args.quiet

    # Set API key
    config = get_config()
    api_key = args.api_key or config.api_key

    if api_key:
        set_api_key(api_key)
    else:
        console.print("[bold red]Error:[/bold red] No API key found.")
        console.print("Set ANTHROPIC_API_KEY in .env file or pass --api-key argument.")
        return 1

    if verbose:
        console.print(Panel.fit(
            "[bold blue]KYC Client Onboarding Intelligence System[/bold blue]\n"
            "AI investigates. Rules classify. Humans decide.",
            border_style="blue"
        ))

    try:
        pipeline = KYCPipeline(
            output_dir=args.output,
            verbose=verbose,
            resume=args.resume
        )

        if args.finalize:
            # Finalize a paused review session
            result = await pipeline.finalize(args.finalize)
        elif args.client:
            # Load client data
            client_path = Path(args.client)
            if not client_path.exists():
                console.print(f"[bold red]Error:[/bold red] Client file not found: {args.client}")
                return 1

            client_data = json.loads(client_path.read_text(encoding="utf-8"))
            if verbose:
                client_name = client_data.get("full_name") or client_data.get("legal_name", "Unknown")
                console.print(f"\nProcessing: [bold]{client_name}[/bold]\n")

            result = await pipeline.run(client_data)
        else:
            console.print("[bold red]Error:[/bold red] Provide --client or --finalize argument.")
            return 1

        if verbose:
            console.print()
            display_summary(result)

        console.print(f"\n[bold green]Pipeline complete in {result.duration_seconds:.1f}s[/bold green]")

        # If paused for review, inform user
        if not result.synthesis or (result.review_session and not result.review_session.finalized):
            console.print("\n[bold yellow]Pipeline paused for review.[/bold yellow]")
            console.print("Review the proto-reports, ask questions, then run:")
            console.print(f"  python main.py --finalize results/{result.client_id}")

        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline cancelled by user[/yellow]")
        return 130

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if verbose:
            console.print_exception()
        return 1


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
