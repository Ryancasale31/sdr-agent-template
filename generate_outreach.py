"""
Generate a 3-touch personalized email sequence for a target sponsor company.
Usage:
    python generate_outreach.py "ServiceMax" "John Smith" "VP Marketing" "FSM software for asset-intensive industries"
    python generate_outreach.py --from-scored scored_companies.json --min-score 70
    python generate_outreach.py --contacts tiga_contacts.csv --hubspot
"""
import os
import sys
import json
import csv
import argparse
from pathlib import Path
import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

TIGA_API_KEY = os.getenv("TIGA_API_KEY")
TIGA_BASE_URL = "https://app.tigalabs.com"
TIGA_HEADERS = {
    "X-Tiga-Auth": TIGA_API_KEY,
    "Content-Type": "application/json",
}

ICP_FILE = "icp_summary.json"

OUTREACH_PROMPT = """You are a senior sponsorship sales rep for Field Service East, a premium B2B conference.

EVENT DETAILS:
- Name: Field Service East
- Dates: August 10-12, 2025
- Location: Orlando, FL
- Audience: {buyer_count} registered buyers, ~70% VP/Director/SVP level

TOP BUYER TITLES IN THE ROOM:
{top_titles}

COMPANIES ALREADY ATTENDING:
{top_companies}

EXISTING SPONSORS (social proof):
{existing_sponsors}

---

TARGET SPONSOR:
Company: {company_name}
Contact: {contact_name}, {contact_title}
Company description: {company_description}

---

Write a 3-touch cold email sequence to sell them a sponsorship.

Rules:
- Email 1: Hook with the specific audience insight most relevant to them. Under 150 words. No pitch yet.
- Email 2 (Day 4): Connect their product to the specific buyer titles attending. Reference 1-2 real attendee companies if it strengthens the case. Under 175 words.
- Email 3 (Day 9): Soft close. Reference limited spots and existing sponsors. Under 100 words.
- Tone: Direct, peer-to-peer, no fluff.
- NEVER use: "I hope this email finds you well", "synergy", "leverage", "cutting-edge", "robust", "game-changing"
- Sign off: Ryan Casale, Field Service East

Return ONLY valid JSON:
{{
  "company": "{company_name}",
  "contact_name": "{contact_name}",
  "contact_title": "{contact_title}",
  "emails": [
    {{"touch": 1, "send_day": "Day 1", "subject": "...", "body": "..."}},
    {{"touch": 2, "send_day": "Day 4", "subject": "...", "body": "..."}},
    {{"touch": 3, "send_day": "Day 9", "subject": "...", "body": "..."}}
  ]
}}
"""


def generate_sequence(company_name, contact_name, contact_title, company_description, icp):
    client = anthropic.Anthropic()

    prompt = OUTREACH_PROMPT.format(
        buyer_count=icp["buyer_count"],
        top_titles=", ".join(icp["top_titles"][:12]),
        top_companies=", ".join(icp["top_companies"][:15]),
        existing_sponsors=", ".join(icp["existing_sponsors"]),
        company_name=company_name,
        contact_name=contact_name,
        contact_title=contact_title,
        company_description=company_description,
    )

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def export_hubspot_csv(sequences, output_file="hubspot_import.csv"):
    rows = []
    for seq in sequences:
        name_parts = seq.get("contact_name", "").split(" ", 1)
        first = name_parts[0] if name_parts else ""
        last = name_parts[1] if len(name_parts) > 1 else ""
        emails = seq.get("emails", [{}, {}, {}])
        row = {
            "First Name": first,
            "Last Name": last,
            "Job Title": seq.get("contact_title", ""),
            "Company": seq.get("company", ""),
            "Email": seq.get("email", ""),
            "Email 1 Subject": emails[0].get("subject", "") if len(emails) > 0 else "",
            "Email 1 Body": emails[0].get("body", "") if len(emails) > 0 else "",
            "Email 2 Subject": emails[1].get("subject", "") if len(emails) > 1 else "",
            "Email 2 Body": emails[1].get("body", "") if len(emails) > 1 else "",
            "Email 3 Subject": emails[2].get("subject", "") if len(emails) > 2 else "",
            "Email 3 Body": emails[2].get("body", "") if len(emails) > 2 else "",
        }
        rows.append(row)

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] HubSpot CSV saved to {output_file}")


def sync_to_hubspot_via_tiga(sequences):
    """Push contacts directly into HubSpot via Tiga API. Requires tiga_person_id on each sequence."""
    if not TIGA_API_KEY:
        print("[!] TIGA_API_KEY not set — cannot sync to HubSpot")
        return

    synced, skipped, failed = 0, 0, 0

    for seq in sequences:
        person_id = seq.get("tiga_person_id")
        name = seq.get("contact_name", seq.get("company", "?"))

        if not person_id:
            print(f"  [SKIP] {name} — no tiga_person_id (run via --contacts from tiga_contacts.csv)")
            skipped += 1
            continue

        resp = requests.post(
            f"{TIGA_BASE_URL}/api/v1/hubspot/create-or-update-contact",
            headers=TIGA_HEADERS,
            json={
                "person_id": person_id,
                "find_person_by": {"email": True, "linkedin_url": True},
                "sync_account_association": True,
            },
        )

        if resp.ok:
            data = resp.json()
            action = "created" if data.get("contact_created") else "updated"
            hs_id = data.get("hubspot_contact_id", "")
            print(f"  [OK] {name} → HubSpot contact {action} (id: {hs_id})")
            synced += 1
        else:
            print(f"  [FAIL] {name} → {resp.status_code}: {resp.text[:120]}")
            failed += 1

    print(f"\n[HubSpot Sync] {synced} synced | {skipped} skipped (no ID) | {failed} failed")


def load_icp():
    if not Path(ICP_FILE).exists():
        print(f"[!] {ICP_FILE} not found. Run: python icp_profile.py first.")
        sys.exit(1)
    with open(ICP_FILE) as f:
        return json.load(f)


def print_sequence(seq):
    print(f"\n{'='*60}")
    print(f"COMPANY: {seq['company']}")
    print(f"CONTACT: {seq.get('contact_name','')} | {seq.get('contact_title','')}")
    print(f"{'='*60}")
    for email in seq.get("emails", []):
        print(f"\n--- Touch {email['touch']} ({email['send_day']}) ---")
        print(f"Subject: {email['subject']}")
        print(f"\n{email['body']}")


def main():
    parser = argparse.ArgumentParser(description="Generate sponsor outreach sequences")
    parser.add_argument("company_name", nargs="?")
    parser.add_argument("contact_name", nargs="?")
    parser.add_argument("contact_title", nargs="?")
    parser.add_argument("description", nargs="?")
    parser.add_argument("--from-scored", help="Use scored_companies.json as input")
    parser.add_argument("--min-score", type=int, default=70)
    parser.add_argument("--contacts", help="CSV: company,email,first_name,last_name,title,description")
    parser.add_argument("--hubspot", action="store_true", help="Sync contacts directly to HubSpot via Tiga (requires tiga_person_id)")
    args = parser.parse_args()

    icp = load_icp()

    if args.contacts:
        sequences = []
        with open(args.contacts, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = f"{row.get('first_name','')} {row.get('last_name','')}".strip()
                print(f"  Generating for {row['company']}...")
                seq = generate_sequence(row["company"], name, row.get("title",""), row.get("description",""), icp)
                seq["email"] = row.get("email", "")
                seq["tiga_person_id"] = row.get("tiga_person_id", "")
                sequences.append(seq)
                print_sequence(seq)
        with open("sequences.json", "w") as f:
            json.dump(sequences, f, indent=2)
        if args.hubspot:
            print("\n[HubSpot] Syncing contacts via Tiga...")
            sync_to_hubspot_via_tiga(sequences)
        else:
            export_hubspot_csv(sequences)
            print("\nTip: rerun with --hubspot to push directly to HubSpot instead of CSV")

    elif args.from_scored:
        with open(args.from_scored) as f:
            scored = json.load(f)
        targets = [c for c in scored if c["score"] >= args.min_score]
        print(f"Generating for {len(targets)} companies (score >= {args.min_score})\n")
        sequences = []
        for company in targets:
            print(f"  Generating for {company['company']} (score: {company['score']})...")
            seq = generate_sequence(
                company["company"], "[First Name]", "[Title]",
                company.get("angle", ""), icp
            )
            seq["score"] = company["score"]
            sequences.append(seq)
            print_sequence(seq)
        with open("sequences.json", "w") as f:
            json.dump(sequences, f, indent=2)
        print(f"\n[OK] Saved to sequences.json")

    elif args.company_name:
        seq = generate_sequence(
            args.company_name,
            args.contact_name or "[First Name]",
            args.contact_title or "[Title]",
            args.description or "",
            icp,
        )
        print_sequence(seq)
        with open(f"{args.company_name.replace(' ','_')}_sequence.json", "w") as f:
            json.dump(seq, f, indent=2)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
