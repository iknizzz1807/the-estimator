/**
 * Canonical feature set mirrored from backend/app/features.py (read-only copy
 * for UI labels, groups and tooltips — backend remains the single source of
 * truth; do not rename or reorder).
 */

export const FEATURE_GROUPS: Record<string, string[]> = {
  integration: [
    "third_party_api",
    "payment_gateway",
    "identity_provider",
    "external_data_sync",
  ],
  data: ["data_migration", "multi_currency", "multi_tenancy"],
  ui: ["realtime_ui", "mobile_app", "offline_mode"],
  security: ["pci_dss", "privacy_compliance", "audit_logging"],
  context: ["legacy_tech_stack", "cross_team_coordination"],
};

export const FEATURES: string[] = Object.values(FEATURE_GROUPS).flat();

export const FEATURE_DEFINITIONS: Record<string, string> = {
  third_party_api:
    "Integrate with an external API/service (CRM, ERP, any vendor system)",
  payment_gateway: "Payment processing integration (cards, wallets)",
  identity_provider: "SSO / OAuth / external identity provider integration",
  external_data_sync: "Continuous data synchronization with external systems",
  data_migration: "Migrate data from legacy systems",
  multi_currency: "Support multiple currencies",
  multi_tenancy:
    "Multi-tenant architecture (shared platform, isolated clients)",
  realtime_ui: "Real-time UI updates (< 100ms)",
  mobile_app: "Native mobile apps (iOS/Android), not just responsive web",
  offline_mode: "Offline-capable functionality",
  pci_dss: "PCI-DSS compliance (card data)",
  privacy_compliance: "GDPR / HIPAA level privacy compliance",
  audit_logging: "Detailed audit trail / audit logging",
  legacy_tech_stack:
    "Work with legacy technology (old languages, on-prem systems)",
  cross_team_coordination: "Coordination across multiple teams / vendors",
};

export const GROUP_LABELS: Record<string, string> = {
  integration: "Integration complexity",
  data: "Data complexity",
  ui: "UI complexity",
  security: "Security & compliance",
  context: "Project context",
};

/** Small presentation labels for tables and chips. */
const SHORT_LABELS: Record<string, string> = {
  third_party_api: "3rd-party API",
  payment_gateway: "Payments",
  identity_provider: "SSO/IdP",
  external_data_sync: "Data sync",
  data_migration: "Migration",
  multi_currency: "Multi-currency",
  multi_tenancy: "Multi-tenant",
  realtime_ui: "Real-time UI",
  mobile_app: "Mobile app",
  offline_mode: "Offline mode",
  pci_dss: "PCI-DSS",
  privacy_compliance: "Privacy (GDPR)",
  audit_logging: "Audit log",
  legacy_tech_stack: "Legacy stack",
  cross_team_coordination: "Cross-team",
};

export function featureLabel(name: string): string {
  if (SHORT_LABELS[name]) return SHORT_LABELS[name];
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function featureDefinition(name: string): string {
  return FEATURE_DEFINITIONS[name] ?? "Canonical project feature";
}
