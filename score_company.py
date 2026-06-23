"""
Score a company's sponsorship fit for Field Service East.
Usage:
    python score_company.py "ServiceMax" "Field service management software for asset-intensive industries"
    python score_company.py --batch target_companies.txt
"""
import sys
import json
import argparse
from pathlib import Path
import anthropic
from dotenv import load_dotenv

load_dotenv()

ICP_FILE = "icp_summary.json"

SCORE_PROMPT = """You are a sponsorship sales expert for a B2B field service conference.

EVENT: {event} | {dates} | {location}

BUYER PROFILE:
{buyer_summary}

Top buyer titles: {top_titles}

Industries represented: {industry_breakdown}

Existing sponsors (proof of concept): {existing_sponsors}

---

COMPANY TO EVALUATE:
Name: {company_name}
Description: {company_description}

Score this company's fit as a sponsor on a scale of 0-100.

Return ONLY valid JSON in this exact format:
{{
  "company": "{company_name}",
  "score": <0-100>,
  "tier": "<A|B|C>",
  "reason": "<2-3 sentence explanation of fit>",
  "angle": "<the specific value proposition: why their buyers are in the room>",
  "risk": "<one sentence on why they might not convert>"
}}

Scoring guide:
- 80-100 (A): Sells directly to field service directors, clear ROI from this audience
- 60-79 (B): Adjacent fit, strong overlap with 50%+ of attendees
- 40-59 (C): Partial fit, niche overlap
- Below 40: Poor fit, do not pursue
"""


def score_company(company_name: str, company_description: str, icp: dict) -> dict:
    client = anthropic.Anthropic()

    prompt = SCORE_PROMPT.format(
        event=icp["event"],
        dates=icp["dates"],
        location=icp["location"],
        buyer_summary=icp["buyer_summary"],
        top_titles=", ".join(icp["top_titles"][:10]),
        industry_breakdown=json.dumps(icp["industry_breakdown"]),
        existing_sponsors=", ".join(icp["existing_sponsors"]),
        company_name=company_name,
        company_description=company_description,
    )

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def load_icp() -> dict:
    if not Path(ICP_FILE).exists():
        print(f"[!] {ICP_FILE} not found. Run: python icp_profile.py first.")
        sys.exit(1)
    with open(ICP_FILE) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Score sponsor fit for Field Service East")
    parser.add_argument("company_name", nargs="?", help="Company name")
    parser.add_argument("description", nargs="?", help="Company description")
    parser.add_argument("--batch", help="Path to target_companies.txt")
    args = parser.parse_args()

    icp = load_icp()

    if args.batch:
        results = []
        lines = Path(args.batch).read_text().strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            name, desc = line.split("|", 1)
            print(f"  Scoring {name.strip()}...")
            result = score_company(name.strip(), desc.strip(), icp)
            results.append(result)
            tier_icon = {"A": "[A]", "B": "[B]", "C": "[C]"}.get(result["tier"], "[ ]")
            print(f"  {tier_icon} {result['score']:3d}/100  {result['company']}")

        results.sort(key=lambda x: x["score"], reverse=True)
        out_file = "scored_companies.json"
        with open(out_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n[OK] Saved {len(results)} results to {out_file}")

    elif args.company_name and args.description:
        result = score_company(args.company_name, args.description, icp)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
