"""LLM-with-history baseline: the fair strawman "LLM + company history".

docs/API.md (contract additions v0.2): POST /api/ab gains a third baseline —
the same email run through an LLM whose prompt includes the most recent
finished projects of the company (compact table: project_id, active feature
names, actual person-days). This is the honest strawman a judge will ask
about: an LLM that at least sees what the company actually shipped recently.

Design notes
------------
- ``llm_history_estimate`` runs ``n`` independent calls and returns the list of
  successfully parsed numbers (length <= n). Failed calls are SKIPPED, not
  raised: the caller recovers the failure count as ``n - len(values)``. A batch
  where every call fails returns ``[]`` (baseline unavailable). This keeps one
  flaky call from killing an otherwise valid A/B response.
- Every value is clamped to [1, 365] person-days; non-finite / non-positive
  numbers count as a failed call.
- Real providers return already-parsed dicts (they run ``parse_json_response``
  internally), but a raw JSON string is accepted too and parsed with the same
  helper, so a minimal protocol object that returns text keeps working.
- No leakage: this module uses exactly the ``history_rows`` it is given. The
  caller (script or API route) is responsible for passing only projects that
  were finished before the new project, i.e. the same rows the system model
  was trained on at that point in the walk-forward replay.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from app.features import FEATURES
from app.services.providers import LLMProvider, parse_json_response

#: System prompt for the history-aware estimator.
HISTORY_SYSTEM_PROMPT = (
    "You are an estimation analyst inside a software services company. "
    "You estimate the expected effort of new customer projects in person-days, "
    "using the durations of the company's recent finished projects as context. "
    "Answer with JSON only."
)

MAX_HISTORY_ROWS = 15  # "the most recent ~15 finished projects"
MIN_CLAMP_DAYS = 1.0
MAX_CLAMP_DAYS = 365.0

_DAYS_KEYS = ("days", "estimated_days", "estimate", "p50")

_HISTORY_PROMPT_TEMPLATE = """Below are the most recently finished projects of the company (internal tracker), then a new customer email.

RECENT FINISHED PROJECTS (most recent first; "features" = capabilities the project actually included):
{ROWS}

NEW CUSTOMER EMAIL:
<email>
{EMAIL}
</email>

Estimate the expected effort for the new project as a SINGLE number of person-days, based on the comparable finished projects above where possible.

Return exactly this JSON shape: {{"days": <number>}}
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def extract_days(payload: Any) -> float | None:
    """Pull a positive finite day estimate out of a provider payload.

    Accepts an already-parsed dict or a raw JSON string (parsed with
    ``parse_json_response``). Returns None when nothing usable is found.
    """
    if isinstance(payload, str):
        try:
            payload = parse_json_response(payload)
        except ValueError:
            return None
    if not isinstance(payload, Mapping):
        return None
    for key in _DAYS_KEYS:
        if key in payload:
            try:
                value = float(payload[key])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                return value
    return None


def _fmt_number(value: float) -> str:
    """42.0 -> '42', 41.5 -> '41.5' (compact history table)."""
    return str(int(value)) if float(value).is_integer() else str(round(float(value), 1))


def _actual_days(row: Mapping[str, Any]) -> float | None:
    """Positive finite actual duration, else None (row not usable as history)."""
    try:
        value = float(row.get("actual_days"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _is_finished(row: Mapping[str, Any]) -> bool:
    """Only finished projects are honest history; missing status defaults to done."""
    status = row.get("status")
    return status is None or str(status).strip().lower() == "done"


def format_history_table(
    history_rows: Sequence[Mapping[str, Any]] | None,
    max_rows: int = MAX_HISTORY_ROWS,
) -> str:
    """Compact table of the most recent finished projects (newest first).

    Columns: ``project_id | finished | features | actual person-days``.
    Invalid rows (non-positive actual_days, explicit non-done status) are
    dropped before the ``max_rows`` cut.
    """
    usable: list[tuple[str, str, str, str]] = []
    for row in history_rows or []:
        value = _actual_days(row)
        if value is None or not _is_finished(row):
            continue
        features = row.get("features") or {}
        active = ", ".join(name for name in FEATURES if features.get(name)) or "-"
        usable.append(
            (
                str(row.get("date") or ""),
                str(row.get("project_id") or "?"),
                active,
                _fmt_number(value),
            )
        )
    usable.sort(key=lambda item: (item[0], item[1]), reverse=True)
    usable = usable[: max(0, int(max_rows))]
    if not usable:
        return "(no finished projects yet)"
    lines = ["project_id | finished | features | actual person-days"]
    lines.extend(f"{pid} | {date} | {feats} | {days}" for date, pid, feats, days in usable)
    return "\n".join(lines)


def build_history_prompt(
    email_text: str,
    history_rows: Sequence[Mapping[str, Any]] | None,
    max_rows: int = MAX_HISTORY_ROWS,
) -> str:
    """User prompt: recent finished projects table + the new customer email."""
    return _HISTORY_PROMPT_TEMPLATE.replace(
        "{ROWS}", format_history_table(history_rows, max_rows=max_rows)
    ).replace("{EMAIL}", email_text)


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #


def llm_history_estimate(
    email_text: str,
    history_rows: Sequence[Mapping[str, Any]] | None,
    provider: LLMProvider,
    n: int = 3,
) -> list[float]:
    """Run the LLM-with-history point estimator ``n`` times for one email.

    Args:
        email_text: new customer email / RFP text.
        history_rows: finished projects available to the LLM (the most recent
            up to 15 are rendered). Pass only rows finished before the new
            project to avoid leakage.
        provider: any object satisfying the ``LLMProvider`` protocol.
        n: number of calls (>= 1).

    Returns:
        Successfully parsed estimates (each clamped to [1, 365] person-days),
        at most ``n`` values. Failed calls are skipped; the caller can recover
        the failure count as ``n - len(returned)`` and treats ``[]`` as
        "baseline unavailable" (documented module contract).

    Raises:
        ValueError: empty email text.
    """
    if not email_text or not email_text.strip():
        raise ValueError("Vui lòng paste email")
    count = max(1, int(n))
    prompt = build_history_prompt(email_text, history_rows)

    values: list[float] = []
    for _ in range(count):
        try:
            payload = provider.complete_json(prompt, HISTORY_SYSTEM_PROMPT)
            days = extract_days(payload)
        except Exception:
            days = None
        if days is None:
            continue
        values.append(min(MAX_CLAMP_DAYS, max(MIN_CLAMP_DAYS, days)))
    return values
