"""Value-of-Information question ranking (spec §4.3, checklist Phase 2).

For each feature the extraction could not resolve (value = None), we estimate
the project twice — once assuming the feature is present, once assuming it is
absent — and rank the gap. Other unresolved features are held at 0 (absent) in
both scenarios; that is a documented simplification: it measures the marginal
impact of asking one question at a time, not the joint impact of all unknowns.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.features import FEATURES
from app.services.estimation import EstimatorModel, cold_start_estimate, point_estimate

#: Specific, answerable questions per feature (spec §4.3 rule 4). VI + EN.
QUESTION_TEMPLATES: dict[str, dict[str, str]] = {
    "third_party_api": {
        "vi": "Dự án cần tích hợp với hệ thống/API bên ngoài nào không (ERP, CRM, đối tác…)? Nếu có, khoảng bao nhiêu hệ thống?",
        "en": "Does the project need to integrate with any external systems/APIs (ERP, CRM, partners…)? If so, roughly how many?",
    },
    "payment_gateway": {
        "vi": "Dự án có xử lý thanh toán không? Qua cổng nào (Stripe, VNPay, MoMo…) và phương thức nào (thẻ, ví, chuyển khoản)?",
        "en": "Will the product process payments? Through which gateway (Stripe, VNPay, MoMo…) and which methods (cards, wallets, transfers)?",
    },
    "identity_provider": {
        "vi": "Người dùng đăng nhập bằng tài khoản nội bộ hay qua SSO/OAuth (Google, Azure AD, IdP của khách)? Cần hỗ trợ nhiều nhà cung cấp không?",
        "en": "Will users sign in with local accounts or via SSO/OAuth (Google, Azure AD, the customer's IdP)? Is more than one provider needed?",
    },
    "external_data_sync": {
        "vi": "Dữ liệu cần đồng bộ hai chiều với hệ thống ngoài nào và tần suất bao lâu (thời gian thực, mỗi giờ, hàng ngày)?",
        "en": "Which external systems need two-way data sync, and how often (real-time, hourly, daily)?",
    },
    "data_migration": {
        "vi": "Có cần chuyển dữ liệu từ hệ thống cũ không? Khoảng bao nhiêu bản ghi và dữ liệu hiện đang ở định dạng nào?",
        "en": "Is data migration from existing systems required? Roughly how many records, and in what format does the current data live?",
    },
    "multi_currency": {
        "vi": "Ứng dụng cần hỗ trợ nhiều loại tiền tệ không? Có cần quy đổi tỷ giá và lưu lịch sử tỷ giá không?",
        "en": "Does the app need to support multiple currencies, including exchange-rate conversion and historical rates?",
    },
    "multi_tenancy": {
        "vi": "Hệ thống phục vụ một khách hàng hay nhiều khách hàng trên cùng nền tảng (multi-tenant)? Mức tách biệt dữ liệu yêu cầu là gì?",
        "en": "Is this a single-customer deployment or one platform shared by multiple tenants? What data-isolation level is required?",
    },
    "realtime_ui": {
        "vi": "Giao diện có cần cập nhật tức thời (dưới 100ms, kiểu dashboard trực tiếp) không? Những màn hình nào?",
        "en": "Does the UI need sub-100ms real-time updates (live dashboard)? Which screens?",
    },
    "mobile_app": {
        "vi": "Có cần ứng dụng mobile native (iOS + Android) không, hay chỉ cần web responsive/PWA?",
        "en": "Are native mobile apps (iOS + Android) required, or is a responsive web app / PWA enough?",
    },
    "offline_mode": {
        "vi": "Người dùng có cần làm việc khi mất mạng không? Dữ liệu offline sẽ đồng bộ lại thế nào khi có mạng?",
        "en": "Will users need to work without internet access? How should offline data sync once connectivity returns?",
    },
    "pci_dss": {
        "vi": "Dự án có lưu/xử lý dữ liệu thẻ thanh toán không? Đã có yêu cầu chứng nhận PCI-DSS chưa?",
        "en": "Will the system store or process cardholder data? Is PCI-DSS certification explicitly required?",
    },
    "privacy_compliance": {
        "vi": "Khách hàng có yêu cầu tuân thủ GDPR/HIPAA hay quy định bảo vệ dữ liệu cá nhân nào không?",
        "en": "Does the client require GDPR/HIPAA or any personal-data privacy regulation compliance?",
    },
    "audit_logging": {
        "vi": "Có yêu cầu lưu audit trail chi tiết không? Cần ghi lại thao tác nào và lưu log bao lâu?",
        "en": "Is a detailed audit trail required? Which actions must be logged, and for how long should logs be retained?",
    },
    "legacy_tech_stack": {
        "vi": "Phần nào phải chạy trên công nghệ cũ (COBOL, on-prem, hệ thống hiện tại)? Có tài liệu kỹ thuật sẵn không?",
        "en": "Which parts must run on legacy technology (COBOL, on-prem, existing systems)? Is technical documentation available?",
    },
    "cross_team_coordination": {
        "vi": "Cần phối hợp với bao nhiêu team/bên liên quan (nội bộ, khách hàng, vendor khác)? Ai review và nghiệm thu?",
        "en": "How many teams/stakeholders must be coordinated (internal, client, other vendors)? Who reviews and signs off?",
    },
}

assert set(QUESTION_TEMPLATES) == set(FEATURES), "Question templates must cover all 15 features"

_FEATURE_INDEX = {name: i for i, name in enumerate(FEATURES)}


def _resolve_findings(findings: Any) -> tuple[dict[str, int], list[str]]:
    """Split findings into resolved {name: 0|1} and unknown [names] (FEATURES order)."""
    items = getattr(findings, "findings", findings)  # accept ExtractionResult too
    resolved: dict[str, int] = {}
    unknown: set[str] = set()
    for item in items or []:
        name = item["name"] if isinstance(item, Mapping) else item.name
        value = item.get("value") if isinstance(item, Mapping) else item.value
        if name not in _FEATURE_INDEX:
            continue
        if value is None:
            unknown.add(name)
        else:
            resolved[name] = int(bool(value))
    ordered_unknown = sorted(unknown, key=_FEATURE_INDEX.__getitem__)
    return resolved, ordered_unknown


def rank_questions(
    model_or_none: EstimatorModel | None,
    findings: Sequence[Any],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Rank the unresolved features by impact on P50 and attach VI/EN questions.

    Falls back to ``cold_start_estimate`` when no trained model is available.
    """
    resolved, unknown = _resolve_findings(findings)

    rows: list[dict[str, Any]] = []
    for name in unknown:
        base = dict(resolved)  # other unknowns held at 0, documented above
        scenario_with = {**base, name: 1}
        scenario_without = {**base, name: 0}
        if model_or_none is None:
            p50_with = cold_start_estimate(scenario_with)["p50"]
            p50_without = cold_start_estimate(scenario_without)["p50"]
        else:
            p50_with = point_estimate(model_or_none, scenario_with)
            p50_without = point_estimate(model_or_none, scenario_without)
        template = QUESTION_TEMPLATES[name]
        rows.append(
            {
                "feature": name,
                "impact_days": round(abs(p50_with - p50_without), 1),
                "p50_with": p50_with,
                "p50_without": p50_without,
                "question_vi": template["vi"],
                "question_en": template["en"],
            }
        )

    rows.sort(key=lambda row: (-row["impact_days"], _FEATURE_INDEX[row["feature"]]))
    return rows[: max(0, top_k)]
