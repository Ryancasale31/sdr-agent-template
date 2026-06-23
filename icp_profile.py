"""
Builds the Ideal Customer Profile from the attendee list.
Run once to generate icp_summary.json which feeds all other commands.
"""
import pandas as pd
from collections import Counter
import json

ATTENDEE_CSV = r"C:\Users\Ryan.Casale\Downloads\current_registrations (20).csv"

INDUSTRY_MAP = {
    "Medical / Life Sciences": [
        "siemens healthineers", "johnson & johnson", "j&j", "roche", "fresenius",
        "zimmer", "nihon kohden", "carestream", "cytiva", "laerdal", "b braun",
        "linet", "sciex", "bruker", "candela", "karl storz", "steris", "diasorin",
        "novocure", "biotage", "bangslabs", "lgc", "eppendorf",
    ],
    "Industrial / Manufacturing Equipment": [
        "oxford instruments", "abb", "crown equipment", "mitsubishi", "mycronic",
        "dieffenbacher", "smardt", "kps global", "cv technology", "cincinnati",
        "reiser", "henny penny", "middleby", "w&h", "flaktgroup", "omron",
    ],
    "Technology / IT Services": [
        "toshiba", "ricoh", "ciena", "bluecrest", "ptc", "salesforce",
        "siemens energy", "altec", "retail tech", "acuity", "transcat",
    ],
    "Utilities / Infrastructure": [
        "dc water", "m.c. dean", "mc dean", "hydro", "pearce", "comfort systems",
        "tas energy", "p3 services", "cpm pipelines",
    ],
    "Food Service / Vending Equipment": [
        "henny penny", "middleby", "catalina", "coca-cola",
    ],
}

SENIORITY_KEYWORDS = [
    "vp", "vice president", "svp", "senior vice president", "director",
    "head of", "chief", "ceo", "coo", "cro", "president", "general manager",
]


def classify_industry(company: str) -> str:
    co = company.lower()
    for industry, keywords in INDUSTRY_MAP.items():
        if any(k in co for k in keywords):
            return industry
    return "Other"


def is_senior(title: str) -> bool:
    if not isinstance(title, str):
        return False
    t = title.lower()
    return any(k in t for k in SENIORITY_KEYWORDS)


def build_icp(csv_path: str = ATTENDEE_CSV) -> dict:
    df = pd.read_csv(csv_path, encoding="latin1")
    df.columns = df.columns.str.strip()

    buyers = df[df["Price List Type"] == "Primary"].copy()

    buyers["Industry"] = buyers["Account"].fillna("").apply(classify_industry)
    buyers["Is Senior"] = buyers["Job Title"].apply(is_senior)

    title_counts = Counter(buyers["Job Title"].dropna().tolist())
    top_titles = [t for t, _ in title_counts.most_common(20)]

    company_counts = Counter(buyers["Account"].dropna().tolist())
    top_companies = [c for c, _ in company_counts.most_common(20)]

    industry_counts = dict(Counter(buyers["Industry"].tolist()))
    senior_pct = round(buyers["Is Senior"].mean() * 100, 1)
    vendors = df[df["Price List Type"] == "Vendor"]["Account"].dropna().tolist()

    icp = {
        "event": "Field Service East",
        "dates": "August 10-12, 2025",
        "location": "Orlando, FL",
        "total_registrants": len(df),
        "buyer_count": len(buyers),
        "senior_buyer_pct": senior_pct,
        "top_titles": top_titles,
        "top_companies": top_companies,
        "industry_breakdown": industry_counts,
        "existing_sponsors": vendors,
        "buyer_summary": (
            "Primarily VP/Director/SVP-level leaders in field service operations "
            "across medical devices, industrial equipment, technology, and utilities. "
            "Decision-makers responsible for service strategy, workforce, parts, "
            "scheduling, and technology adoption."
        ),
    }
    return icp


if __name__ == "__main__":
    icp = build_icp()
    print(json.dumps(icp, indent=2))
    with open("icp_summary.json", "w") as f:
        json.dump(icp, f, indent=2)
    print("\n[OK] Saved to icp_summary.json")
