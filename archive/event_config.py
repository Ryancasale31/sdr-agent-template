"""
EVENT CONFIGURATION
Edit this file to set up the SDR agent for any event.
This is the only file you need to change for a new event.
"""

EVENT = {
    # ── Basic event info ──────────────────────────────────────────────────
    "name": "Your Event Name",
    "short_name": "YEN",                          # Used in app title
    "dates": "Month DD-DD, YYYY",
    "location": "City, State",
    "focus": "Brief description of event topic",  # e.g. "Field service operations, digital transformation"

    # ── Your attendee CSV ─────────────────────────────────────────────────
    "attendee_csv": r"C:\path\to\your\attendees.csv",

    # ── CSV column names (adjust to match your file) ──────────────────────
    "csv_columns": {
        "company":           "Account",
        "job_title":         "Job Title",
        "registration_type": "Registration Type",
        "price_list_type":   "Price List Type",   # "Primary" = buyer, "Vendor" = sponsor
    },

    # ── Who counts as a buyer (not a vendor) ─────────────────────────────
    "buyer_filter": {
        "column": "Price List Type",
        "value":  "Primary",
    },

    # ── Who counts as an existing sponsor ────────────────────────────────
    "sponsor_filter": {
        "column": "Price List Type",
        "value":  "Vendor",
    },

    # ── Industry classification keywords ─────────────────────────────────
    # Add/edit industries and keywords that match your audience
    "industry_map": {
        "Medical / Life Sciences": [
            "siemens healthineers", "johnson & johnson", "roche", "fresenius",
            "zimmer", "stryker", "medtronic", "abbott", "becton dickinson",
        ],
        "Industrial / Manufacturing": [
            "abb", "siemens", "honeywell", "emerson", "ge", "schneider",
            "rockwell", "parker hannifin",
        ],
        "Technology / IT Services": [
            "ibm", "microsoft", "salesforce", "sap", "oracle", "dell",
            "hp", "cisco", "accenture",
        ],
        "Utilities / Infrastructure": [
            "utility", "water", "electric", "gas", "energy", "power",
            "infrastructure", "pipeline",
        ],
    },

    # ── Seniority keywords for buyer scoring ─────────────────────────────
    "seniority_keywords": [
        "vp", "vice president", "svp", "senior vice president",
        "director", "head of", "chief", "ceo", "coo", "cro",
        "president", "general manager",
    ],

    # ── Your name (signs off on all outreach emails) ──────────────────────
    "sender_name": "Your Name",
    "sender_title": "Your Title",
    "event_brand": "Your Event Name",
}
