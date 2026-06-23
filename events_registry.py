"""
EVENTS REGISTRY
Add a new event here and set its password in Streamlit Secrets under [event_passwords].

Each event key becomes the event_id (used for data namespacing in storage).
"""

EVENTS = {
    "field-service-east": {
        "name":            "Field Service East",
        "short_name":      "FSE",
        "dates":           "Aug 10-12, 2026",
        "location":        "Orlando, FL",
        "focus":           "field service management, IoT, digital transformation",
        "search_keywords": "field service software products customers target market",
        "sender_name":     "Ryan Casale",
        "sender_title":    "Sponsorship Sales",
        "event_brand":     "Field Service East",
        "website":         "https://www.wbresearch.com/fieldserviceus/",
    },
    "b2b-online-atlanta": {
        "name":            "B2B Online Atlanta",
        "short_name":      "B2B",
        "dates":           "Nov 9-11, 2026",
        "location":        "Atlanta, GA",
        "focus":           "B2B eCommerce, digital marketing, manufacturer and distributor digital transformation",
        "search_keywords": "B2B eCommerce platform digital commerce manufacturer distributor marketing automation",
        "sender_name":     "Ryan Casale",
        "sender_title":    "Sponsorship Sales",
        "event_brand":     "B2B Online Atlanta",
        "website":         "https://b2bmarketingeast.wbresearch.com/",
    },
    # ── Add new events below ──────────────────────────────────────────────────
    # "new-event-slug": {
    #     "name":            "My New Event",
    #     "short_name":      "MNE",
    #     "dates":           "Oct 14-16, 2026",
    #     "location":        "Chicago, IL",
    #     "focus":           "brief topic description",
    #     "search_keywords": "keywords for web research",
    #     "sender_name":     "Colleague Name",
    #     "sender_title":    "Sponsorship Sales",
    #     "event_brand":     "My New Event",
    #     "website":         "https://...",
    # },
}
