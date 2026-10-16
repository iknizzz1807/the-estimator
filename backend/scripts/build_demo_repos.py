"""Deterministic builder for the two Codebase Lab demo repos.

Creates, under ``data/demo_repos/`` (gitignored):

* ``payment_plugin/`` -- CLEAN plugin pattern: an abstract ``PaymentProvider``,
  a registry and one file per provider; provider commits mostly ADD files; two
  authors; a high ``coverage.xml`` line-rate.
* ``payment_spaghetti/`` -- MESSY: the same provider knowledge hardcoded as
  ``if provider == "stripe"`` branches across eight modules, no tests, no
  coverage, one author, high churn on the same files.

Every commit uses fixed ``GIT_AUTHOR_DATE``/``GIT_COMMITTER_DATE`` and author
identities, so rebuilding produces the identical history (identical commit
hashes and therefore identical analyzer signals).

Usage (from ``backend/``)::

    python scripts/build_demo_repos.py [--force] [--target DIR]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_REPOS_DIR = REPO_ROOT / "data" / "demo_repos"

ALICE = ("Alice Tran", "alice@example.com")
BOB = ("Bao Pham", "bao@example.com")
SOLO = ("Minh Nguyen", "minh@example.com")  # single author of the spaghetti repo


# --------------------------------------------------------------------------- #
# git plumbing
# --------------------------------------------------------------------------- #


def _run_git(repo: Path, args: list[str], *, date: str | None = None,
             author: tuple[str, str] | None = None) -> None:
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    if author is not None:
        name, email = author
        env["GIT_AUTHOR_NAME"] = name
        env["GIT_AUTHOR_EMAIL"] = email
        env["GIT_COMMITTER_NAME"] = name
        env["GIT_COMMITTER_EMAIL"] = email
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "commit.gpgsign=false",
            # FUSE/PRoot on-device quirk: repos can be owned by another uid;
            # pin safe.directory to this demo repo only (never a global '*').
            "-c",
            f"safe.directory={Path(repo).resolve()}",
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}"
        )


def _write(repo: Path, rel_path: str, text: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, day: str, author: tuple[str, str], message: str) -> None:
    """Stage everything and commit with fixed author/committer identity + date."""
    date = f"{day}T10:00:00+00:00"
    _run_git(repo, ["add", "-A"])
    _run_git(repo, ["commit", "-q", "-m", message], date=date, author=author)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(path, ["init", "-q", "-b", "main"])


# --------------------------------------------------------------------------- #
# payment_plugin (CLEAN)
# --------------------------------------------------------------------------- #

PLUGIN_BASE_V1 = '''"""Abstract payment provider interface."""

from abc import ABC, abstractmethod


class PaymentProvider(ABC):
    """Base class every payment provider implements."""

    name: str = "abstract"

    @abstractmethod
    def charge(self, amount_cents: int, currency: str) -> str:
        """Charge ``amount_cents`` and return the provider charge id."""

    @abstractmethod
    def refund(self, charge_id: str) -> bool:
        """Refund a previous charge; True when accepted."""
'''

PLUGIN_BASE_V2 = '''"""Abstract payment provider interface."""

from abc import ABC, abstractmethod


def validate_amount(amount_cents: int) -> int:
    """Reject non-positive amounts before they reach a provider."""
    if amount_cents <= 0:
        raise ValueError("amount must be positive")
    return amount_cents


class PaymentProvider(ABC):
    """Base class every payment provider implements."""

    name: str = "abstract"

    @abstractmethod
    def charge(self, amount_cents: int, currency: str) -> str:
        """Charge ``amount_cents`` and return the provider charge id."""

    @abstractmethod
    def refund(self, charge_id: str) -> bool:
        """Refund a previous charge; True when accepted."""
'''

PLUGIN_INIT = '''"""Payment provider plugins package."""

from payments.registry import available, get_provider, register

__all__ = ["available", "get_provider", "register"]
'''

PLUGIN_PROVIDERS_INIT = '''"""Built-in payment providers."""
'''

PLUGIN_REGISTRY_V1 = '''"""Provider registry: name -> provider class."""

from payments.base import PaymentProvider
from payments.providers.stripe import StripeProvider

_PROVIDERS: dict[str, type[PaymentProvider]] = {"stripe": StripeProvider}


def register(name: str, provider: type[PaymentProvider]) -> None:
    """Register a provider class under ``name``."""
    _PROVIDERS[name] = provider


def get_provider(name: str) -> type[PaymentProvider]:
    """Look up a provider class; KeyError when unknown."""
    if name not in _PROVIDERS:
        raise KeyError(f"unknown payment provider: {name}")
    return _PROVIDERS[name]


def available() -> list[str]:
    """Sorted registered provider names."""
    return sorted(_PROVIDERS)
'''

PLUGIN_REGISTRY_V2 = PLUGIN_REGISTRY_V1.replace(
    "from payments.providers.stripe import StripeProvider",
    "from payments.providers.paypal import PayPalProvider\n"
    "from payments.providers.stripe import StripeProvider",
).replace(
    '_PROVIDERS: dict[str, type[PaymentProvider]] = {"stripe": StripeProvider}',
    '_PROVIDERS: dict[str, type[PaymentProvider]] = {\n'
    '    "stripe": StripeProvider,\n'
    '    "paypal": PayPalProvider,\n'
    "}",
)

PLUGIN_REGISTRY_V3 = PLUGIN_REGISTRY_V2.replace(
    '    """Register a provider class under ``name``."""\n    _PROVIDERS[name] = provider',
    '    """Register a provider class under ``name``."""\n'
    '    if not name:\n'
    '        raise ValueError("provider name is required")\n'
    "    _PROVIDERS[name] = provider",
)

PLUGIN_REGISTRY_V4 = PLUGIN_REGISTRY_V3.replace(
    "from payments.providers.paypal import PayPalProvider",
    "from payments.providers.klarna import KlarnaProvider\n"
    "from payments.providers.paypal import PayPalProvider",
).replace(
    '    "paypal": PayPalProvider,\n',
    '    "paypal": PayPalProvider,\n    "klarna": KlarnaProvider,\n',
)

PLUGIN_STRIPE = '''"""Stripe payment provider."""

from payments.base import PaymentProvider, validate_amount


class StripeProvider(PaymentProvider):
    """Stripe card payments."""

    name = "stripe"

    def charge(self, amount_cents: int, currency: str) -> str:
        validate_amount(amount_cents)
        return f"stripe-charge-{amount_cents}-{currency}"

    def refund(self, charge_id: str) -> bool:
        return charge_id.startswith("stripe-")
'''

PLUGIN_PAYPAL = '''"""PayPal payment provider."""

from payments.base import PaymentProvider, validate_amount


class PayPalProvider(PaymentProvider):
    """PayPal balance / card payments."""

    name = "paypal"

    def charge(self, amount_cents: int, currency: str) -> str:
        validate_amount(amount_cents)
        return f"paypal-charge-{amount_cents}-{currency}"

    def refund(self, charge_id: str) -> bool:
        return charge_id.startswith("paypal-")
'''

PLUGIN_KLARNA = '''"""Klarna payment provider."""

from payments.base import PaymentProvider, validate_amount


class KlarnaProvider(PaymentProvider):
    """Klarna buy-now-pay-later."""

    name = "klarna"

    def charge(self, amount_cents: int, currency: str) -> str:
        validate_amount(amount_cents)
        return f"klarna-charge-{amount_cents}-{currency}"

    def refund(self, charge_id: str) -> bool:
        return charge_id.startswith("klarna-")
'''

PLUGIN_TEST_REGISTRY = '''"""Registry tests."""

from payments.providers.paypal import PayPalProvider
from payments.providers.stripe import StripeProvider
from payments.registry import available, get_provider


def test_registry_knows_stripe() -> None:
    assert get_provider("stripe") is StripeProvider


def test_registry_knows_paypal() -> None:
    assert get_provider("paypal") is PayPalProvider


def test_registry_rejects_unknown_provider() -> None:
    try:
        get_provider("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_available_is_sorted() -> None:
    assert available() == sorted(available())
'''

PLUGIN_TEST_PROVIDERS = '''"""Provider behaviour tests."""

from payments.providers.stripe import StripeProvider


def test_stripe_charge_id_prefix() -> None:
    provider = StripeProvider()
    assert provider.charge(1000, "usd").startswith("stripe-")


def test_stripe_refund_round_trip() -> None:
    provider = StripeProvider()
    charge_id = provider.charge(1000, "usd")
    assert provider.refund(charge_id) is True
'''

PLUGIN_README_V1 = """# Payment plugin demo

A tiny plugin-pattern payments module: every provider is a NEW file under
`payments/providers/` implementing `PaymentProvider`, registered in
`payments/registry.py`.
"""

PLUGIN_README_V2 = PLUGIN_README_V1 + """
## Adding a provider

1. create `payments/providers/<name>.py` implementing `PaymentProvider`;
2. register it in `payments/registry.py`;
3. add a test under `tests/`.

No other module changes.
"""

PLUGIN_EXAMPLE = '''"""Example: register a new payment provider."""

from payments.providers.paypal import PayPalProvider
from payments.registry import register


def main() -> None:
    register("paypal", PayPalProvider)
    print("registered paypal")


if __name__ == "__main__":
    main()
'''

PLUGIN_COVERAGE_XML = '''<?xml version="1.0" ?>
<coverage version="7.6.0" timestamp="1772200000000" lines-valid="52" lines-covered="49" line-rate="0.94" branches-valid="12" branches-covered="10" branch-rate="0.8333" complexity="0">
  <sources>
    <source>.</source>
  </sources>
  <packages>
    <package name="payments" line-rate="0.96" branch-rate="0.9" complexity="0">
      <classes>
        <class name="base.py" filename="payments/base.py" complexity="0" line-rate="1.0" branch-rate="1.0"/>
        <class name="registry.py" filename="payments/registry.py" complexity="0" line-rate="0.95" branch-rate="0.85"/>
      </classes>
    </package>
    <package name="payments.providers" line-rate="0.92" branch-rate="0.8" complexity="0">
      <classes>
        <class name="stripe.py" filename="payments/providers/stripe.py" complexity="0" line-rate="0.94" branch-rate="1.0"/>
        <class name="paypal.py" filename="payments/providers/paypal.py" complexity="0" line-rate="0.9" branch-rate="1.0"/>
        <class name="klarna.py" filename="payments/providers/klarna.py" complexity="0" line-rate="0.9" branch-rate="1.0"/>
      </classes>
    </package>
    <package name="tests" line-rate="1.0" branch-rate="1.0" complexity="0">
      <classes>
        <class name="test_registry.py" filename="tests/test_registry.py" complexity="0" line-rate="1.0" branch-rate="1.0"/>
        <class name="test_providers.py" filename="tests/test_providers.py" complexity="0" line-rate="1.0" branch-rate="1.0"/>
      </classes>
    </package>
  </packages>
</coverage>
'''


def _build_plugin(repo: Path) -> None:
    _init_repo(repo)

    _write(repo, "payments/__init__.py", PLUGIN_INIT)
    _write(repo, "payments/base.py", PLUGIN_BASE_V1)
    _commit(repo, "2025-11-02", ALICE, "Scaffold payments package and provider interface")

    _write(repo, "payments/registry.py", PLUGIN_REGISTRY_V1)
    _write(repo, "payments/providers/__init__.py", PLUGIN_PROVIDERS_INIT)
    _write(repo, "payments/providers/stripe.py", PLUGIN_STRIPE)
    _commit(repo, "2025-11-10", ALICE, "Add stripe provider and registry")

    _write(repo, "payments/providers/paypal.py", PLUGIN_PAYPAL)
    _write(repo, "payments/registry.py", PLUGIN_REGISTRY_V2)
    _commit(repo, "2025-12-01", BOB, "Add paypal provider (new file + registry line)")

    _write(repo, "tests/test_registry.py", PLUGIN_TEST_REGISTRY)
    _write(repo, "tests/test_providers.py", PLUGIN_TEST_PROVIDERS)
    _commit(repo, "2025-12-20", ALICE, "Add registry and provider tests")

    _write(repo, "payments/base.py", PLUGIN_BASE_V2)
    _write(repo, "payments/registry.py", PLUGIN_REGISTRY_V3)
    _commit(repo, "2026-01-15", BOB, "Validate provider names and amounts")

    _write(repo, "payments/providers/klarna.py", PLUGIN_KLARNA)
    _write(repo, "payments/registry.py", PLUGIN_REGISTRY_V4)
    _commit(repo, "2026-02-01", ALICE, "Add klarna provider (new file + registry line)")

    _write(repo, "README.md", PLUGIN_README_V1)
    _commit(repo, "2026-02-20", BOB, "Add README")

    _write(repo, "examples/add_provider.py", PLUGIN_EXAMPLE)
    _write(repo, "README.md", PLUGIN_README_V2)
    _commit(repo, "2026-03-05", ALICE, "Add provider example and README section")

    # Working-tree coverage report (not committed): the analyzer reads it from
    # disk, exercising the "coverage found / high line-rate" path.
    _write(repo, "coverage.xml", PLUGIN_COVERAGE_XML)


# --------------------------------------------------------------------------- #
# payment_spaghetti (MESSY)
# --------------------------------------------------------------------------- #

SPAGHETTI_INITIAL: dict[str, str] = {
    "utils.py": '''"""Shared helpers. Provider logic should NOT live here, but it does."""


SCHEMA_VERSION = 1


def format_money(amount, currency):
    if currency == "usd":
        return f"${amount:,.2f}"
    elif currency == "eur":
        return f"{amount:,.2f} EUR"
    elif currency == "vnd":
        return f"{amount:,.0f} VND"
    return f"{amount} {currency}"


def log_event(name, payload):
    if name == "stripe":
        payload = dict(payload, provider="stripe")
    elif name == "paypal":
        payload = dict(payload, provider="paypal")
    return {"event": name, "payload": payload}
''',
    "models.py": '''"""Data models. Provider names are raw strings everywhere."""

from utils import format_money

SCHEMA_VERSION = 1


class Order:
    def __init__(self, provider, items, currency, coupon=None):
        self.provider = provider
        self.items = items
        self.currency = currency
        self.coupon = coupon

    def total(self):
        total = sum(item["price"] * item["qty"] for item in self.items)
        if self.provider == "stripe":
            total = total * 1.029
        elif self.provider == "paypal":
            total = total * 1.034
        if self.coupon == "SAVE10":
            total = total - 10
        return round(total, 2)

    def label(self):
        return format_money(self.total(), self.currency)


class Customer:
    def __init__(self, email, provider):
        self.email = email
        self.provider = provider
        if provider == "stripe":
            self.billing = "card"
        elif provider == "paypal":
            self.billing = "paypal-balance"
        else:
            self.billing = "invoice"
''',
    "checkout.py": '''"""Checkout flow. Provider branches are copied into every function."""

from models import Customer, Order
from utils import format_money, log_event

SCHEMA_VERSION = 1


def process_checkout(provider, cart, coupon, currency, tax_rate, retry):
    total = 0
    for item in cart:
        total = total + item["price"] * item["qty"]
    if provider == "stripe":
        total = total * 1.029
        if retry:
            total = total + 2
        if coupon == "SAVE10":
            total = total - 10
    elif provider == "paypal":
        total = total * 1.034
        if retry:
            total = total + 3
    elif provider == "adyen":
        total = total * 1.041
        if coupon == "SAVE10":
            total = total - 8
    elif provider == "":
        raise ValueError("provider required")
    else:
        total = total + 1
    if currency == "usd":
        total = total + 0
    elif currency == "eur":
        total = total * 0.92
    elif currency == "vnd":
        total = total * 25000
    if tax_rate > 0:
        total = total * (1 + tax_rate)
    if total < 0:
        total = 0
    log_event("checkout", {"provider": provider})
    return format_money(round(total, 2), currency)


def build_order(provider, cart, currency, coupon):
    order = Order(provider, cart, currency, coupon)
    customer = Customer("guest@example.com", provider)
    if provider == "stripe":
        retry = True
    else:
        retry = False
    return order, customer, retry
''',
    "orders.py": '''"""Order lifecycle. Provider checks duplicated from checkout."""

from models import Order
from utils import format_money

SCHEMA_VERSION = 1


def create_order(provider, items, currency):
    order = Order(provider, items, currency)
    if provider == "stripe":
        status = "requires_capture"
    elif provider == "paypal":
        status = "requires_approval"
    else:
        status = "pending"
    return {"order": order, "status": status}


def cancel_order(provider, order):
    if provider == "stripe":
        return {"cancelled": True, "fee": 0}
    elif provider == "paypal":
        return {"cancelled": True, "fee": 1}
    return {"cancelled": True, "fee": 2}


def order_summary(provider, items, currency):
    order = Order(provider, items, currency)
    if provider == "stripe":
        note = "card statement shows stripe"
    else:
        note = "generic statement"
    return {"total": format_money(order.total(), currency), "note": note}
''',
    "billing.py": '''"""Billing and invoicing with hardcoded provider branches."""

from utils import format_money

SCHEMA_VERSION = 1


def calculate_invoice(provider, plan, seats, currency, coupon, tax_rate, proration, trial_days):
    total = plan * seats
    if provider == "stripe":
        if proration:
            total = total * 0.9
        if coupon == "SAVE10":
            total = total - 10
    elif provider == "paypal":
        if trial_days > 0:
            total = total * 0.95
        if coupon == "SAVE10":
            total = total - 5
    else:
        total = total + 1
    if currency == "eur":
        total = total * 0.92
    elif currency == "vnd":
        total = total * 25000
    if tax_rate > 0:
        total = total * (1 + tax_rate)
    if total < 0:
        total = 0
    return format_money(round(total, 2), currency)


def refund_invoice(provider, invoice_id, amount):
    if provider == "stripe":
        return {"refunded": amount, "channel": "stripe-api"}
    elif provider == "paypal":
        return {"refunded": amount * 0.98, "channel": "paypal-api"}
    return {"refunded": 0, "channel": "manual"}
''',
    "api.py": '''"""HTTP handlers. Provider branching leaks into the API layer too."""

from billing import calculate_invoice, refund_invoice
from checkout import build_order, process_checkout
from models import Customer
from orders import cancel_order
from utils import log_event

SCHEMA_VERSION = 1


def handle_checkout(payload):
    provider = payload.get("provider")
    if provider == "stripe":
        payload["retry"] = True
    result = process_checkout(
        provider,
        payload.get("cart", []),
        payload.get("coupon"),
        payload.get("currency", "usd"),
        payload.get("tax_rate", 0),
        payload.get("retry", False),
    )
    order, customer, retry = build_order(
        provider, payload.get("cart", []), payload.get("currency", "usd"), payload.get("coupon")
    )
    log_event("api", {"provider": provider, "retry": retry})
    return {"total": result, "order": order.label(), "customer": customer.email}


def handle_cancel(payload):
    if payload.get("provider") == "paypal":
        return cancel_order("paypal", payload.get("order"))
    return cancel_order(payload.get("provider"), payload.get("order"))


def handle_invoice(payload):
    provider = payload.get("provider")
    if provider == "stripe":
        seats = payload.get("seats", 1)
    else:
        seats = payload.get("seats", 2)
    return calculate_invoice(
        provider,
        payload.get("plan", 9),
        seats,
        payload.get("currency", "usd"),
        payload.get("coupon"),
        payload.get("tax_rate", 0),
        payload.get("proration", False),
        payload.get("trial_days", 0),
    )


def handle_refund(payload):
    if payload.get("provider") == "stripe":
        return refund_invoice("stripe", payload.get("invoice_id"), payload.get("amount", 0))
    return refund_invoice(payload.get("provider"), payload.get("invoice_id"), payload.get("amount", 0))
''',
    "admin.py": '''"""Admin views. Provider checks copied once more."""

from billing import refund_invoice
from utils import log_event

SCHEMA_VERSION = 1


def admin_dashboard(provider):
    if provider == "stripe":
        return {"provider": provider, "fees": "2.9% + 30c", "payout": "2 days"}
    elif provider == "paypal":
        return {"provider": provider, "fees": "3.4% + 35c", "payout": "1 day"}
    return {"provider": provider, "fees": "n/a", "payout": "manual"}


def admin_force_refund(provider, invoice_id, amount):
    log_event("admin", {"provider": provider, "invoice": invoice_id})
    if provider == "stripe":
        amount = amount * 1.0
    elif provider == "paypal":
        amount = amount * 1.01
    return refund_invoice(provider, invoice_id, amount)
''',
    "legacy.py": '''"""Legacy migration helpers still wired into the HTTP path."""

from models import Order
from utils import format_money

SCHEMA_VERSION = 1


def legacy_import_row(row, provider):
    if provider == "stripe":
        row["provider_id"] = "stripe:" + str(row.get("id"))
    elif provider == "paypal":
        row["provider_id"] = "paypal:" + str(row.get("id"))
    else:
        row["provider_id"] = str(row.get("id"))
    return row


def legacy_total(rows, provider, currency):
    total = 0
    for row in rows:
        amount = row.get("amount", 0)
        if provider == "stripe":
            amount = amount * 1.029
        elif provider == "paypal":
            amount = amount * 1.034
        total = total + amount
    order = Order(provider, [], currency)
    return format_money(round(total, 2), currency)
''',
}

SPAGHETTI_SNIPPET = '''

def step_{commit_no}_{stem}(provider, amount, flags):
    """Change #{commit_no} patched {path} again with the same provider branches."""
    total = amount
    if provider == "stripe":
        total = amount * 1.029 + {commit_no}
        if "retry" in flags:
            total = total + 2
    elif provider == "paypal":
        total = amount * 1.034
        if "retry" in flags:
            total = total + 3
    else:
        total = amount + {commit_no}
    if total < 0:
        total = 0
    return round(total, 2)
'''

_SCHEMA_RE = re.compile(r"^SCHEMA_VERSION = \d+$", re.MULTILINE)


def _patch_file(repo: Path, rel_path: str, commit_no: int) -> None:
    """Bump the schema marker (a removed line) and append a new branchy function."""
    path = repo / rel_path
    text = path.read_text(encoding="utf-8")
    text = _SCHEMA_RE.sub(f"SCHEMA_VERSION = {commit_no + 1}", text)
    stem = Path(rel_path).stem
    text += SPAGHETTI_SNIPPET.format(commit_no=commit_no, stem=stem, path=rel_path)
    path.write_text(text, encoding="utf-8")


def _build_spaghetti(repo: Path) -> None:
    _init_repo(repo)

    # (day, message, files): create or patch, every commit on the same 8 files.
    plan: list[tuple[str, str, list[str]]] = [
        ("2025-11-05", "Initial checkout flow", ["checkout.py", "orders.py", "models.py", "utils.py"]),
        ("2025-11-20", "Add billing module", ["checkout.py", "orders.py", "models.py", "utils.py", "billing.py"]),
        ("2025-12-05", "Add API handlers and stripe branches", ["checkout.py", "orders.py", "billing.py", "models.py", "utils.py", "api.py"]),
        ("2025-12-15", "Patch totals and coupons everywhere", ["checkout.py", "orders.py", "billing.py", "api.py", "models.py", "utils.py"]),
        ("2026-01-05", "Add admin views and touch core files", ["api.py", "models.py", "utils.py", "admin.py"]),
        ("2026-01-20", "Round of provider fixes across all modules", ["checkout.py", "orders.py", "billing.py", "api.py", "models.py", "utils.py", "admin.py"]),
        ("2026-02-05", "Add legacy import helpers", ["utils.py", "models.py", "orders.py", "legacy.py"]),
        ("2026-02-18", "Fix retry totals in billing and utils", ["utils.py", "billing.py", "checkout.py", "legacy.py", "api.py"]),
        ("2026-03-02", "Harden API and admin provider branches", ["api.py", "checkout.py", "orders.py", "admin.py", "legacy.py", "models.py"]),
        ("2026-03-10", "Legacy migration cleanup across modules", ["legacy.py", "models.py", "utils.py", "billing.py", "orders.py", "checkout.py"]),
    ]

    for commit_no, (day, message, touched) in enumerate(plan, start=1):
        for rel_path in touched:
            if (repo / rel_path).exists():
                _patch_file(repo, rel_path, commit_no)
            else:
                _write(repo, rel_path, SPAGHETTI_INITIAL[rel_path])
        _commit(repo, day, SOLO, message)

    # NOTE: no tests, no coverage report -- the analyzer must report coverage
    # as "unknown" (never faked) for this repo.


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def build_demo_repos(
    target_dir: str | Path | None = None, force: bool = False
) -> dict[str, Path]:
    """Build both demo repos under ``target_dir`` (default ``data/demo_repos``).

    Existing repos are left untouched unless ``force=True``. With ``force`` (or
    on a fresh target) the rebuild is byte-comparable: fixed authors, fixed
    dates and deterministic file contents produce identical commit hashes and
    therefore identical analyzer signals.
    """
    target = Path(target_dir) if target_dir is not None else DEMO_REPOS_DIR
    builders = {"payment_plugin": _build_plugin, "payment_spaghetti": _build_spaghetti}
    repos: dict[str, Path] = {}
    for name, builder in builders.items():
        repo = target / name
        if repo.exists():
            if not force:
                repos[name] = repo
                continue
            shutil.rmtree(repo)
        builder(repo)
        repos[name] = repo
    return repos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="delete and rebuild existing repos")
    parser.add_argument(
        "--target",
        default=str(DEMO_REPOS_DIR),
        help=f"output directory (default: {DEMO_REPOS_DIR})",
    )
    args = parser.parse_args(argv)
    repos = build_demo_repos(args.target, force=args.force)
    for name, path in repos.items():
        count = subprocess.run(
            [
                "git", "-C", str(path),
                "-c", f"safe.directory={Path(path).resolve()}",
                "rev-list", "--count", "HEAD",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        print(f"{name}: {path} ({count} commits)")
    print(
        "Demo check date (covers the full 6-month churn window): 2026-04-01\n"
        "Next: python scripts/codebase_cli.py --demo"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
