"""
Builds the Ideal Customer Profile from the attendee list.
Supports multiple events via optional industry_map, seniority_keywords, and event_meta.
"""
import pandas as pd
from collections import Counter
import json

ATTENDEE_CSV = r"C:\Users\Ryan.Casale\Downloads\current_registrations (20).csv"

# FSE defaults
FSE_INDUSTRY_MAP = {
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

FSE_SENIORITY_KEYWORDS = [
    "vp", "vice president", "svp", "senior vice president", "director",
    "head of", "chief", "ceo", "coo", "cro", "president", "general manager",
]

# Backwards compat
INDUSTRY_MAP = FSE_INDUSTRY_MAP
SENIORITY_KEYWORDS = FSE_SENIORITY_KEYWORDS


def classify_industry(company: str, industry_map: dict = None) -> str:
    if industry_map is None:
        industry_map = FSE_INDUSTRY_MAP
    co = company.lower()
    for industry, keywords in industry_map.items():
        if any(k in co for k in keywords):
            return industry
    return "Other"


def is_senior(title: str, seniority_keywords: list = None) -> bool:
    if not isinstance(title, str):
        return False
    if seniority_keywords is None:
        seniority_keywords = FSE_SENIORITY_KEYWORDS
    t = title.lower()
    return any(k in t for k in seniority_keywords)


def build_icp(
    csv_path: str = ATTENDEE_CSV,
    industry_map: dict = None,
    seniority_keywords: list = None,
    event_meta: dict = None,
) -> dict:
    """
    Build ICP from a WBR attendee CSV.

    Args:
        csv_path:           Path to registrations CSV.
        industry_map:       {industry: [keyword,...]} for classification. Defaults to FSE map.
        seniority_keywords: Title keywords that count as senior. Defaults to FSE keywords.
        event_meta:         Dict with name/dates/location/buyer_summary from events_registry.
    """
    _industry_map = industry_map or FSE_INDUSTRY_MAP
    _seniority    = seniority_keywords or FSE_SENIORITY_KEYWORDS

    df = pd.read_csv(csv_path, encoding="latin1")
    df.columns = df.columns.str.strip()

    buyers = df[df["Price List Type"] == "Primary"].copy()

    buyers["Industry"] = buyers["Account"].fillna("").apply(
        lambda co: classify_industry(co, _industry_map)
    )
    buyers["Is Senior"] = buyers["Job Title"].apply(
        lambda t: is_senior(t, _seniority)
    )

    title_counts   = Counter(buyers["Job Title"].dropna().tolist())
    top_titles     = [t for t, _ in title_counts.most_common(20)]
    company_counts = Counter(buyers["Account"].dropna().tolist())
    top_companies  = [c for c, _ in company_counts.most_common(20)]
    industry_counts = dict(Counter(buyers["Industry"].tolist()))
    senior_pct     = round(buyers["Is Senior"].mean() * 100, 1)
    vendors        = df[df["Price List Type"] == "Vendor"]["Account"].dropna().tolist()

    meta = event_meta or {}
    icp = {
        "event":              meta.get("name",     "Field Service East"),
        "dates":              meta.get("dates",    "August 10-12, 2026"),
        "location":           meta.get("location", "Orlando, FL"),
        "total_registrants":  len(df),
        "buyer_count":        len(buyers),
        "senior_buyer_pct":   senior_pct,
        "top_titles":         top_titles,
        "top_companies":      top_companies,
        "industry_breakdown": industry_counts,
        "existing_sponsors":  vendors,
        "buyer_summary": meta.get(
            "buyer_summary",
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
