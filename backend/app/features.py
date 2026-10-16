"""Canonical feature set for The Estimator — single source of truth.

15 binary features grouped by complexity type (docs/SPEC.md §5.2).
CSV columns, DB rows, LLM prompts and the UI all depend on these names:
do not rename or reorder.
"""

from __future__ import annotations

FEATURE_GROUPS: dict[str, list[str]] = {
    "integration": [
        "third_party_api",
        "payment_gateway",
        "identity_provider",
        "external_data_sync",
    ],
    "data": [
        "data_migration",
        "multi_currency",
        "multi_tenancy",
    ],
    "ui": [
        "realtime_ui",
        "mobile_app",
        "offline_mode",
    ],
    "security": [
        "pci_dss",
        "privacy_compliance",
        "audit_logging",
    ],
    "context": [
        "legacy_tech_stack",
        "cross_team_coordination",
    ],
}

FEATURES: list[str] = [f for group in FEATURE_GROUPS.values() for f in group]

FEATURE_DEFINITIONS: dict[str, str] = {
    "third_party_api": "Integrate with an external API/service (CRM, ERP, any vendor system)",
    "payment_gateway": "Payment processing integration (cards, wallets)",
    "identity_provider": "SSO / OAuth / external identity provider integration",
    "external_data_sync": "Continuous data synchronization with external systems",
    "data_migration": "Migrate data from legacy systems",
    "multi_currency": "Support multiple currencies",
    "multi_tenancy": "Multi-tenant architecture (shared platform, isolated clients)",
    "realtime_ui": "Real-time UI updates (< 100ms)",
    "mobile_app": "Native mobile apps (iOS/Android), not just responsive web",
    "offline_mode": "Offline-capable functionality",
    "pci_dss": "PCI-DSS compliance (card data)",
    "privacy_compliance": "GDPR / HIPAA level privacy compliance",
    "audit_logging": "Detailed audit trail / audit logging",
    "legacy_tech_stack": "Work with legacy technology (old languages, on-prem systems)",
    "cross_team_coordination": "Coordination across multiple teams / vendors",
}

assert len(FEATURES) == 15, "Feature set must contain exactly 15 features"
assert len(set(FEATURES)) == 15, "Duplicate feature names"
assert all(f in FEATURE_DEFINITIONS for f in FEATURES)

FEATURE_COLUMN_PREFIX = "feat_"


def csv_columns() -> list[str]:
    """Canonical CSV column names for the feature vector."""
    return [f"{FEATURE_COLUMN_PREFIX}{name}" for name in FEATURES]
