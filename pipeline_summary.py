"""
Pipeline Summary — shows how many companies have contacts on GitHub.
Usage: python pipeline_summary.py
"""
import os, json, base64, requests
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "Ryancasale31/sdr-agent-template")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "data")
console = Console()

def main():
    if not GITHUB_TOKEN:
        console.print("[red]GITHUB_TOKEN not set in .env[/red]")
        return

    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/pipeline.json",
        params={"ref": GITHUB_BRANCH},
        headers=headers,
    )
    if not r.ok:
        console.print(f"[red]Failed to fetch pipeline.json: {r.status_code} {r.text}[/red]")
        return

    data = json.loads(base64.b64decode(r.json()["content"]))

    with_contacts    = [e for e in data if e.get("contacts")]
    without_contacts = [e for e in data if not e.get("contacts")]
    total_contacts   = sum(len(e["contacts"]) for e in with_contacts)

    console.print(f"\n[bold]Pipeline Summary[/bold]")
    console.print(f"  Total companies:       {len(data)}")
    console.print(f"  With contacts:         [green]{len(with_contacts)}[/green]")
    console.print(f"  Without contacts:      [yellow]{len(without_contacts)}[/yellow]")
    console.print(f"  Total contacts found:  [green]{total_contacts}[/green]")

    if with_contacts:
        console.print("\n[bold]Companies with contacts:[/bold]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Company", style="white")
        table.add_column("# Contacts", justify="center")
        table.add_column("Contacts", style="dim")
        for e in with_contacts:
            names = ", ".join(
                f"{c.get('first_name','')} {c.get('last_name','')}".strip()
                for c in e["contacts"]
            )
            table.add_row(e["company"], str(len(e["contacts"])), names)
        console.print(table)

    if without_contacts:
        console.print(f"\n[bold yellow]Still no contacts ({len(without_contacts)} companies):[/bold yellow]")
        for e in without_contacts:
            console.print(f"  - {e['company']}")

if __name__ == "__main__":
    main()
