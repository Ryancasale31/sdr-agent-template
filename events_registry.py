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
        "location":        "Grand Hyatt Atlanta, Buckhead, GA",
        "focus": (
            "B2B eCommerce, digital commerce, and digital transformation for manufacturers and distributors. "
            "Senior CXO-level executives from industrial, building materials, electrical, chemical, food, and "
            "wholesale distribution companies navigating platform modernization, AI-driven commerce, ERP integration, "
            "PIM/data hygiene, omnichannel strategy, and change management. "
            "Core sponsor categories: PIM/data syndication, B2B digital commerce platforms, conversational/agentic AI, "
            "website personalization, ERP, OMS, payment platforms, and commerce experience management."
        ),
        "search_keywords": (
            "B2B eCommerce platform PIM product information management digital commerce "
            "manufacturer distributor ERP integration agentic commerce AI personalization "
            "OMS order management omnichannel marketing automation CDP data syndication "
            "B2B payments wholesale distribution digital transformation"
        ),
        "sender_name":     "Ryan Casale",
        "sender_title":    "Sponsorship Sales",
        "event_brand":     "B2B Online Atlanta",
        "website":         "https://b2bmarketingeast.wbresearch.com/",

        # Sponsor fit scoring context
        "core_sponsor_categories": [
            "Product Information Management (PIM) and data syndication",
            "B2B digital commerce platforms",
            "Conversational and agentic commerce / AI",
            "Website personalization engines",
            "Enterprise Resource Planning (ERP)",
        ],
        "secondary_sponsor_categories": [
            "Payment platforms",
            "Order Management Systems (OMS)",
            "Commerce Experience Management (CEM)",
            "Smart discovery and recommendations (AI/LLM-powered)",
            "Amazon marketplace intelligence",
        ],
        "out_of_scope_categories": [
            "Point of Sale (POS) software",
            "Compliance, risk, and protection software",
        ],

        # ICP industry classification
        "industry_map": {
            "Industrial Distribution": [
                "motion industries", "winsupply", "integrated power services",
                "city electric supply", "kloeckner", "cleveland steel",
                "grainger", "msc industrial", "fastenal",
                "bulbs.com", "tessco", "snap-on", "sunbelt rentals",
            ],
            "Wholesale / Specialty Distribution": [
                "specialty building products", "imperial brady", "pcna",
                "j.j. keller", "bradley corp", "watts water", "bausch",
                "trane supply",
            ],
            "Manufacturing": [
                "samsung", "lg ", "kimberly-clark", "schneider electric",
                "evonik", "lippert", "douglas dynamics", "haimer",
                "ule group", "sciens building", "boeing", "ge healthcare",
                "standard textile", "trends international", "ansell",
                "ppg", "nuvo",
            ],
            "Consumer Goods / Food & Beverage": [
                "coca-cola", "pepsico", "pepsi", "philip morris",
                "food manufacturing", "beverage",
            ],
            "Technology / Software": [
                "microsoft", "ibm", "intel", "dell", "oracle",
                "salesforce", "sap", "adobe",
            ],
            "Energy / Chemicals": [
                "exxon", "chevron", "valero", "marathon", "phillips",
                "dow", "chemical",
            ],
        },
        "seniority_keywords": [
            "vp", "vice president", "svp", "senior vice president",
            "director", "head of", "chief", "ceo", "coo", "cro", "cto",
            "cdo", "chief digital", "president", "general manager", "evp",
            "executive vice president", "senior manager",
        ],
    },
    "field-service-medical": {
        "name":            "Field Service Medical",
        "short_name":      "FSM",
        "dates":           "TBC",
        "location":        "TBC",
        "focus": (
            "Field service and aftermarket support for medical device, diagnostic and "
            "laboratory equipment manufacturers. Service, support and technical operations "
            "leaders responsible for equipment uptime in hospitals and clinics, field "
            "engineer productivity, depot and repair operations, service contract revenue, "
            "and service documentation that has to survive an FDA or ISO 13485 audit. "
            "Core sponsor categories: field service management platforms, service parts "
            "planning, AI-assisted resolution, remote/AR support, technician training and "
            "certification, connected-device monitoring, and regulated service reporting."
        ),
        "search_keywords": (
            "medical device field service management software service parts planning "
            "remote assistance AR technician clinical engineering biomedical equipment "
            "hospital equipment uptime depot repair service contract FDA 21 CFR part 820 "
            "ISO 13485 service documentation connected medical device remote monitoring"
        ),
        "sender_name":     "Ryan Casale",
        "sender_title":    "Sponsorship Sales",
        "event_brand":     "Field Service Medical",
        "website":         "",

        "core_sponsor_categories": [
            "Field service management (FSM) platforms",
            "Service parts planning and inventory optimisation",
            "AI-assisted service resolution and knowledge",
            "Remote assistance / AR for field and clinical engineers",
            "Technician training, certification and competency tracking",
        ],
        "secondary_sponsor_categories": [
            "Connected device monitoring and predictive maintenance",
            "Service contract pricing and revenue management",
            "Mobile forms and regulated service documentation",
            "Scheduling and dispatch optimisation",
            "Service analytics and decision intelligence",
        ],
        "out_of_scope_categories": [
            "Drone and aerial inspection",
            "Utilities and energy field service",
            "Telecom network service management",
            "Fleet telematics",
            "Gig / contractor networks",
        ],
    },
    # Add new events below
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
