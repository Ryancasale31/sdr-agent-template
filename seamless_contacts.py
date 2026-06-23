"""
Seamless.ai Contact Discovery — FSE Sponsors

Searches Seamless.ai for VP/Director Marketing contacts at target companies.
Designed to run alongside tiga_contacts.py for broader coverage.

Usage:
    python seamless_contacts.py --min-score 70
    python seamless_contacts.py --company "ServiceMax"
    python seamless_contacts.py --company "ServiceMax" --max-contacts 5

Requires SEAMLESS_API_KEY in .env
Get your key: app.seamless.ai → Settings → Integrations → API
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

SEAMLESS_API_KEY = os.getenv("SEAMLESS_API_KEY")
BASE_URL = "https://api.seamless.ai/api/client/v1"

console = Console()

# Target titles for FSE sponsorship contacts
TARGET_TITLE_KEYWORDS = [
    "vp marketing", "vice president marketing",
    "director marketing", "director of marketing",
    "vp partnerships", "vp of partnerships",
    "head of marketing", "head of events",
    "chief marketing", "cmo",
    "vp sales", "vice president sales",
    "director partnerships", "director of partnerships",
    "marketing director", "marketing vp",
    "field marketing", "demand generation",
    "vp demand generation", "director demand generation",
]

SENIORITY_LEVELS = ["vp", "director", "c_suite", "partner", "svp", "evp"]


def title_matches(title: str) -> bool:
    t = (title or "").lower()
    return any(kw in t for kw in TARGET_TITLE_KEYWORDS)


def search_contacts(company_name: str, page: int = 1, page_size: int = 25) -> dict:
    """
    Search Seamless.ai for contacts at a company.

    Seamless.ai API reference:
      POST https://api.seamless.ai/v1/contacts/search
      Auth: Authorization: Bearer <key>

    If the endpoint or payload shape changes, update here.
    """
    if not SEAMLESS_API_KEY:
        raise ValueError("SEAMLESS_API_KEY not set in .env")

    headers = {
        "Authorization": f"Bearer {SEAMLESS_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Build title filter — Seamless supports OR across title values
    titles_to_search = [
        "VP Marketing",
        "Director of Marketing",
        "VP Partnerships",
        "Head of Marketing",
        "CMO",
        "VP Sales",
        "Director of Partnerships",
        "Head of Events",
        "VP Demand Generation",
        "Field Marketing Director",
    ]

    payload = {
        "company_name": company_name,
        "title": titles_to_search,           # list = OR across titles
        "seniority": SENIORITY_LEVELS,
        "country": ["United States"],
        "page": page,
        "page_size": page_size,
    }

    resp = requests.post(
        f"{BASE_URL}/search/contacts",
        headers=headers,
        json=payload,
        timeout=30,
    )

    if resp.status_code == 401:
        console.print("[red]Seamless.ai: 401 Unauthorized — check your SEAMLESS_API_KEY[/red]")
        return {}
    if resp.status_code == 402:
        console.print("[red]Seamless.ai: 402 — out of credits[/red]")
        return {}
    if not resp.ok:
        console.print(f"[yellow]Seamless.ai search error {resp.status_code}: {resp.text[:200]}[/yellow]")
        return {}

    return resp.json()


def get_contact_details(contact_id: str) -> dict:
    """
    Fetch full contact details (email, phone) by ID.
    Seamless charges credits per reveal — only call this on contacts you intend to reach.
    """
    headers = {
        "Authorization": f"Bearer {SEAMLESS_API_KEY}",
        "Accept": "application/json",
    }
    resp = requests.get(
        f"{BASE_URL}/contacts/{contact_id}",
        headers=headers,
        timeout=30,
    )
    if not resp.ok:
        return {}
    return resp.json()


def find_contacts_at_company(company_name: str, max_contacts: int = 3) -> list[dict]:
    """
    Search Seamless.ai for target contacts at a company, reveal top N.
    Returns normalized contact dicts.
    """
    console.print(f"  [cyan]Searching Seamless.ai for contacts at {company_name}...[/cyan]")

    result = search_contacts(company_name)
    if not result:
        return []

    # Seamless returns contacts under 'contacts' or 'data' key
    contacts_raw = result.get("contacts") or result.get("data") or []
    total = result.get("total") or len(contacts_raw)
    console.print(f"  [dim]Seamless found {total} candidates[/dim]")

    if not contacts_raw:
        return []

    # Filter by title match and pick top N
    matched = [c for c in contacts_raw if title_matches(c.get("title", ""))]
    if not matched:
        matched = contacts_raw  # fallback: take whatever Seamless returned

    top = matched[:max_contacts]

    # Reveal each contact to get email/phone (costs credits)
    enriched = []
    for raw in top:
        contact_id = raw.get("id") or raw.get("contact_id")
        if contact_id:
            details = get_contact_details(contact_id)
            merged = {**raw, **details}
        else:
            merged = raw

        # Normalize to our standard shape
        enriched.append(_normalize(merged, company_name))
        time.sleep(0.3)  # gentle rate limiting

    console.print(f"  [green]Revealed {len(enriched)} Seamless contacts[/green]")
    return enriched


def _normalize(raw: dict, source_company: str) -> dict:
    """
    Map Seamless.ai contact fields → our standard contact shape.
    Seamless returns email_addresses as a list; we take the first verified one.
    """
    emails = raw.get("email_addresses") or raw.get("emails") or []
    email = ""
    if isinstance(emails, list):
        # Prefer verified emails
        verified = [e for e in emails if isinstance(e, dict) and e.get("is_verified")]
        if verified:
            email = verified[0].get("email_address") or verified[0].get("email", "")
        elif emails:
            first = emails[0]
            email = first.get("email_address") or first.get("email", "") if isinstance(first, dict) else str(first)
    elif isinstance(emails, str):
        email = emails

    phones = raw.get("phone_numbers") or raw.get("phones") or []
    phone = ""
    if isinstance(phones, list) and phones:
        first_phone = phones[0]
        phone = first_phone.get("phone_number") or first_phone.get("phone", "") if isinstance(first_phone, dict) else str(first_phone)
    elif isinstance(phones, str):
        phone = phones

    return {
        "source": "seamless",
        "source_company": source_company,
        "first_name": raw.get("first_name", ""),
        "last_name": raw.get("last_name", ""),
        "title": raw.get("title", "") or raw.get("job_title", ""),
        "email": email,
        "phone": phone,
        "linkedin": raw.get("linkedin_url") or raw.get("linkedin", ""),
        "company": raw.get("company_name") or raw.get("company", "") or source_company,
        "seamless_id": raw.get("id") or raw.get("contact_id", ""),
    }


def save_contacts_csv(contacts: list[dict], output_file: str = "seamless_contacts.csv"):
    """Append contacts to CSV, deduplicating by email."""
    import csv
    if not contacts:
        console.print("[yellow]No Seamless contacts to save[/yellow]")
        return

    output_path = Path(output_file)
    existing_emails = set()
    existing_keys = set()

    if output_path.exists():
        with open(output_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("email"):
                    existing_emails.add(row["email"].lower())
                existing_keys.add((
                    row.get("company", "").lower(),
                    row.get("first_name", "").lower(),
                    row.get("last_name", "").lower(),
                ))

    rows = []
    skipped = 0
    for c in contacts:
        email = (c.get("email") or "").lower()
        key = (
            c.get("company", "").lower(),
            c.get("first_name", "").lower(),
            c.get("last_name", "").lower(),
        )
        if (email and email in existing_emails) or key in existing_keys:
            skipped += 1
            continue
        if email:
            existing_emails.add(email)
        existing_keys.add(key)
        rows.append(c)

    if not rows:
        console.print(f"  [dim]All Seamless contacts already in {output_file}[/dim]")
        return

    write_header = not output_path.exists() or output_path.stat().st_size == 0
    fieldnames = ["company", "email", "first_name", "last_name", "title",
                  "phone", "linkedin", "seamless_id", "source", "source_company"]

    with open(output_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    if skipped:
        console.print(f"  [dim]Skipped {skipped} duplicates[/dim]")

    table = Table(title=f"Seamless Contacts ({len(rows)} new)")
    table.add_column("Company", style="cyan")
    table.add_column("Name")
    table.add_column("Title")
    table.add_column("Email", style="green")
    for row in rows:
        table.add_row(
            row["company"],
            f"{row['first_name']} {row['last_name']}",
            row["title"],
            row["email"] or "[dim]not revealed[/dim]",
        )
    console.print(table)
    console.print(f"\n[green]Saved {len(rows)} contacts to {output_file}[/green]")


def main():
    parser = argparse.ArgumentParser(description="Seamless.ai contact discovery for FSE sponsors")
    parser.add_argument("--min-score", type=int, default=70, help="Min company score from scored_companies.json")
    parser.add_argument("--company", help="Single company to search")
    parser.add_argument("--max-contacts", type=int, default=3, help="Max contacts to reveal per company (each costs credits)")
    parser.add_argument("--output", default="seamless_contacts.csv", help="Output CSV filename")
    args = parser.parse_args()

    if not SEAMLESS_API_KEY:
        console.print("[red]SEAMLESS_API_KEY not set in .env[/red]")
        console.print("[dim]Get your key: app.seamless.ai → Settings → Integrations → API[/dim]")
        return

    all_contacts = []

    if args.company:
        contacts = find_contacts_at_company(args.company, max_contacts=args.max_contacts)
        all_contacts.extend(contacts)
    else:
        scored_file = Path("scored_companies.json")
        if not scored_file.exists():
            console.print("[red]scored_companies.json not found. Run score_company.py --batch first.[/red]")
            return

        with open(scored_file) as f:
            scored = json.load(f)

        targets = [c for c in scored if c.get("score", 0) >= args.min_score]
        console.print(f"\n[bold]Searching Seamless.ai for contacts at {len(targets)} companies (score ≥ {args.min_score})[/bold]\n")

        for company in targets:
            name = company["company"]
            score = company.get("score", 0)
            console.print(f"\n[bold]→ {name}[/bold] (score: {score})")
            contacts = find_contacts_at_company(name, max_contacts=args.max_contacts)
            all_contacts.extend(contacts)
            time.sleep(1)  # rate limiting between companies

    save_contacts_csv(all_contacts, args.output)

    if all_contacts:
        console.print(f"\n[bold green]Done! Next step:[/bold green]")
        console.print(f"python list_builder.py --seamless {args.output} --tiga tiga_contacts.csv")


if __name__ == "__main__":
    main()
