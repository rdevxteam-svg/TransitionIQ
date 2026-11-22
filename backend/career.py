# Synthetic employment records for the local demonstration accounts.
CAREER_HISTORY = {
    "vikram": {
        "joined_on": "2021-08-16",
        "entry_role": "Associate Software Engineer",
        "role_changes": [
            {"on": "2022-10-03", "role": "Software Engineer", "summary": "Took ownership of service endpoints and release checks."},
            {"on": "2024-05-06", "role": "Backend Engineer", "summary": "Began leading reliability improvements and backend design reviews."},
        ],
        "projects": [
            {"id": "catalog", "name": "Retail Catalog", "role": "Associate Software Engineer",
             "started_on": "2021-08-16", "ended_on": "2022-09-30",
             "summary": "Built catalog endpoints and automated regression tests for product and inventory updates.",
             "technologies": ["Python", "Django REST Framework", "PostgreSQL", "pytest"]},
            {"id": "fulfillment", "name": "Order Fulfillment", "role": "Software Engineer",
             "started_on": "2022-10-03", "ended_on": "2024-05-03",
             "summary": "Implemented order status APIs and improved observability for asynchronous workflows.",
             "technologies": ["Python", "FastAPI", "Redis", "Docker"]},
            {"id": "merchant", "name": "Merchant Services", "role": "Backend Engineer",
             "started_on": "2024-05-06", "ended_on": "2026-10-30",
             "summary": "Led incident follow-up and improved monitoring and release reliability for merchant APIs.",
             "technologies": ["Python", "FastAPI", "PostgreSQL", "Kubernetes", "Grafana"]},
        ],
    },
    "anika": {
        "joined_on": "2023-07-10",
        "entry_role": "Associate Software Engineer",
        "role_changes": [
            {"on": "2025-01-13", "role": "Software Engineer", "summary": "Started owning customer portal features and their API integrations."},
        ],
        "projects": [
            {"id": "customer-onboarding", "name": "Customer Onboarding", "role": "Associate Software Engineer",
             "started_on": "2023-07-10", "ended_on": "2025-01-10",
             "summary": "Built onboarding forms and integration tests for the registration flow.",
             "technologies": ["React", "TypeScript", "Playwright"]},
            {"id": "service-portal", "name": "Service Portal", "role": "Software Engineer",
             "started_on": "2025-01-13", "ended_on": "2026-09-25",
             "summary": "Implemented self-service account features backed by Python APIs.",
             "technologies": ["Python", "FastAPI", "React", "PostgreSQL"]},
        ],
    },
    "leo": {
        "joined_on": "2024-02-12",
        "entry_role": "Software Engineer",
        "role_changes": [],
        "projects": [
            {"id": "reporting", "name": "Operations Reporting", "role": "Software Engineer",
             "started_on": "2024-02-12", "ended_on": "2026-10-02",
             "summary": "Automated reporting workflows and validated operational data quality.",
             "technologies": ["Python", "SQL", "pandas"]},
        ],
    },
}
