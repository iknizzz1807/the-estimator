"""Deterministic email-template engine for the synthetic history generator.

Assembles short client emails (120-350 words) from graded sentence pools:

* greeting + client/project context with concrete numbers (users, budget, timeline),
* one sentence per *mentioned* present feature (several phrasings/synonyms per
  feature so a keyword-based extractor can catch them),
* explicit negation sentences for a small share of *absent* features,
* optional fluff and a sign-off.

Language mix: ~70% English, ~15% Vietnamese, ~15% mixed VI-EN. Vietnamese and
mixed sentences keep the English keyword next to the Vietnamese wording
("cổng thanh toán (payment gateway)") so extraction works in both languages.

Sentence pools are deliberately kept free of *other* features' keywords: a
sentence about data migration never says "legacy" and an offline sentence never
says "sync", so a naive keyword extractor does not produce cross-feature false
positives from the generated corpus.

All randomness flows through the caller-provided ``random.Random`` instance, so
output is fully deterministic for a given seed.
"""

from __future__ import annotations

import random
from typing import Sequence

MIN_WORDS = 120  # emails are padded with fluff up to this length
_MAX_WORDS = 350  # documented upper bound (core sentence lengths keep us far below)

# --- Client / project context pools ------------------------------------------

_CLIENTS = [
    "Northwind Retail",
    "Acme Logistics",
    "Orbit Telecom",
    "MedCore Health",
    "GreenFarm Co",
    "Citywide Insurance",
    "Lotus Travel",
    "Titan Manufacturing",
    "BlueRiver Energy",
    "NovaMart",
    "Hanoi Fintech JSC",
    "Pacific Freight",
    "Saigon Digital Bank",
    "Edulab Group",
    "Sunrise Hotels",
]

# Feature-neutral descriptors: they must not contain any feature keyword.
_PROJECTS_EN = [
    "a customer self-service portal",
    "an internal operations dashboard",
    "a booking management platform",
    "a reporting and analytics tool",
    "an order management system",
    "a partner onboarding workflow",
    "a field service tracking tool",
    "a supplier collaboration hub",
]

_PROJECTS_VI = [
    "cổng tự phục vụ cho khách hàng",
    "dashboard vận hành nội bộ",
    "hệ thống quản lý đặt chỗ",
    "công cụ báo cáo và phân tích",
    "hệ thống quản lý đơn hàng",
    "quy trình onboarding đối tác",
    "công cụ theo dõi dịch vụ hiện trường",
]

_CONTACTS_EN = [
    ("Sarah Mitchell", "Head of Operations"),
    ("David Chen", "CTO"),
    ("Emma Rodriguez", "Product Manager"),
    ("Michael Turner", "IT Director"),
    ("Priya Nair", "Program Manager"),
    ("James Okafor", "COO"),
    ("Laura Kim", "Head of Engineering"),
    ("Tom Becker", "Procurement Lead"),
]

_CONTACTS_VI = [
    ("Nguyễn Minh Anh", "Giám đốc vận hành"),
    ("Trần Quốc Bảo", "Trưởng phòng IT"),
    ("Lê Thu Hà", "Quản lý sản phẩm"),
    ("Phạm Đức Huy", "CTO"),
    ("Võ Thanh Mai", "Giám đốc chương trình"),
    ("Đặng Văn Nam", "Trưởng phòng mua sắm"),
]

_USER_COUNTS = [120, 450, 800, 1500, 2500, 5000, 12_000, 25_000, 40_000, 80_000]
_BUDGETS_USD = [15_000, 25_000, 40_000, 60_000, 90_000, 120_000, 180_000, 250_000]
_TIMELINES_MONTHS = [3, 4, 5, 6, 9, 12]

_GREETINGS = {
    "en": ["Hi team,", "Hello,", "Dear team,", "Greetings,"],
    "vi": ["Xin chào đội ngũ,", "Kính gửi anh/chị,", "Chào team,"],
}

_CONTEXT = {
    "en": [
        "I'm {contact} from {client}. We're planning {project} and would like your "
        "team to build it. We expect around {users} active users in the first year, "
        "and the approved budget is about {budget} USD. Our target launch is roughly "
        "{months} months from kick-off.",
        "We are {client}, currently evaluating partners for {project}. The solution "
        "should serve about {users} users initially, the budget is around {budget} USD, "
        "and we would like delivery within {months} months.",
        "{client} is looking for a vendor to deliver {project}. Roughly {users} people "
        "will use it daily, the budget is about {budget} USD, and the planned timeline "
        "is {months} months.",
        "My name is {contact} and I represent {client}. The project is {project}, "
        "expected to onboard about {users} users in year one. Budget: approximately "
        "{budget} USD. Timing: {months} months.",
    ],
    "vi": [
        "Tôi là {contact} từ {client}. Chúng tôi đang chuẩn bị {project} và muốn nhận "
        "báo giá từ đội của bạn. Dự kiến khoảng {users} người dùng trong năm đầu, "
        "ngân sách khoảng {budget} USD, thời gian mong muốn khoảng {months} tháng.",
        "{client} đang tìm đối tác triển khai {project}. Quy mô ban đầu khoảng {users} "
        "người dùng, ngân sách dự kiến {budget} USD, deadline khoảng {months} tháng.",
        "Tôi là {contact}, đại diện {client}. Dự án là {project}, dự kiến phục vụ khoảng "
        "{users} người dùng, ngân sách {budget} USD, hoàn thành trong {months} tháng.",
    ],
}

# --- Feature sentences (keyword-rich, no cross-feature keywords) -------------

FEATURE_SENTENCES: dict[str, dict[str, list[str]]] = {
    "en": {
        "third_party_api": [
            "The platform must integrate with our existing CRM through its REST API, "
            "and the integration should handle rate limits gracefully.",
            "We need an integration with a third-party ERP system using the vendor's "
            "API and webhooks.",
            "There is a third-party API integration with our logistics provider that "
            "the new system has to consume.",
        ],
        "payment_gateway": [
            "Customers will pay online, so we need a payment gateway that supports "
            "cards and e-wallets.",
            "The checkout flow must process payments through an external gateway and "
            "handle refunds and chargebacks.",
            "Please include support for one-time payments and monthly subscriptions "
            "through a payment provider.",
        ],
        "identity_provider": [
            "Users should log in with their existing company accounts via SSO/OAuth, "
            "and we need role mapping from the identity provider.",
            "The system must connect to our corporate identity provider using "
            "SAML 2.0 and OAuth 2.0.",
            "Single sign-on (SSO) against our internal IdP is a hard requirement.",
        ],
        "external_data_sync": [
            "Data must stay in sync with our warehouse system, with automatic "
            "synchronization every 15 minutes and conflict handling.",
            "We need continuous two-way data synchronization between the new app and "
            "our back-office systems.",
            "The service should pull updates from partner systems regularly and keep "
            "records in sync whenever they differ.",
        ],
        "data_migration": [
            "We have around 12 years of records in the previous system, so data "
            "migration with validation is a significant workstream.",
            "A migration of existing customer and order data from the previous "
            "database must be included in scope.",
            "Please plan for migrating roughly 4 million rows from our current "
            "spreadsheets and previous database.",
        ],
        "multi_currency": [
            "We operate in several markets, so multi-currency support with exchange "
            "rates and rounding rules is required.",
            "Prices and invoices must support multiple currencies, with daily FX rates.",
            "The product should handle multi-currency billing for customers in Asia "
            "and Europe.",
        ],
        "multi_tenancy": [
            "The system will be multi-tenant, serving several client organizations "
            "from a single deployment with strict data isolation.",
            "We need a multi-tenant architecture where each tenant workspace is "
            "isolated but shares the same codebase.",
            "Multi-tenancy with per-tenant configuration and role-based access is "
            "part of the requirements.",
        ],
        "realtime_ui": [
            "Operators need a real-time dashboard where status updates appear "
            "instantly, ideally under 100ms, using WebSockets.",
            "The UI must update in real time as events arrive, without manual refresh.",
            "Live notifications and real-time charts are important for the control "
            "room screen.",
        ],
        "mobile_app": [
            "Field staff need native mobile apps for both iOS and Android, not just a "
            "responsive web page.",
            "We want a cross-platform mobile app that works on iPhones and Android "
            "devices and ships through the app stores.",
            "A native mobile application for iOS and Android is required for field "
            "technicians.",
        ],
        "offline_mode": [
            "Field technicians often work in basements and rural areas, so offline "
            "mode with local storage is essential.",
            "The application should remain usable without internet access, buffering "
            "changes on the device until connectivity returns.",
            "Offline capability is required for the inspection workflow when devices "
            "lose their connection.",
        ],
        "pci_dss": [
            "Because we handle card data, PCI-DSS compliance is mandatory, including "
            "encryption and tokenization.",
            "The solution must be ready for PCI-DSS certification for handling "
            "cardholder data.",
            "We need to comply with PCI-DSS for storing and processing cardholder "
            "data.",
        ],
        "privacy_compliance": [
            "We process personal data of EU residents, so GDPR compliance, consent "
            "tracking and the right to deletion are required.",
            "The product must meet GDPR/HIPAA privacy requirements for medical "
            "records.",
            "Privacy compliance with GDPR is mandatory because of our European "
            "customers.",
        ],
        "audit_logging": [
            "Regulators require a full audit trail: every change must be logged with "
            "who, when and what.",
            "We need detailed audit logging across the platform with a searchable "
            "history.",
            "An immutable audit log is required for internal control purposes.",
        ],
        "legacy_tech_stack": [
            "The core platform runs on a COBOL mainframe and an on-prem Oracle "
            "database, so experience with legacy technology is important.",
            "Part of the backend works with a legacy technology stack that has very "
            "little documentation.",
            "A significant part of the work involves an on-premise legacy platform we "
            "cannot replace yet.",
        ],
        "cross_team_coordination": [
            "Delivery will require cross-team coordination with our internal IT "
            "department and a second supplier managing the network.",
            "The project involves several stakeholder teams, so regular coordination "
            "across teams is expected.",
            "We will run this with your team plus our data team and the network "
            "provider, so coordination overhead is real.",
        ],
    },
    "vi": {
        "third_party_api": [
            "Hệ thống cần tích hợp API (third-party API) với CRM hiện tại của chúng "
            "tôi, bao gồm REST API và webhooks.",
            "Bên tôi cần kết nối (integration) với hệ thống ERP của đối tác qua API "
            "của họ.",
        ],
        "payment_gateway": [
            "Khách hàng thanh toán online nên cần cổng thanh toán (payment gateway) "
            "hỗ trợ thẻ và ví điện tử.",
            "Cần hỗ trợ payment: thanh toán một lần và subscription hằng tháng qua "
            "cổng thanh toán bên thứ ba.",
        ],
        "identity_provider": [
            "Người dùng đăng nhập bằng tài khoản công ty qua SSO/OAuth; cần map "
            "quyền từ identity provider.",
            "Yêu cầu bắt buộc: single sign-on (SSO) với IdP nội bộ và SAML.",
        ],
        "external_data_sync": [
            "Dữ liệu phải đồng bộ (data sync) hai chiều với hệ thống kho vận, chạy "
            "tự động mỗi 15 phút và có xử lý xung đột.",
            "Cần đồng bộ liên tục (synchronization) giữa ứng dụng mới và các hệ "
            "thống back-office.",
        ],
        "data_migration": [
            "Phải bao gồm migration dữ liệu (data migration) từ hệ thống cũ, khoảng "
            "4 triệu bản ghi, có kiểm tra đối chiếu.",
            "Cần di chuyển dữ liệu từ database hiện tại sang hệ thống mới, có "
            "validation.",
        ],
        "multi_currency": [
            "Chúng tôi kinh doanh nhiều thị trường nên cần hỗ trợ multi-currency và "
            "tỷ giá cập nhật hằng ngày.",
            "Hóa đơn phải hỗ trợ nhiều loại tiền tệ (multi-currency).",
        ],
        "multi_tenancy": [
            "Kiến trúc phải là multi-tenant, mỗi khách hàng là một tenant tách biệt "
            "dữ liệu.",
            "Cần multi-tenancy với cấu hình riêng cho từng tenant.",
        ],
        "realtime_ui": [
            "Màn hình điều hành cần cập nhật real-time (dưới 100ms) qua WebSocket.",
            "Dashboard phải cập nhật theo thời gian thực (real-time), không cần "
            "refresh tay.",
        ],
        "mobile_app": [
            "Nhân viên hiện trường cần ứng dụng mobile native (mobile app) cho cả "
            "iOS và Android.",
            "Cần mobile app iOS/Android chứ không chỉ web responsive.",
        ],
        "offline_mode": [
            "Kỹ thuật viên thường làm việc ở nơi không có kết nối, nên ứng dụng phải "
            "hoạt động offline (offline mode), lưu dữ liệu cục bộ.",
            "Cần chế độ offline cho quy trình kiểm tra khi thiết bị mất kết nối.",
        ],
        "pci_dss": [
            "Vì xử lý dữ liệu thẻ, chúng tôi bắt buộc tuân thủ PCI-DSS (bao gồm mã "
            "hóa và tokenization).",
            "Cần đạt chuẩn PCI-DSS cho dữ liệu thẻ.",
        ],
        "privacy_compliance": [
            "Có khách hàng tại EU nên phải tuân thủ GDPR (privacy compliance) và "
            "quyền xóa dữ liệu.",
            "Sản phẩm cần đáp ứng yêu cầu GDPR/HIPAA về dữ liệu cá nhân.",
        ],
        "audit_logging": [
            "Cơ quan quản lý yêu cầu audit log đầy đủ cho mọi thay đổi dữ liệu.",
            "Cần audit logging chi tiết, có thể tra cứu lịch sử thao tác.",
        ],
        "legacy_tech_stack": [
            "Phần backend chạy trên hệ thống legacy (COBOL, on-prem), tài liệu rất ít.",
            "Phải làm việc với legacy tech stack cũ, khó tuyển developer.",
        ],
        "cross_team_coordination": [
            "Triển khai cần cross-team coordination: IT nội bộ, data team và một "
            "nhà cung cấp khác.",
            "Dự án liên quan nhiều team, cần phối hợp (coordination) thường xuyên.",
        ],
    },
}

# --- Negation sentences for absent features ----------------------------------

NEGATION_SENTENCES: dict[str, dict[str, list[str]]] = {
    "en": {
        "third_party_api": [
            "No third-party API integration is needed - everything stays in our own systems.",
            "We are not integrating any external API in this phase.",
        ],
        "payment_gateway": [
            "No payment gateway is needed; invoicing is handled by our finance team.",
            "We are not processing online payments, so no payment support is required.",
        ],
        "identity_provider": [
            "We will not use an external identity provider - local username/password login is fine.",
            "SSO is out of scope for now; accounts are created manually by admins.",
        ],
        "external_data_sync": [
            "There is no external data synchronization required; this is a standalone tool.",
            "The tool does not need to stay in sync with any other system.",
        ],
        "data_migration": [
            "No data migration is needed; we are starting from a clean database.",
            "There is no migration work - only new records will be created.",
        ],
        "multi_currency": [
            "We only work in USD, so multi-currency support is not required.",
            "Single currency is fine; no multi-currency handling needed.",
        ],
        "multi_tenancy": [
            "This is single-tenant, so no multi-tenancy support is needed.",
            "Multi-tenant architecture is not required for this deployment.",
        ],
        "realtime_ui": [
            "Real-time updates are not needed; refreshing the page manually is acceptable.",
            "The UI does not need live updates - a normal page load is fine.",
        ],
        "mobile_app": [
            "No mobile app is needed - a responsive web page is enough.",
            "We do not need native iOS or Android apps for this project.",
        ],
        "offline_mode": [
            "Offline mode is not required; users always have connectivity.",
            "The app can assume a stable internet connection, so no offline support is needed.",
        ],
        "pci_dss": [
            "PCI-DSS compliance is out of scope because we never store card data.",
            "We are not handling cardholder data, so PCI-DSS does not apply.",
        ],
        "privacy_compliance": [
            "GDPR/HIPAA compliance is not required for this internal tool.",
            "Privacy regulation scope is minimal here; no GDPR obligations apply.",
        ],
        "audit_logging": [
            "Detailed audit logging is not required at this stage.",
            "We do not need a formal audit trail for this workflow.",
        ],
        "legacy_tech_stack": [
            "There is no legacy system involved - this is a greenfield project.",
            "We are building fresh; no legacy technology is involved.",
        ],
        "cross_team_coordination": [
            "No cross-team coordination is needed; a single team will own delivery.",
            "This stays inside one team, so no multi-team coordination is expected.",
        ],
    },
    "vi": {
        "third_party_api": ["Không cần tích hợp API bên thứ ba trong giai đoạn này."],
        "payment_gateway": ["Không cần cổng thanh toán (payment gateway)."],
        "identity_provider": ["Không dùng identity provider bên ngoài, login nội bộ là đủ."],
        "external_data_sync": ["Không cần đồng bộ dữ liệu với hệ thống ngoài."],
        "data_migration": ["Không cần migration dữ liệu, bắt đầu từ database mới."],
        "multi_currency": ["Chỉ dùng USD, không cần multi-currency."],
        "multi_tenancy": ["Chỉ một tenant, không cần multi-tenancy."],
        "realtime_ui": ["Không cần real-time, refresh thủ công là được."],
        "mobile_app": ["Không cần mobile app, web responsive là đủ."],
        "offline_mode": ["Không cần offline mode, người dùng luôn có kết nối."],
        "pci_dss": ["PCI-DSS không nằm trong phạm vi vì không lưu dữ liệu thẻ."],
        "privacy_compliance": ["Không yêu cầu GDPR/HIPAA cho công cụ nội bộ này."],
        "audit_logging": ["Chưa cần audit logging chi tiết ở giai đoạn này."],
        "legacy_tech_stack": ["Không có hệ thống legacy, đây là dự án mới hoàn toàn."],
        "cross_team_coordination": ["Không cần phối hợp nhiều team, một team tự làm là đủ."],
    },
}

# --- Fluff and sign-off -------------------------------------------------------

_FLUFF = {
    "en": [
        "Please include a rough breakdown by phase and the key assumptions in your proposal.",
        "We are flexible on the technical stack as long as the solution is maintainable.",
        "A short plan with milestones would help us align internally before the board meeting.",
        "Feel free to ask clarifying questions - we can arrange a call this week.",
        "We would appreciate a firm quote with a validity period of 30 days.",
        "The procurement process is straightforward; we can sign within two weeks.",
        "A security review and user acceptance testing will be part of the acceptance process.",
        "Please send an indicative timeline together with the commercial proposal.",
        "We have a reference architecture document we can share after the first call.",
        "Your team's experience with similar systems in our industry would be a plus.",
    ],
    "vi": [
        "Vui lòng gửi kèm bảng phân rã công việc và các giả định chính trong proposal.",
        "Chúng tôi linh hoạt về công nghệ miễn là giải pháp dễ bảo trì về lâu dài.",
        "Mong nhận được báo giá chi tiết trong tuần này để kịp trình ban lãnh đạo.",
        "Nếu cần thêm thông tin, anh/chị cứ hỏi, bên tôi có thể sắp xếp một cuộc gọi.",
        "Quy trình mua sắm bên tôi khá nhanh, có thể ký hợp đồng trong hai tuần.",
        "Vui lòng gửi kèm timeline sơ bộ và các mốc bàn giao chính.",
        "Kinh nghiệm của đội bạn với các hệ thống tương tự là một điểm cộng lớn.",
        "Sau buổi trao đổi đầu tiên, bên tôi có thể chia sẻ tài liệu kiến trúc tham chiếu.",
    ],
}

_SIGNOFFS = {
    "en": ["Best regards,", "Kind regards,", "Thanks in advance,", "Regards,"],
    "vi": ["Trân trọng,", "Cảm ơn anh/chị,", "Thân mến,"],
}

# Probability that a mixed-language email uses Vietnamese for a given sentence.
_MIXED_VI_PROBABILITY = 0.4


def _pick(rng: random.Random, pool: Sequence[str]) -> str:
    """Pick one element from a non-empty pool."""
    return pool[rng.randrange(len(pool))]


def _word_count(*chunks: str) -> int:
    """Total whitespace-separated word count of the given chunks."""
    return sum(len(chunk.split()) for chunk in chunks)


def _sentence_language(rng: random.Random, mode: str) -> str:
    """Resolve the language ('en'|'vi') of a single sentence under ``mode``."""
    if mode == "vi":
        return "vi"
    if mode == "en":
        return "en"
    return "vi" if rng.random() < _MIXED_VI_PROBABILITY else "en"


def compose_email(rng: random.Random, *, mentioned: Sequence[str], negated: Sequence[str]) -> str:
    """Build one client email.

    Args:
        rng: shared deterministic RNG (consumed in a fixed order).
        mentioned: present features that *should* be mentioned (canonical order).
        negated: absent features that get an explicit negation sentence.

    Returns:
        Email text with 120-350 words. Mention bookkeeping stays with the caller.
    """
    # ~70% EN, ~15% VI, ~15% mixed (documented language mix).
    mode = _pick(rng, ("en",) * 14 + ("vi",) * 3 + ("mixed",) * 3)
    # Vietnamese and mixed emails open in Vietnamese; EN emails stay English.
    context_lang = "en" if mode == "en" else "vi"
    contact_name, contact_title = _pick(rng, _CONTACTS_VI if context_lang == "vi" else _CONTACTS_EN)
    client = _pick(rng, _CLIENTS)

    greeting = _pick(rng, _GREETINGS[context_lang])
    context = _pick(rng, _CONTEXT[context_lang]).format(
        contact=contact_name,
        client=client,
        project=_pick(rng, _PROJECTS_VI if context_lang == "vi" else _PROJECTS_EN),
        users=f"{_pick(rng, _USER_COUNTS):,}",
        budget=f"{_pick(rng, _BUDGETS_USD):,}",
        months=_pick(rng, _TIMELINES_MONTHS),
    )

    body: list[str] = [context]
    ordered_mentions = list(mentioned)
    rng.shuffle(ordered_mentions)
    for name in ordered_mentions:
        lang = _sentence_language(rng, mode)
        body.append(_pick(rng, FEATURE_SENTENCES[lang][name]))
    ordered_negations = list(negated)
    rng.shuffle(ordered_negations)
    for name in ordered_negations:
        lang = _sentence_language(rng, mode)
        body.append(_pick(rng, NEGATION_SENTENCES[lang][name]))

    signoff = "{signoff}\n{name}\n{title}, {client}".format(
        signoff=_pick(rng, _SIGNOFFS["en" if context_lang == "en" else "vi"]),
        name=contact_name,
        title=contact_title,
        client=client,
    )

    # Pad short emails with fluff until they reach MIN_WORDS. High-feature-count
    # emails are already long enough and get no fluff at all; the core sentence
    # lengths keep the text well below _MAX_WORDS in practice.
    fluff_pool = list(_FLUFF["en" if mode == "en" else "vi"])
    rng.shuffle(fluff_pool)
    fluff: list[str] = []
    fixed_words = _word_count(greeting, signoff, *body)
    while fixed_words + _word_count(*fluff) < MIN_WORDS and fluff_pool:
        fluff.append(fluff_pool.pop())

    paragraphs = [greeting, " ".join(body)]
    if fluff:
        paragraphs.append(" ".join(fluff))
    paragraphs.append(signoff)
    text = "\n\n".join(paragraphs)
    # Invariant for the current sentence pools; guards future template edits
    # against silently breaking the 120-350-word contract.
    assert MIN_WORDS <= _word_count(text) <= _MAX_WORDS
    return text
