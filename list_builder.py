"""
FSE SDR List Builder — Unified Contact Pipeline

Orchestrates Seamless.ai + Tiga to build a deduplicated contact list,
then waterfall enriches via Tiga for any contacts missing email/phone.

Workflow:
  1. Search Seamless.ai for contacts at target companies
  2. Run Tiga contact discovery for same companies
  3. Merge & deduplicate across both sources
  4. Waterfall enrich any contacts still missing email via Tiga
  5. Export unified contacts.csv + generate_outreach-ready CSV

Usage:
    # Full pipeline: score → search → enrich → outreach
    python list_builder.py --min-score 70

    # From existing CSVs (skip re-running searches)
    python list_builder.py --seamless seamless_contacts.csv --tiga tiga_contacts.csv

    # Single company
    python list_builder.py --company "ServiceMax"

    # Skip Seamless (Tiga only)
    python list_builder.py --min-score 70 --no-seamless

    # Skip Tiga (Seamless only)
    python list_builder.py --min-score 70 --no-tiga
"""

import os
import csv
import json
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

console = Console()

SEAMLESS_API_KEY = os.getenv("SEAMLESS_API_KEY")
TIGA_API_KEY = os.getenv("TIGA_API_KEY")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_csv(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_csv(rows: list[dict], path: str, fieldnames: list[str] = None):
    if not rows:
        return
    if not fieldnames:
        # Collect all keys from all rows
        seen = {}
        for r in rows:
            for k in r.keys():
                seen[k] = True
        fieldnames = list(seen.keys())

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def email_key(contact: dict) -> str:
    return (
        contact.get("email") or
        contact.get("email_address") or
        ""
    ).lower().strip()


def name_key(contact: dict) -> tuple:
    return (
        (contact.get("first_name") or "").lower().strip(),
        (contact.get("last_name") or "").lower().strip(),
        (contact.get("company") or contact.get("account_name") or contact.get("source_company") or "").lower().strip(),
    )


def normalize_row(row: dict) -> dict:
    """Normalize field names to a consistent schema."""
    return {
        "company": (
            row.get("company") or
            row.get("account_name") or
            row.get("source_company") or
            row.get("company_name") or ""
        ).strip(),
        "first_name": row.get("first_name", "").strip(),
        "last_name": row.get("last_name", "").strip(),
        "title": row.get("title", "").strip(),
        "email": (
            row.get("email") or
            row.get("email_address") or ""
        ).strip(),
        "phone": (
            row.get("phone") or
            row.get("phone_number") or ""
        ).strip(),
        "linkedin": (
            row.get("linkedin") or
            row.get("linkedin_url") or
            row.get("person_linkedin") or ""
        ).strip(),
        "source": row.get("source", "unknown"),
        "seamless_id": row.get("seamless_id", ""),
        "tiga_person_id": row.get("tiga_person_id", ""),
        "score": row.get("score", ""),
        "description": row.get("description", ""),
        "company_industry": row.get("company_industry", ""),
        "company_domain": row.get("company_domain", ""),
    }


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def merge_contacts(sources: list[list[dict]]) -> list[dict]:
    """
    Merge contact lists from multiple sources, deduplicating by:
      1. Email address (exact match, case-insensitive)
      2. Name + Company (for contacts without email yet)

    When the same person appears in multiple sources, merge fields:
    email from whichever source has it, prefer Tiga enrichment for phone.
    """
    merged: dict[str, dict] = {}  # email_or_namekey → contact

    for source_list in sources:
        for raw in source_list:
            contact = normalize_row(raw)
            email = email_key(contact)
            nkey = name_key(contact)

            if email:
                if email in merged:
                    # Merge: fill in missing fields from this source
                    existing = merged[email]
                    for field in ["phone", "linkedin", "tiga_person_id", "seamless_id",
                                  "description", "company_industry", "company_domain"]:
                        if not existing.get(field) and contact.get(field):
                            existing[field] = contact[field]
                    # Track multiple sources
                    existing["source"] = _merge_sources(existing.get("source", ""), contact.get("source", ""))
                else:
                    merged[email] = contact
            else:
                # No email — dedupe by name+company
                nkey_str = "|".join(nkey)
                if nkey_str in merged:
                    existing = merged[nkey_str]
                    for field in ["phone", "linkedin", "tiga_person_id", "seamless_id"]:
                        if not existing.get(field) and contact.get(field):
                            existing[field] = contact[field]
                    existing["source"] = _merge_sources(existing.get("source", ""), contact.get("source", ""))
                else:
                    merged[nkey_str] = contact

    return list(merged.values())


def _merge_sources(a: str, b: str) -> str:
    parts = set(filter(None, a.split(",") + b.split(",")))
    return ",".join(sorted(parts))


# ---------------------------------------------------------------------------
# Tiga waterfall enrichment (for contacts missing email)
# ---------------------------------------------------------------------------

def tiga_enrich_missing(contacts: list[dict]) -> list[dict]:
    """
    For any contact missing an email, attempt Tiga waterfall enrichment.
    Only called if TIGA_API_KEY is set and contact has a LinkedIn URL or full name.
    """
    if not TIGA_API_KEY:
        return contacts

    import requests
    BASE_URL = "https://app.tigalabs.com"
    HEADERS = {"X-Tiga-Auth": TIGA_API_KEY, "Content-Type": "application/json"}

    needs_enrich = [c for c in contacts if not c.get("email") and
                    (c.get("linkedin") or (c.get("first_name") and c.get("last_name")))]

    if not needs_enrich:
        return contacts

    console.print(f"\n[cyan]Tiga waterfall enriching {len(needs_enrich)} contacts missing email...[/cyan]")

    for contact in needs_enrich:
        payload = {
            "first_name": contact.get("first_name", ""),
            "last_name": contact.get("last_name", ""),
            "company_name": contact.get("company", ""),
            "person_linkedin_url": contact.get("linkedin", ""),
            "title": contact.get("title", ""),
        }
        try:
            resp = requests.post(
                f"{BASE_URL}/api/v1/people/enrich-person",
                headers=HEADERS,
                json=payload,
                timeout=30,
            )
            if not resp.ok:
                continue

            enrich_id = resp.json().get("enrich_id")
            if not enrich_id:
                continue

            for _ in range(20):
                time.sleep(5)
                poll = requests.get(f"{BASE_URL}/api/v1/enrich/{enrich_id}", headers=HEADERS)
                if not poll.ok:
                    continue
                data = poll.json()
                if data.get("data_import_status", "Running") != "Running":
                    if data.get("email_address"):
                        contact["email"] = data["email_address"]
                        contact["source"] = _merge_sources(contact.get("source", ""), "tiga_enrich")
                    if data.get("phone") and not contact.get("phone"):
                        contact["phone"] = data["phone"]
                    break
        except Exception as e:
            console.print(f"  [dim]Enrich error for {contact.get('first_name')} {contact.get('last_name')}: {e}[/dim]")
            continue

    return contacts


# ---------------------------------------------------------------------------
# Stats display
# ---------------------------------------------------------------------------

def print_stats(contacts: list[dict], label: str = "Final list"):
    total = len(contacts)
    with_email = sum(1 for c in contacts if c.get("email"))
    with_phone = sum(1 for c in contacts if c.get("phone"))
    seamless = sum(1 for c in contacts if "seamless" in (c.get("source") or ""))
    tiga = sum(1 for c in contacts if "tiga" in (c.get("source") or ""))

    console.print(f"\n[bold]{label}[/bold]")
    console.print(f"  Total contacts:    [bold]{total}[/bold]")
    console.print(f"  With email:        [green]{with_email}[/green] ({with_email*100//total if total else 0}%)")
    console.print(f"  With phone:        {with_phone}")
    console.print(f"  From Seamless.ai:  {seamless}")
    console.print(f"  From Tiga:         {tiga}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

OUTPUT_FIELDNAMES = [
    "company", "email", "first_name", "last_name", "title",
    "phone", "linkedin", "description", "source",
    "seamless_id", "tiga_person_id", "score",
    "company_industry", "company_domain",
]


def main():
    parser = argparse.ArgumentParser(description="FSE SDR list builder — Seamless + Tiga unified pipeline")
    parser.add_argument("--min-score", type=int, default=70, help="Min company score (used when running fresh searches)")
    parser.add_argument("--company", help="Single company name")
    parser.add_argument("--seamless", help="Path to existing seamless_contacts.csv (skip re-running Seamless search)")
    parser.add_argument("--tiga", help="Path to existing tiga_contacts.csv (skip re-running Tiga search)")
    parser.add_argument("--no-seamless", action="store_true", help="Skip Seamless.ai")
    parser.add_argument("--no-tiga", action="store_true", help="Skip Tiga")
    parser.add_argument("--no-enrich", action="store_true", help="Skip Tiga waterfall enrichment pass")
    parser.add_argument("--max-contacts", type=int, default=3, help="Max contacts per company (Seamless)")
    parser.add_argument("--output", default="contacts.csv", help="Output unified contacts CSV")
    args = parser.parse_args()

    all_sources = []

    # ── Seamless.ai ──────────────────────────────────────────────────────────
    if not args.no_seamless:
        if args.seamless:
            # Load from existing CSV
            seamless_rows = load_csv(args.seamless)
            console.print(f"[dim]Loaded {len(seamless_rows)} contacts from {args.seamless}[/dim]")
            all_sources.append(seamless_rows)
        elif SEAMLESS_API_KEY:
            # Run live search
            from seamless_contacts import find_contacts_at_company, save_contacts_csv as sl_save
            seamless_contacts = []

            if args.company:
                seamless_contacts = find_contacts_at_company(args.company, args.max_contacts)
            else:
                scored_file = Path("scored_companies.json")
                if scored_file.exists():
                    with open(scored_file) as f:
                        scored = json.load(f)
                    targets = [c for c in scored if c.get("score", 0) >= args.min_score]
                    console.print(f"\n[bold]Seamless.ai: searching {len(targets)} companies...[/bold]")
                    for co in targets:
                        name = co["company"]
                        score = co.get("score", 0)
                        console.print(f"\n[bold]→ {name}[/bold] (score: {score})")
                        contacts = find_contacts_at_company(name, args.max_contacts)
                        for c in contacts:
                            c["score"] = score
                        seamless_contacts.extend(contacts)
                        time.sleep(1)

            if seamless_contacts:
                sl_save(seamless_contacts, "seamless_contacts.csv")
            all_sources.append(seamless_contacts)
        else:
            console.print("[yellow]SEAMLESS_API_KEY not set — skipping Seamless.ai[/yellow]")
            console.print("[dim]Get your key: app.seamless.ai → Settings → Integrations → API[/dim]")

    # ── Tiga ─────────────────────────────────────────────────────────────────
    if not args.no_tiga:
        if args.tiga:
            # Load from existing CSV
            tiga_rows = load_csv(args.tiga)
            console.print(f"[dim]Loaded {len(tiga_rows)} contacts from {args.tiga}[/dim]")
            all_sources.append(tiga_rows)
        elif TIGA_API_KEY:
            # Run live Tiga search
            import subprocess, sys
            if args.company:
                cmd = [sys.executable, "tiga_contacts.py", "--company", args.company]
            else:
                cmd = [sys.executable, "tiga_contacts.py", "--min-score", str(args.min_score)]
            console.print(f"\n[bold]Running Tiga contact discovery...[/bold]")
            subprocess.run(cmd, check=False)
            # Load results
            tiga_rows = load_csv("tiga_contacts.csv")
            all_sources.append(tiga_rows)
        else:
            console.print("[yellow]TIGA_API_KEY not set — skipping Tiga[/yellow]")

    if not any(all_sources):
        console.print("[red]No contact sources available. Check API keys.[/red]")
        return

    # ── Merge & deduplicate ───────────────────────────────────────────────────
    console.print("\n[bold]Merging and deduplicating contacts...[/bold]")
    merged = merge_contacts(all_sources)
    print_stats(merged, "After merge")

    # ── Waterfall enrich missing emails ──────────────────────────────────────
    if not args.no_enrich and TIGA_API_KEY:
        merged = tiga_enrich_missing(merged)
        print_stats(merged, "After Tiga enrichment")

    # ── Save unified output ───────────────────────────────────────────────────
    save_csv(merged, args.output, OUTPUT_FIELDNAMES)
    console.print(f"\n[bold green]✓ Saved {len(merged)} contacts → {args.output}[/bold green]")

    # ── Also write a generate_outreach-compatible CSV ─────────────────────────
    outreach_file = "contacts_for_outreach.csv"
    outreach_rows = [
        {
            "company": c["company"],
            "email": c["email"],
            "first_name": c["first_name"],
            "last_name": c["last_name"],
            "title": c["title"],
            "description": c.get("description", ""),
        }
        for c in merged if c.get("email")
    ]
    save_csv(outreach_rows, outreach_file,
             ["company", "email", "first_name", "last_name", "title", "description"])
    console.print(f"[bold green]✓ Outreach-ready CSV ({len(outreach_rows)} with email) → {outreach_file}[/bold green]")

    console.print(f"\n[bold]Next step:[/bold]")
    console.print(f"  python generate_outreach.py --contacts {outreach_file}")


if __name__ == "__main__":
    main()
