"""Demo scenarios powering the 1-click "Load Sample Data" buttons.

Three realistic customer emails (150-250 words each) that exercise distinct
feature clusters and are tuned for the deterministic offline ``stub``
extractor (docs/DECISIONS.md D2), so judges can demo the pipeline without
typing anything:

* A - fintech wallet: payment_gateway, pci_dss, mobile_app, realtime_ui,
  third_party_api.
* B - healthcare (Vietnamese email): data_migration, privacy_compliance
  (HIPAA), audit_logging, legacy_tech_stack, offline_mode hinted only
  indirectly (low confidence -> shows up as a ranked question).
* C - B2B marketplace: multi_currency, multi_tenancy, identity_provider
  (SSO), external_data_sync, cross_team_coordination.

The ``notes`` field documents the expectations for the UI/demo script.
"""

from __future__ import annotations

_SCENARIO_A_EMAIL = """Dear team,

We are Nordwind Pay, a licensed fintech based in Singapore. We need a payments product for our SME customers — a card-linked wallet — and are looking to start development in November.

Core scope: the product must process payments through Stripe from day one, and we may add a regional acquirer later, so the payment layer must be pluggable. Our compliance team requires PCI-DSS certification before we can go live with card data, and their review covers encryption and key management. Customers must be able to top up, pay merchants, and freeze a lost card instantly.

We also need a mobile app for iOS and Android (both stores, native feel) plus a small web back office. The back office must show transactions in real-time — our ops team wants live updates on a dashboard without refreshing. The system must integrate with HubSpot (our CRM) as a third-party API for customer profiles and support tickets. Notifications go through a vendor SMS gateway we already pay for.

Timeline: our board expects a pilot with 50 merchants within four months. Please include your estimate for discovery, integration and testing. We can share vendor API documentation after NDA, and our CTO is available for a technical call next week.

Best regards,
Elena Voss
Head of Product, Nordwind Pay"""

_SCENARIO_B_EMAIL = """Chào đội ngũ,

Tôi là Trần Minh Anh, phụ trách CNTT của Bệnh viện Đa khoa Hòa Phát (3 cơ sở, khoảng 400 nhân viên). Chúng tôi muốn xây dựng hệ thống quản lý hồ sơ bệnh án điện tử và lịch khám nội bộ, dự kiến khởi động trong quý 4.

Hiện tại dữ liệu bệnh nhân và lịch sử khám nằm trong hệ thống cũ chạy trên máy chủ nội bộ, không xuất báo cáo được. Chúng tôi cần chuyển dữ liệu (khoảng 900.000 bản ghi) sang hệ thống mới, kèm đối chiếu để không mất hồ sơ. Ban giám đốc yêu cầu tuân thủ HIPAA vì có hợp tác với một đối tác y tế tại Mỹ; dữ liệu cá nhân của bệnh nhân không được rời khỏi máy chủ bệnh viện. Hệ thống cũng cần lưu audit trail đầy đủ: mọi thao tác xem hoặc sửa hồ sơ phải tra cứu lại được.

Một điểm tôi chưa rõ cách mô tả: đội điều dưỡng ở cơ sở vùng ven đôi khi phải làm việc mà không có internet ổn định — các bạn tư vấn giúp phương án.

Hệ thống nên chạy được trên hạ tầng hiện có (Windows Server 2012, SQL Server 2008) nếu có thể, vì chưa được duyệt kinh phí thay máy chủ.

Rất mong nhận được báo giá và thời gian triển khai dự kiến.

Trân trọng,
Trần Minh Anh"""

_SCENARIO_C_EMAIL = """Hi team,

I'm Marcus Bell from TradeLane, a B2B marketplace for industrial parts. We are looking for a partner to rebuild our platform over the next two quarters.

The marketplace connects buyers and suppliers in 14 countries, so the new platform must handle multiple currencies: listings in EUR, transactions settling in USD, and automatic exchange rate updates with historical rates for accounting. We currently run one shop per client, but the new architecture must be multi-tenant — every supplier gets an isolated storefront and data separation is enforced at the database level. Enterprise buyers will use SSO (SAML or Azure AD) through their own identity provider, while small buyers can sign in with email and password.

Orders, invoices and stock levels must stay in sync with our suppliers' systems. Some already expose REST APIs, others only a nightly data feed, so we need a flexible synchronization layer with retry logic. Given this complexity, multiple teams must work together: our product team, your delivery team, and at least two supplier IT departments. We also have a partner agency for design to coordinate with.

Budget is flexible for the right team. Kick-off is planned for January and the first release should be live before the summer. Please include discovery, integration testing and a hypercare period in your estimate.

Best,
Marcus Bell
COO, TradeLane"""

SCENARIOS: list[dict[str, str]] = [
    {
        "id": "A",
        "title": "Fintech wallet + PCI (EN)",
        "email_text": _SCENARIO_A_EMAIL,
        "notes": (
            "Fintech: kỳ vọng nhận diện payment_gateway, pci_dss, mobile_app, "
            "realtime_ui, third_party_api (Stripe, PCI-DSS, iOS/Android, "
            "real-time dashboard, HubSpot API)."
        ),
    },
    {
        "id": "B",
        "title": "Bệnh viện: HIPAA + hệ thống cũ (VI)",
        "email_text": _SCENARIO_B_EMAIL,
        "notes": (
            "Y tế (email tiếng Việt): kỳ vọng data_migration, privacy_compliance "
            "(HIPAA), audit_logging, legacy_tech_stack; offline_mode chỉ được "
            "gợi ý gián tiếp nên confidence thấp hoặc thành câu hỏi."
        ),
    },
    {
        "id": "C",
        "title": "B2B marketplace: multi-tenant + SSO (EN)",
        "email_text": _SCENARIO_C_EMAIL,
        "notes": (
            "Marketplace: kỳ vọng multi_currency, multi_tenancy, "
            "identity_provider (SSO/SAML/Azure AD), external_data_sync "
            "(ERP sync/data feed), cross_team_coordination."
        ),
    },
]

_SCENARIOS_BY_ID: dict[str, dict[str, str]] = {scenario["id"]: scenario for scenario in SCENARIOS}


def list_scenarios() -> list[dict[str, str]]:
    """All demo scenarios as plain dicts (id, title, email_text, notes)."""
    return [dict(scenario) for scenario in SCENARIOS]


def get_scenario(scenario_id: str) -> dict[str, str] | None:
    """Look up a scenario by id (case-insensitive); None when unknown."""
    return (
        dict(_SCENARIOS_BY_ID[scenario_id.strip().upper()])
        if scenario_id and scenario_id.strip().upper() in _SCENARIOS_BY_ID
        else None
    )
