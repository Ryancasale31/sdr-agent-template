"""
Tiga Buying Intent Signals — layers on top of score_company.py results.

Reads scored_companies.json and enriches each company with Tiga signals:
  - Recent funding (last 90 days)
  - Actively hiring for marketing/sales roles
  - Uses field service or related technology

Outputs tiga_scored_companies.json with combined score + signal data.

Usage:
    python tiga_signals.py --min-score 60
"""
import os
import json
import time
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

TIGA_API_KEY = os.getenv("TIGA_API_KEY")
BASE_URL = "https://app.tigalabs.com"
HEADERS = {
    "X-Tiga-Auth": TIGA_API_KEY,
    "Content-Type": "application/json",
}

console = Console()

SIGNALS = [
    {
        "key": "recent_funding",
        "label": "Recent Funding (90d)",
        "config": {
            "type": "gpt",
            "prompt": "Has {{.AccountName}} raised a funding round in the last 90 days (after {{.Last90Days}})? Answer yes or no with round size if known.",
            "is_account_insight": True,
            "can_use_web_search": True,
            "expiration_in_days": 90,
            "word_limit": 40,
        },
    },
    {
        "key": "hiring_marketing",
        "label": "Hiring Marketing/Sales",
        "config": {
            "type": "hiring_for_role",
            "is_account_insight": True,
        },
    },
    {
        "key": "field_service_fit",
        "label": "Field Service Tech Fit",
        "config": {
            "type": "gpt",
            "prompt": "Does {{.AccountName}} ({{.AccountWebsite}}) sell software or services to companies that manage field service operations, field technicians, or service dispatch? Answer yes or no with a 1-sentence reason.",
            "is_account_insight": True,
            "can_use_web_search": True,
            "expiration_in_days": 30,
            "word_limit": 50,
        },
    },
]


def get_or_create_signal(label: str, config: dict) -> str:
    """Get existing signal by label or create a new one. Returns signal ID."""
    # Check existing signals
    resp = requests.get(
        f"{BASE_URL}/api/v1/signals?is_computed_column=true&account_columns_only=true",
        headers=HEADERS,
    )
    if resp.ok:
        for sig in resp.json():
            if sig.get("label") == label:
                console.print(f"  [dim]Using existing signal: {label}[/dim]")
                return sig["id"]

    # Create new signal
    resp = requests.post(
        f"{BASE_URL}/api/v1/signal",
        headers=HEADERS,
        json={
            "label": label,
            "is_computed_column": True,
            "type": "text",
            "computed_config": config,
        },
    )
    if resp.ok:
        sig_id = resp.json()["id"]
        console.print(f"  [green]Created signal: {label} ({sig_id})[/green]")
        return sig_id

    console.print(f"  [red]Failed to create signal {label}: {resp.text}[/red]")
    return None


def get_or_create_account(company_name: str) -> str:
    """Get or create a Tiga account by company name. Returns account ID."""
    # Try to find existing
    resp = requests.get(
        f"{BASE_URL}/api/v1/accounts",
        headers=HEADERS,
        headers={**HEADERS, "Tiga-Filter": json.dumps({"search_term": company_name})},
    )
    if resp.ok:
        accounts = resp.json()
        if isinstance(accounts, list) and accounts:
            return accounts[0]["id"]

    # Create account
    resp = requests.post(
        f"{BASE_URL}/api/v1/account",
        headers=HEADERS,
        json={"name": company_name},
    )
    if resp.ok:
        return resp.json()["id"]
    if resp.status_code == 409:
        # Already exists, search again
        resp2 = requests.get(
            f"{BASE_URL}/api/v1/accounts",
            headers={**HEADERS, "Tiga-Filter": json.dumps({"search_term": company_name})},
        )
        if resp2.ok:
            accounts = resp2.json()
            if isinstance(accounts, list) and accounts:
                return accounts[0]["id"]
    return None


def run_signal_on_account(signal_id: str, account_id: str, company_name: str) -> str:
    """Run a signal on a single account. Returns the signal value."""
    resp = requests.post(
        f"{BASE_URL}/api/v1/signal/{signal_id}/run-signal",
        headers=HEADERS,
        json={"account": {"domain": ""}},  # fallback — will use account_id if needed
    )

    # Try with account name/domain lookup
    resp = requests.post(
        f"{BASE_URL}/api/v1/signal/{signal_id}/run-signal",
        headers=HEADERS,
        json={"account": {"domain": company_name.lower().replace(" ", "") + ".com"}},
    )

    if resp.ok:
        data = resp.json()
        account = data.get("account", {})
        custom_cols = account.get("custom_columns", {})
        if signal_id in custom_cols:
            col = custom_cols[signal_id]
            if col.get("status") == 1:  # SUCCESS
                return col.get("value", "")
    return ""


def score_with_signals(company: dict, signal_ids: dict) -> dict:
    """Run all signals on a company and compute a signal bonus score."""
    name = company["company"]
    console.print(f"  Running signals on [cyan]{name}[/cyan]...")

    signal_results = {}
    signal_bonus = 0

    for sig_key, sig_id in signal_ids.items():
        value = run_signal_on_account(sig_id, None, name)
        signal_results[sig_key] = value

        # Add bonus points for positive signals
        if value and value.lower().startswith("yes"):
            signal_bonus += 10
            console.print(f"    [green]✓ {sig_key}: {value[:60]}[/green]")
        elif value:
            console.print(f"    [dim]✗ {sig_key}: {value[:60]}[/dim]")

    return {
        **company,
        "signal_results": signal_results,
        "signal_bonus": signal_bonus,
        "combined_score": min(100, company.get("score", 0) + signal_bonus),
    }


def main():
    parser = argparse.ArgumentParser(description="Layer Tiga buying intent signals on scored companies")
    parser.add_argument("--min-score", type=int, default=60, help="Min ICP score to run signals on")
    parser.add_argument("--input", default="scored_companies.json")
    parser.add_argument("--output", default="tiga_scored_companies.json")
    args = parser.parse_args()

    if not TIGA_API_KEY:
        console.print("[red]TIGA_API_KEY not set in .env[/red]")
        return

    input_file = Path(args.input)
    if not input_file.exists():
        console.print(f"[red]{args.input} not found. Run score_company.py --batch first.[/red]")
        return

    with open(input_file) as f:
        scored = json.load(f)

    targets = [c for c in scored if c.get("score", 0) >= args.min_score]
    console.print(f"\n[bold]Running Tiga signals on {len(targets)} companies (score ≥ {args.min_score})[/bold]\n")

    # Create signals once
    console.print("[bold]Setting up signals...[/bold]")
    signal_ids = {}
    for sig in SIGNALS:
        sig_id = get_or_create_signal(sig["label"], sig["config"])
        if sig_id:
            signal_ids[sig["key"]] = sig_id

    console.print(f"\n[bold]Scoring companies...[/bold]\n")
    results = []
    for company in targets:
        enriched = score_with_signals(company, signal_ids)
        results.append(enriched)

    # Sort by combined score
    results.sort(key=lambda x: x["combined_score"], reverse=True)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    # Summary table
    table = Table(title="Companies + Signal Scores")
    table.add_column("Company", style="cyan")
    table.add_column("ICP Score", justify="right")
    table.add_column("Signal Bonus", justify="right", style="green")
    table.add_column("Combined", justify="right", style="bold")
    table.add_column("Funding")
    table.add_column("Hiring")

    for r in results[:15]:
        funding = "✓" if r["signal_results"].get("recent_funding", "").lower().startswith("yes") else "—"
        hiring = "✓" if r["signal_results"].get("hiring_marketing", "").lower().startswith("yes") else "—"
        table.add_row(
            r["company"],
            str(r["score"]),
            f"+{r['signal_bonus']}",
            str(r["combined_score"]),
            funding,
            hiring,
        )
    console.print(table)
    console.print(f"\n[green][OK] Saved to {args.output}[/green]")
    console.print(f"\n[bold]Next step:[/bold] python tiga_contacts.py --min-score 70")


if __name__ == "__main__":
    main()
