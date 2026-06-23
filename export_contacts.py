"""
Export all contacts from the live pipeline (GitHub data branch) to a CSV.

Usage:
    python export_contacts.py
    python export_contacts.py --output my_contacts.csv
    python export_contacts.py --min-score 70
"""
import os
import json
import base64
import csv
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO",   "Ryancasale31/sdr-agent-template")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "data")
PIPELINE_FILE = Path(__file__).parent / "pipeline.json"


def fetch_pipeline_from_github() -> list | None:
    try:
        import requests
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/pipeline.json",
            params={"ref": GITHUB_BRANCH},
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            timeout=20,
        )
        if resp.ok:
            return json.loads(base64.b64decode(resp.json()["content"]).decode("utf-8"))
    except Exception as e:
        print(f"  GitHub fetch failed: {e}")
    return None


def load_pipeline() -> list:
    if GITHUB_TOKEN:
        print("Fetching pipeline from GitHub...")
        data = fetch_pipeline_from_github()
        if data:
            print(f"  Loaded {len(data)} companies from GitHub ({GITHUB_REPO} @ {GITHUB_BRANCH})")
            return data
        print("  Falling back to local pipeline.json")
    else:
        print("No GITHUB_TOKEN — reading local pipeline.json")

    if PIPELINE_FILE.exists():
        with open(PIPELINE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  Loaded {len(data)} companies from local file")
        return data

    print("ERROR: No pipeline data found.")
    return []


def get_contacts(company: dict) -> list:
    """Return contacts, handling both array and legacy single-contact fields."""
    contacts = company.get("contacts") or []
    if not contacts:
        # Legacy fields: contact_name / contact_email
        if company.get("contact_name") or company.get("contact_email"):
            contacts = [{
                "name":  company.get("contact_name", ""),
                "title": company.get("contact_title", ""),
                "email": company.get("contact_email", ""),
                "phone": company.get("contact_phone", "") or company.get("account_phone", ""),
                "linkedin": company.get("contact_linkedin", ""),
                "notes": "",
                "source": "legacy",
            }]
    return contacts


def export_contacts(pipeline: list, output: str, min_score: int) -> int:
    rows = []
    for company in pipeline:
        score = company.get("score", 0)
        if score < min_score:
            continue
        contacts = get_contacts(company)
        for contact in contacts:
            rows.append({
                "company":  company.get("company", ""),
                "tier":     company.get("tier", ""),
                "score":    score,
                "status":   company.get("status", ""),
                "category": company.get("category", ""),
                "name":     contact.get("name", ""),
                "title":    contact.get("title", ""),
                "email":    contact.get("email", ""),
                "phone":    contact.get("phone", ""),
                "linkedin": contact.get("linkedin", ""),
                "notes":    contact.get("notes", ""),
                "source":   contact.get("source", ""),
            })

    if not rows:
        print("\nNo contacts found in pipeline.")
        return 0

    fieldnames = list(rows[0].keys())
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Export all pipeline contacts to CSV")
    parser.add_argument("--output",    default="contacts_export.csv", help="Output CSV filename")
    parser.add_argument("--min-score", type=int, default=0,           help="Only include companies scoring >= this")
    args = parser.parse_args()

    pipeline = load_pipeline()
    if not pipeline:
        return

    total_with_contacts = sum(1 for c in pipeline if get_contacts(c))
    print(f"  Companies with contacts: {total_with_contacts} / {len(pipeline)}")

    count = export_contacts(pipeline, args.output, args.min_score)
    if count:
        print(f"\nExported {count} contacts to {args.output}")
    else:
        print("\nNo contacts to export yet.")
        print("Run tiga_contacts.py to discover contacts, or add them manually in the Pipeline tab.")


if __name__ == "__main__":
    main()
