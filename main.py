"""
Field Service East — AI SDR Agent
Entry point. Run this first.
"""
import subprocess
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

console = Console()


def step(n, title, cmd, description):
    console.print(f"\n[bold cyan]Step {n}: {title}[/bold cyan]")
    console.print(f"[dim]{description}[/dim]")
    console.print(f"[green]→ Run:[/green] [bold]{cmd}[/bold]")


def main():
    console.print(Panel.fit(
        "[bold white]Field Service East — AI SDR Agent[/bold white]\n"
        "[dim]Orlando, FL | August 10-12, 2025[/dim]",
        border_style="cyan"
    ))

    console.print("\n[bold]Workflow Overview:[/bold]")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Step", style="cyan", width=6)
    table.add_column("What it does", width=45)
    table.add_column("Output", width=30)

    table.add_row("1", "Analyze attendee list → build ICP", "icp_summary.json")
    table.add_row("2", "Score target companies for sponsor fit", "scored_companies.json")
    table.add_row("3", "Pull contacts from Seamless.AI", "your_contacts.csv (manual)")
    table.add_row("4", "Generate 3-touch email sequences", "sequences.json + hubspot_import.csv")
    table.add_row("5", "Import to HubSpot → enroll in sequence", "Active outreach campaign")

    console.print(table)

    console.print("\n[bold yellow]── Run these commands in order ──[/bold yellow]")

    step(1, "Build ICP from attendee list",
         "python icp_profile.py",
         "Reads your CSV and extracts buyer profile, industries, seniority mix.")

    step(2, "Score target companies",
         "python score_company.py --batch target_companies.txt",
         "Claude scores each company 0-100 for sponsor fit. Takes ~2 min.")

    step(3, "Pull contacts in Seamless.AI",
         "(see seamless_search_queries.md)",
         "Search for VP/Director Marketing at your top-scored companies. Export CSV.")

    step(4, "Generate outreach sequences",
         "python generate_outreach.py --contacts your_contacts.csv",
         "Writes 3-touch personalized email sequence per contact. Exports HubSpot CSV.")

    step(5, "Import to HubSpot",
         "(see seamless_search_queries.md → HubSpot Import Steps)",
         "Import hubspot_import.csv, create sequences, enroll contacts.")

    console.print("\n[bold green]Quick test (single company):[/bold green]")
    console.print("python score_company.py \"ServiceMax\" \"Field service management software for asset-intensive industries\"")
    console.print("\npython generate_outreach.py \"ServiceMax\" \"jsmith@servicemax.com\" \"John Smith\" \"VP Marketing\" --description \"FSM software for medical and industrial\"")

    console.print("\n[dim]Need your ANTHROPIC_API_KEY in a .env file. Copy .env.example → .env and add your key.[/dim]\n")


if __name__ == "__main__":
    main()
