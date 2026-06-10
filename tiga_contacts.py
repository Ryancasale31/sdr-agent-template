"""
Tiga Contact Discovery — replaces manual Seamless.AI step.

Reads scored_companies.json, finds and enriches contacts at each company
using Tiga's Find People Agent + people search + Waterfall Enrichment.

Usage:
    python tiga_contacts.py --min-score 70
    python tiga_contacts.py --company "ServiceMax"
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

# Keywords to match in titles
TARGET_TITLE_KEYWORDS = [
    "vp marketing", "vice president marketing",
    "director marketing", "director of marketing",
    "vp partnerships", "vp of partnerships",
    "head of marketing",
    "chief marketing", "cmo",
    "vp sales", "vice president sales",
    "director partnerships", "director of partnerships",
    "marketing director", "marketing vp",
]

console = Console()


def title_matches(title: str) -> bool:
    """Check if a title matches our target roles."""
    t = (title or "").lower()
    return any(kw in t for kw in TARGET_TITLE_KEYWORDS)


def run_find_people_agent(company_name: str) -> int:
    """Run the Find People Agent to populate Tiga's DB. Returns count found."""
    description = (
        f"VP Marketing, Director of Marketing, VP Partnerships, "
        f"Head of Marketing, CMO, or VP Sales at {company_name}, "
        f"based in the United States"
    )
    resp = requests.post(
        f"{BASE_URL}/api/v1/agent/find-people",
        headers=HEADERS,
        json={"contact_description": description, "model": "gpt-5.4-2026-03-05"},
    )
    if not resp.ok:
        return 0

    status_id = resp.json().get("status_id")
    if not status_id:
        return 0

    for _ in range(18):  # max ~2 minutes
        time.sleep(7)
        poll = requests.get(
            f"{BASE_URL}/api/agent/find-people/{status_id}/status",
            headers=HEADERS,
        )
        if not poll.ok:
            continue
        data = poll.json()
        status = data.get("status", "")
        if status == "Complete":
            return len(data.get("created_flux_ids") or [])
        elif status.startswith("Error"):
            return 0

    return 0


def search_people_at_company(company_name: str) -> list[dict]:
    """Search Tiga's people database for contacts at a company."""
    # Build a list of search terms to try: full name, then first meaningful word
    search_terms = [company_name]
    first_word = company_name.split()[0]
    if first_word.lower() not in ("the", "a", "an") and first_word != company_name:
        search_terms.append(first_word)

    all_people = []
    for term in search_terms:
        resp = requests.get(
            f"{BASE_URL}/api/v1/people",
            headers={**HEADERS, "Tiga-Filter": json.dumps({
                "search_term": term,
                "person_location_country": "United States",
            })},
        )
        if not resp.ok:
            continue
        data = resp.json()
        if data is None:
            continue
        rows = data if isinstance(data, list) else (data.get("rows") or [])
        all_people.extend(rows)
        if rows:
            break  # found results, no need to try shorter term

    # Deduplicate by person id
    seen = set()
    unique_people = []
    for p in all_people:
        pid = p.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            unique_people.append(p)

    # Post-filter: keep only US-based contacts
    US_COUNTRY_VARIANTS = {"united states", "us", "usa", "u.s.", "u.s.a."}
    US_STATES = {
        "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
        "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
        "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
        "minnesota","mississippi","missouri","montana","nebraska","nevada",
        "new hampshire","new jersey","new mexico","new york","north carolina",
        "north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island",
        "south carolina","south dakota","tennessee","texas","utah","vermont",
        "virginia","washington","west virginia","wisconsin","wyoming","washington dc",
        "district of columbia",
        # abbreviations
        "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia",
        "ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj",
        "nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn","tx","ut","vt",
        "va","wa","wv","wi","wy","dc",
    }

    def is_us_based(person: dict) -> bool:
        country = (
            person.get("person_location_country")
            or person.get("account_country")
            or person.get("country")
            or ""
        ).lower().strip()
        state = (
            person.get("person_location_state")
            or person.get("account_region")
            or person.get("state")
            or ""
        ).lower().strip()
        city_state = (person.get("person_location_city") or "").lower()

        # Explicit non-US country → reject
        if country and country not in US_COUNTRY_VARIANTS and not country.startswith("united states"):
            return False
        # Explicit US country → keep
        if country in US_COUNTRY_VARIANTS or country.startswith("united states"):
            return True
        # No country — check state
        if state and state in US_STATES:
            return True
        if state and state not in US_STATES:
            return False  # has a state but it's not a US state → reject
        # No country, no state — check if city looks US (rough heuristic: contains a US state abbrev)
        for abbrev in ["ca", "ny", "tx", "fl", "il", "pa", "oh", "ga", "nc", "wa"]:
            if f", {abbrev}" in city_state:
                return True
        # No location data at all → keep (can't tell, better to include)
        return True

    # Sort: US-based first, then everyone else
    unique_people.sort(key=lambda p: 0 if is_us_based(p) else 1)

    # Filter: account name shares a significant word with company name, and title matches
    # Ignore generic words that match too broadly
    STOP_WORDS = {"the", "a", "an", "of", "and", "for", "in", "at", "by", "to", "inc", "llc", "ltd", "corp", "group"}
    company_words = [w.lower() for w in company_name.split() if len(w) >= 3 and w.lower() not in STOP_WORDS]
    matched = []
    for p in unique_people:
        acct = (p.get("account_name") or "").lower()
        acct_words = [w for w in acct.split() if len(w) >= 3 and w not in STOP_WORDS]
        name_match = any(w in acct for w in company_words) or any(w in company_name.lower() for w in acct_words)
        if name_match and title_matches(p.get("title", "")):
            matched.append(p)

    return matched


def enrich_person(person: dict) -> dict:
    """Waterfall enrich a contact to get verified email + phone."""
    resp = requests.post(
        f"{BASE_URL}/api/v1/people/enrich-person",
        headers=HEADERS,
        json={
            "first_name": person.get("first_name", ""),
            "last_name": person.get("last_name", ""),
            "company_name": person.get("account_name", ""),
            "person_linkedin_url": person.get("linkedin_url") or person.get("person_linkedin", ""),
            "title": person.get("title", ""),
        },
    )
    if not resp.ok:
        return person

    enrich_id = resp.json().get("enrich_id")
    if not enrich_id:
        return person

    for _ in range(30):
        time.sleep(5)
        poll = requests.get(f"{BASE_URL}/api/v1/enrich/{enrich_id}", headers=HEADERS)
        if not poll.ok:
            continue
        data = poll.json()
        if data.get("data_import_status", "Running") != "Running":
            # Merge enriched email/phone back onto person
            enriched = dict(person)
            if data.get("email_address"):
                enriched["email_address"] = data["email_address"]
            if data.get("phone"):
                enriched["phone"] = data["phone"]
            return enriched

    return person


def find_people(company_name: str, use_agent: bool = True) -> list[dict]:
    """Find and return target contacts at a company."""
    console.print(f"  [cyan]Searching Tiga for contacts at {company_name}...[/cyan]")

    # First: check if we already have contacts in Tiga before running the agent
    people = search_people_at_company(company_name)
    if people:
        console.print(f"  [green]Found {len(people)} existing contacts[/green]")
        return people

    if not use_agent:
        return []

    # Only run Find People Agent if nothing found locally
    console.print(f"  [dim]Running Find People Agent...[/dim]")
    n = run_find_people_agent(company_name)
    console.print(f"  [dim]Agent added {n} new records[/dim]")

    # Search again after agent run
    people = search_people_at_company(company_name)
    console.print(f"  [green]Found {len(people)} matching contacts[/green]")
    return people


PIPELINE_FILE = Path(__file__).parent / "pipeline.json"


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Ryancasale31/sdr-agent-template")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "data")
GITHUB_API = "https://api.github.com"


def _gh_headers():
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}


def _load_pipeline_from_github() -> list:
    """Load pipeline.json from GitHub data branch."""
    import base64
    resp = requests.get(
        f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/pipeline.json",
        params={"ref": GITHUB_BRANCH},
        headers=_gh_headers(),
    )
    if resp.ok:
        return json.loads(base64.b64decode(resp.json()["content"]).decode("utf-8"))
    return None


def _save_pipeline_to_github(pipeline: list) -> bool:
    """Save pipeline.json to GitHub data branch."""
    import base64
    # Get current SHA
    resp = requests.get(
        f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/pipeline.json",
        params={"ref": GITHUB_BRANCH},
        headers=_gh_headers(),
    )
    sha = resp.json().get("sha") if resp.ok else None
    content = base64.b64encode(json.dumps(pipeline, indent=2, ensure_ascii=False).encode()).decode()
    payload = {"message": "Update pipeline contacts via tiga_contacts.py", "content": content, "branch": GITHUB_BRANCH}
    if sha:
        payload["sha"] = sha
    put = requests.put(
        f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/pipeline.json",
        headers=_gh_headers(),
        json=payload,
    )
    return put.ok


def save_contacts_to_pipeline(company_name: str, contacts: list[dict]):
    """Write enriched contacts into pipeline and sync to GitHub so app updates."""
    if not contacts:
        return

    # Try GitHub first, fall back to local
    pipeline = None
    use_github = bool(GITHUB_TOKEN)
    if use_github:
        pipeline = _load_pipeline_from_github()
    if pipeline is None:
        if not PIPELINE_FILE.exists():
            return
        with open(PIPELINE_FILE, encoding="utf-8") as f:
            pipeline = json.load(f)
        use_github = False

    name_lower = company_name.lower()
    updated = False
    for entry in pipeline:
        entry_name = (entry.get("company") or "").lower()
        if name_lower in entry_name or entry_name in name_lower:
            existing = entry.get("contacts") or []
            existing_emails = {c.get("email", "").lower() for c in existing}
            added = 0
            for c in contacts:
                email = (c.get("email_address") or "").lower()
                if email and email in existing_emails:
                    continue
                existing.append({
                    "name": f"{c.get('first_name','')} {c.get('last_name','')}".strip(),
                    "title": c.get("title", ""),
                    "email": c.get("email_address", ""),
                    "phone": c.get("phone", "") or c.get("account_phone", ""),
                    "linkedin": c.get("linkedin_url") or c.get("person_linkedin", ""),
                    "source": "tiga",
                })
                if email:
                    existing_emails.add(email)
                added += 1
            entry["contacts"] = existing
            if added:
                console.print(f"  [blue]→ Added {added} contact(s) to pipeline[/blue]")
                updated = True
            break

    if updated:
        try:
            if use_github:
                ok = _save_pipeline_to_github(pipeline)
                if ok:
                    console.print(f"  [blue]→ Synced to GitHub ✓[/blue]")
                else:
                    console.print(f"  [yellow]GitHub sync failed — saved locally[/yellow]")
                    with open(PIPELINE_FILE, "w", encoding="utf-8") as f:
                        json.dump(pipeline, f, indent=2, ensure_ascii=False)
            else:
                with open(PIPELINE_FILE, "w", encoding="utf-8") as f:
                    json.dump(pipeline, f, indent=2, ensure_ascii=False)
        except Exception as e:
            console.print(f"  [yellow]Warning: could not save pipeline: {e}[/yellow]")


def process_companies(companies: list[dict], use_agent: bool = True) -> list[dict]:
    """Find and enrich contacts for a list of companies."""
    all_contacts = []

    for company in companies:
        name = company["company"]
        score = company.get("score", 0)
        console.print(f"\n[bold]→ {name}[/bold] (score: {score})")

        people = find_people(name, use_agent=use_agent)
        if not people:
            console.print(f"  [yellow]No matching contacts found[/yellow]")
            continue

        # Enrich top 2 contacts per company
        enriched_batch = []
        for person in people[:2]:
            console.print(f"  Enriching {person.get('first_name','')} {person.get('last_name','')} ({person.get('title','')})")
            enriched = enrich_person(person)
            enriched["source_company_score"] = score
            enriched["source_company"] = name
            enriched_batch.append(enriched)
            all_contacts.append(enriched)

        # Write to pipeline.json immediately so app updates in real time
        save_contacts_to_pipeline(name, enriched_batch)

    return all_contacts


def save_contacts_csv(contacts: list[dict], output_file: str = "tiga_contacts.csv"):
    """Append enriched contacts to CSV, skipping duplicates by email."""
    import csv
    if not contacts:
        console.print("[yellow]No contacts to save[/yellow]")
        return

    # Load existing emails to avoid duplicates
    existing_emails = set()
    existing_companies = set()
    output_path = Path(output_file)
    if output_path.exists():
        with open(output_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("email"):
                    existing_emails.add(row["email"].lower())
                existing_companies.add((row.get("company","").lower(), row.get("first_name","").lower(), row.get("last_name","").lower()))

    rows = []
    skipped = 0
    for c in contacts:
        email = (c.get("email_address") or "").lower()
        key = (
            (c.get("source_company") or c.get("account_name","")).lower(),
            c.get("first_name","").lower(),
            c.get("last_name","").lower()
        )
        if (email and email in existing_emails) or key in existing_companies:
            skipped += 1
            continue
        if email:
            existing_emails.add(email)
        existing_companies.add(key)
        rows.append({
            "company": c.get("source_company") or c.get("account_name", ""),
            "email": c.get("email_address", ""),
            "first_name": c.get("first_name", ""),
            "last_name": c.get("last_name", ""),
            "title": c.get("title", ""),
            "description": "",
            "linkedin": c.get("linkedin_url") or c.get("person_linkedin", ""),
            "phone": c.get("phone", ""),
            "score": c.get("source_company_score", ""),
            "tiga_person_id": c.get("id", ""),
            # Company-level details from Tiga enrichment
            "company_phone": c.get("account_phone", ""),
            "company_address": " ".join(filter(None, [
                c.get("account_street", ""),
                c.get("account_city", ""),
                c.get("account_region", ""),
                c.get("account_postal", ""),
                c.get("account_country", ""),
            ])),
            "company_industry": c.get("account_industry", ""),
            "company_domain": c.get("account_domain", ""),
        })

    if not rows:
        console.print(f"  [dim]All contacts already in {output_file}[/dim]")
        return

    write_header = not output_path.exists() or output_path.stat().st_size == 0
    with open(output_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    if skipped:
        console.print(f"  [dim]Skipped {skipped} duplicates[/dim]")
    console.print(f"\n[green][OK] Added {len(rows)} new contacts to {output_file}[/green]")

    table = Table(title="Contacts Found")
    table.add_column("Company", style="cyan")
    table.add_column("Name")
    table.add_column("Title")
    table.add_column("Email", style="green")
    for row in rows:
        table.add_row(
            row["company"],
            f"{row['first_name']} {row['last_name']}",
            row["title"],
            row["email"] or "[dim]not found[/dim]",
        )
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Tiga contact discovery for FSE sponsors")
    parser.add_argument("--min-score", type=int, default=70, help="Min company score to target")
    parser.add_argument("--company", help="Single company name to find contacts for")
    parser.add_argument("--output", default="tiga_contacts.csv", help="Output CSV filename")
    parser.add_argument("--skip-existing", action="store_true", help="Skip companies that already have contacts in pipeline")
    parser.add_argument("--no-agent", action="store_true", help="Skip Find People Agent (faster batch, search only)")
    args = parser.parse_args()

    if not TIGA_API_KEY:
        console.print("[red]TIGA_API_KEY not set in .env[/red]")
        return

    if args.company:
        people = find_people(args.company)
        contacts = []
        for person in people[:3]:
            enriched = enrich_person(person)
            enriched["source_company"] = args.company
            contacts.append(enriched)
        save_contacts_to_pipeline(args.company, contacts)
        save_contacts_csv(contacts, args.output)
    else:
        scored_file = Path("scored_companies.json")
        if not scored_file.exists():
            console.print("[red]scored_companies.json not found. Run score_company.py --batch first.[/red]")
            return

        with open(scored_file) as f:
            scored = json.load(f)

        targets = [c for c in scored if c.get("score", 0) >= args.min_score]

        if args.skip_existing:
            pipeline = _load_pipeline_from_github() or []
            has_contacts = {
                e["company"].lower()
                for e in pipeline
                if e.get("contacts")
            }
            before = len(targets)
            targets = [c for c in targets if c["company"].lower() not in has_contacts]
            console.print(f"[dim]Skipping {before - len(targets)} companies that already have contacts[/dim]")

        console.print(f"\n[bold]Finding contacts for {len(targets)} companies (score ≥ {args.min_score})[/bold]\n")

        contacts = process_companies(targets, use_agent=not args.no_agent)
        save_contacts_csv(contacts, args.output)
        console.print(f"\n[bold green]Done! Run next:[/bold green]")
        console.print(f"python generate_outreach.py --contacts {args.output}")


if __name__ == "__main__":
    main()
