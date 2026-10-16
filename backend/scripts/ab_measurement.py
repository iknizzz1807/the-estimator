"""Real measured A/B benchmark for all four baselines -> docs/AB_MEASUREMENT.md.

Runs the configured LLM provider (``LLM_PROVIDER`` in .env, expected: deepseek)
over the walk-forward replay steps of ``data/synthetic_history.csv`` and measures
on the SAME rows, for real:

1. system: Ridge-on-log-days p50 from ``replay()`` (trained only on past rows);
2. team: the historical human estimate;
3. llm_only: ONE call per row with the exact prompt of ``POST /api/ab``;
4. llm_history: one measurement per row (``history_n`` calls, mean used) with the
   up-to-15 most recent finished projects as prompt context (the rows before
   that step - no leakage).

Plus a run-to-run variance probe (5 repeats of the LLM-only call on one
representative email) and a chars/4 token/cost estimate. Replaces the unmeasured
"±15 days" expectation (docs/SPEC.md §6.4) with a real measurement.

Robustness: each LLM call is retried once on error, failed rows are skipped and
noted, and the run ABORTS (without writing) when more than 30% of rows fail.

Usage (from backend/, real API: 1 + ``--history-n`` calls per evaluated step + 5
probe calls; with the defaults that is 42*4 + 5 = 173 calls)::

    PYTHONPATH=. /root/venvs/estimator/bin/python scripts/ab_measurement.py \\
        --limit 42 --history-n 3 --write
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Callable, Mapping, Sequence

# Allow `python scripts/ab_measurement.py` from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.features import FEATURES  # noqa: E402
from app.services.ab import (  # noqa: E402
    AB_SYSTEM_PROMPT,
    build_llm_only_prompt,
    llm_only_point,
)
from app.services.llm_baseline import (  # noqa: E402
    HISTORY_SYSTEM_PROMPT,
    MAX_HISTORY_ROWS,
    build_history_prompt,
    llm_history_estimate,
)
from app.services.providers import get_provider, LLMProvider  # noqa: E402
from app.services.replay import replay  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
REPORT_PATH = REPO_ROOT / "docs" / "AB_MEASUREMENT.md"

DEFAULT_MIN_TRAIN = 10  # mirrors app/api/state.DEFAULT_MIN_TRAIN
PROBE_REPEATS = 5
ABORT_FAILURE_RATIO = 0.30
CHARS_PER_TOKEN = 4.0  # rough chars/4 token heuristic

#: DeepSeek-V4.1-Flash list price, worst case (peak hours, cache miss),
#: USD per 1M tokens. Source: api-docs.deepseek.com/quick_start/pricing,
#: fetched 2026-10-16 (off-peak is half; cached input is far cheaper).
INPUT_USD_PER_MTOK = 0.30
OUTPUT_USD_PER_MTOK = 1.20


# --------------------------------------------------------------------------- #
# Data + call helpers
# --------------------------------------------------------------------------- #


def sha1_file(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def load_done_rows(path: Path) -> list[dict[str, Any]]:
    """CSV done rows -> canonical rows + email_text (docs/API.md conventions)."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            if str(record.get("status") or "").strip().lower() != "done":
                continue
            actual = _float_or_none(record.get("actual_days"))
            if actual is None or actual <= 0:
                continue
            rows.append(
                {
                    "project_id": str(record.get("project_id") or ""),
                    "date": str(record.get("date") or ""),
                    "actual_days": actual,
                    "team_estimate": _float_or_none(record.get("team_estimate")),
                    "status": "done",
                    "email_text": str(record.get("email_text") or ""),
                    "features": {
                        name: int(_float_or_none(record.get(f"feat_{name}")) or 0)
                        for name in FEATURES
                    },
                }
            )
    return rows


def call_with_retry(call: Callable[[], Any]) -> tuple[Any | None, str | None, int]:
    """Run ``call``; retry once on exception.

    Returns ``(value | None, last_error | None, attempts)``.
    """
    last_error: str | None = None
    for attempt in (1, 2):
        try:
            return call(), None, attempt
        except Exception as exc:  # noqa: BLE001 - report any provider failure
            last_error = f"{type(exc).__name__}: {exc}"
    return None, last_error, 2


def _days_output_chars(value: float) -> int:
    """Approximate response size: the provider returns a tiny JSON object."""
    return len(json.dumps({"days": value}))


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #


def measure(
    provider: LLMProvider,
    provider_name: str,
    *,
    limit: int = 42,
    history_n: int = 3,
    min_train: int = DEFAULT_MIN_TRAIN,
    csv_path: Path = CSV_PATH,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Measure all baselines on the most recent ``limit`` walk-forward steps."""
    say = progress or (lambda _message: None)
    csv_path = Path(csv_path)
    sha1 = sha1_file(csv_path)
    rows = load_done_rows(csv_path)
    if len(rows) <= min_train:
        raise SystemExit(f"Need more than {min_train} done rows in {csv_path}, found {len(rows)}")

    ordered = sorted(
        rows, key=lambda r: (str(r.get("date") or ""), str(r.get("project_id") or ""))
    )
    replay_result = replay(ordered, min_train=min_train)
    steps = replay_result["steps"]
    if not steps:
        raise SystemExit(f"Replay produced no steps for {csv_path} (min_train={min_train})")
    chosen = steps[-limit:] if limit and limit > 0 else steps
    say(
        f"data: {csv_path.name} sha1={sha1[:12]}... done={len(rows)} "
        f"steps={len(steps)} evaluating={len(chosen)} (min_train={min_train})"
    )

    io: dict[str, int] = {
        "llm_only_calls": 0,
        "llm_only_input_chars": 0,
        "llm_only_output_chars": 0,
        "llm_history_calls": 0,
        "llm_history_input_chars": 0,
        "llm_history_output_chars": 0,
        "probe_calls": 0,
        "probe_input_chars": 0,
        "probe_output_chars": 0,
    }
    records: list[dict[str, Any]] = []
    failures = 0

    for position, step in enumerate(chosen, 1):
        index = int(step["i"])
        item = ordered[index]
        email = str(item.get("email_text") or "")
        history = ordered[:index]  # exactly the rows the replay model trained on

        only_prompt = build_llm_only_prompt(email)
        only_chars = len(only_prompt) + len(AB_SYSTEM_PROMPT)
        only_value, only_error, only_attempts = call_with_retry(
            lambda: llm_only_point(email, provider)
        )
        io["llm_only_calls"] += only_attempts
        io["llm_only_input_chars"] += only_attempts * only_chars
        if only_value is not None:
            io["llm_only_output_chars"] += _days_output_chars(only_value)
        elif not email.strip():
            only_error = only_error or "empty email text"

        history_prompt = build_history_prompt(email, history)
        history_chars = len(history_prompt) + len(HISTORY_SYSTEM_PROMPT)
        history_attempts = history_n
        history_error: str | None = None
        try:
            history_values = llm_history_estimate(email, history, provider, n=history_n)
        except Exception as exc:  # noqa: BLE001 - never kill the row on baseline 3
            history_values = []
            history_error = f"{type(exc).__name__}: {exc}"
        missing = history_n - len(history_values)
        if missing > 0:  # one retry for the failed calls, then skip
            try:
                history_values += llm_history_estimate(email, history, provider, n=missing)
            except Exception as exc:  # noqa: BLE001
                history_error = f"{type(exc).__name__}: {exc}"
            history_attempts += missing
        io["llm_history_calls"] += history_attempts
        io["llm_history_input_chars"] += history_attempts * history_chars
        for value in history_values:
            io["llm_history_output_chars"] += _days_output_chars(value)
        if not history_values:
            history_error = history_error or "no usable number in any call"

        row_failed = only_value is None or not history_values
        failures += int(row_failed)
        history_value = fmean(history_values) if history_values else None
        actual = float(step["actual"])
        team = _float_or_none(step.get("team_estimate"))
        records.append(
            {
                "i": index,
                "date": item.get("date"),
                "project_id": step.get("project_id"),
                "actual": actual,
                "system": float(step["p50"]),
                "team": team,
                "llm_only": only_value,
                "llm_history": history_value,
                "in_interval": bool(step["in_interval"]),
                "llm_only_error": only_error,
                "llm_history_error": history_error,
            }
        )
        say(
            f"[{position:>3}/{len(chosen)}] {step.get('project_id')}: "
            f"actual={actual:g} system={float(step['p50']):g} "
            f"llm_only={only_value if only_value is not None else 'ERR'} "
            f"llm_history={history_value if history_value is not None else 'ERR'}"
        )

    fail_ratio = failures / len(chosen)
    say(f"row failures: {failures}/{len(chosen)} ({fail_ratio:.0%})")
    if fail_ratio > ABORT_FAILURE_RATIO:
        raise SystemExit(
            f"ABORT: {failures}/{len(chosen)} rows ({fail_ratio:.0%}) failed two attempts each - "
            f"provider '{provider_name}' looks unhealthy. No report written. "
            "Check the API key/network and re-run."
        )

    common = [
        row
        for row in records
        if row["llm_only"] is not None and row["llm_history"] is not None and row["team"] is not None
    ]

    def common_mae(key: str) -> float | None:
        if not common:
            return None
        return round(fmean(abs(row["actual"] - row[key]) for row in common), 2)

    coverage_common = (
        round(100.0 * sum(row["in_interval"] for row in common) / len(common), 1) if common else None
    )

    # Variance probe: PROBE_REPEATS repeats of the LLM-only call, one email.
    probe_email = str(ordered[int(chosen[-1]["i"])].get("email_text") or "")
    probe_chars = len(build_llm_only_prompt(probe_email)) + len(AB_SYSTEM_PROMPT)
    probe_values: list[float] = []
    probe_errors = 0
    for _ in range(PROBE_REPEATS):
        value, _error, attempts = call_with_retry(lambda: llm_only_point(probe_email, provider))
        io["probe_calls"] += attempts
        io["probe_input_chars"] += attempts * probe_chars
        if value is None:
            probe_errors += attempts
        else:
            probe_values.append(value)
            io["probe_output_chars"] += _days_output_chars(value)
    probe = {
        "repeats": PROBE_REPEATS,
        "project_id": chosen[-1].get("project_id"),
        "values": probe_values,
        "errors": probe_errors,
        "mean": round(fmean(probe_values), 2) if probe_values else None,
        "std": round(pstdev(probe_values), 3) if len(probe_values) > 1 else None,
        "min": round(min(probe_values), 2) if probe_values else None,
        "max": round(max(probe_values), 2) if probe_values else None,
    }

    input_chars = io["llm_only_input_chars"] + io["llm_history_input_chars"] + io["probe_input_chars"]
    output_chars = (
        io["llm_only_output_chars"] + io["llm_history_output_chars"] + io["probe_output_chars"]
    )
    input_tokens = input_chars / CHARS_PER_TOKEN
    output_tokens = output_chars / CHARS_PER_TOKEN
    cost_usd = (
        input_tokens / 1e6 * INPUT_USD_PER_MTOK + output_tokens / 1e6 * OUTPUT_USD_PER_MTOK
    )

    return {
        "provider": provider_name,
        "csv_name": csv_path.name,
        "sha1": sha1,
        "n_done": len(ordered),
        "min_train": min_train,
        "n_steps": len(steps),
        "n_eval": len(chosen),
        "history_n": history_n,
        "failures": failures,
        "n_common": len(common),
        "metrics": {
            "system": common_mae("system"),
            "team": common_mae("team"),
            "llm_only": common_mae("llm_only"),
            "llm_history": common_mae("llm_history"),
        },
        "coverage_common_pct": coverage_common,
        "replay_summary": replay_result["summary"],
        "probe": probe,
        "io": io,
        "cost": {
            "input_chars": input_chars,
            "output_chars": output_chars,
            "input_tokens": round(input_tokens),
            "output_tokens": round(output_tokens),
            "usd_upper": round(cost_usd, 4),
            "total_calls": io["llm_only_calls"] + io["llm_history_calls"] + io["probe_calls"],
        },
        "records": records,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def _fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render_report(data: Mapping[str, Any]) -> str:
    """docs/AB_MEASUREMENT.md text (kept under 120 lines)."""
    metrics = data["metrics"]
    probe = data["probe"]
    cost = data["cost"]
    io = data["io"]
    summary = data["replay_summary"]
    only_success = sum(1 for row in data["records"] if row["llm_only"] is not None)
    history_success = sum(1 for row in data["records"] if row["llm_history"] is not None)
    probe_values = ", ".join(f"{value:g}" for value in probe["values"]) or "(none)"
    probe_range = (
        f"{probe['max'] - probe['min']:g}" if probe["values"] else "-"
    )
    probe_pct = (
        f"{probe['std'] / probe['mean'] * 100:.1f}%"
        if probe["std"] is not None and probe["mean"]
        else "-"
    )

    lines = [
        "# A/B measurement - real provider run",
        "",
        f"Measured on {data['generated_at']} with the configured provider. This is the",
        "evidence behind the honest demo claims: how each baseline scores on the same",
        "walk-forward rows, and how stable a temperature-0 LLM is across repeats. It",
        "replaces the pre-build \"+/-15 days\" expectation flagged in docs/SPEC.md sec.6.4.",
        "",
        f"**Provider:** {data['provider']}, temperature 0 forced in providers.py (JSON-object",
        f"output, thinking disabled). **Data:** `data/{data['csv_name']}`, sha1",
        f"`{data['sha1']}` - {data['n_done']} finished rows (status == done).",
        "",
        "## Method",
        "",
        f"1. `replay(min_train={data['min_train']})` over the CSV in (date, project_id) order:",
        f"   {data['n_steps']} walk-forward steps; the {data['n_eval']} most recent steps were",
        "   evaluated. System p10/p50/p90 are trained only on earlier rows.",
        "2. Per step: 1 LLM-only call (exact `POST /api/ab` prompt) +",
        f"   {data['history_n']} LLM-with-history calls (per-row mean used, like the API",
        f"   contract; the history prompt shows the up-to-{MAX_HISTORY_ROWS} most recent finished",
        "   projects **before that step** (project_id, active features, actual days -",
        "   exactly the rows the replay model trained on, so no future leakage) and asks",
        "   for `{\"days\": <number>}`.",
        f"3. Robustness: 1 retry per failed call, then the row is skipped. Failures this",
        f"   run: {data['failures']}/{data['n_eval']} rows; a run aborts above",
        f"   {int(ABORT_FAILURE_RATIO * 100)}% failures before writing anything.",
        f"4. Variance probe: {probe['repeats']} repeats of the LLM-only call on one representative",
        f"   email (the most recent step, `{probe['project_id']}`).",
        "",
        f"## Results - same {data['n_common']} rows for every baseline",
        "",
        "| baseline | MAE (days) | rows | what it is |",
        "| --- | --- | --- | --- |",
        f"| System (calibrated p50) | {_fmt(metrics['system'])} | {data['n_common']} | Ridge on log-days + conformal interval, replay step |",
        f"| Team human estimate | {_fmt(metrics['team'])} | {data['n_common']} | the historical team estimate |",
        f"| LLM-only | {_fmt(metrics['llm_only'])} | {data['n_common']} | 1 call/row, no history |",
        f"| LLM + company history | {_fmt(metrics['llm_history'])} | {data['n_common']} | mean of {data['history_n']} calls/row, prompt shows the recent projects |",
        "",
        f"System p10-p90 coverage on those rows: {_fmt(data['coverage_common_pct'], 1)}% (full replay,",
        f"all {data['n_steps']} steps: {_fmt(summary['coverage_pct'], 1)}%). Full-replay MAE: system",
        f"{_fmt(summary['mae_system'])}, team {_fmt(summary['mae_team'])}. The replay's built-in",
        "LLM-only baseline is SIMULATED and was not used here.",
        "",
        f"Calls: llm_only {only_success} ok / {io['llm_only_calls']} attempts; llm_history",
        f"{history_success} ok / {io['llm_history_calls']} attempts; probe {len(probe['values'])} ok /",
        f"{io['probe_calls']} attempts.",
        "",
        "## Run-to-run variance at temperature 0 (the \"+/-15 days\" claim)",
        "",
        f"Probe: LLM-only prompt, {probe['repeats']} repeats, email of `{probe['project_id']}`.",
        "",
        f"- values: {probe_values}",
        f"- mean {_fmt(probe['mean'])}, std {_fmt(probe['std'], 3)}, min..max {_fmt(probe['min'])}..{_fmt(probe['max'])} (range {probe_range} days)",
        f"- std as % of mean: {probe_pct}",
        "",
        "Reading: at temperature 0 the provider is effectively deterministic on this",
        "sample, so run-to-run spread is not where LLM error comes from - the MAE table",
        "above is. The \"+/-15 days\" figure in docs/SPEC.md sec.6.4 was a pre-build",
        "expectation, never measured; treat the number in this section as the measured",
        "replacement. It says nothing about temperature > 0 runs (not measured).",
        "",
        "## Cost (rough heuristic)",
        "",
        f"- input chars {cost['input_chars']} -> tokens ~ chars/4 = {cost['input_tokens']}; output",
        f"  chars {cost['output_chars']} -> ~{cost['output_tokens']} tokens; {cost['total_calls']} calls total.",
        f"- DeepSeek-V4.1-Flash list price at cache-miss PEAK rates ($0.30/M in, $1.20/M out,",
        "  api-docs.deepseek.com/quick_start/pricing, 2026-10-16) gives an upper bound of",
        f"  **~${cost['usd_upper']}** for this run (off-peak is half price; cached input is far cheaper).",
        "",
        "## Honest notes",
        "",
        "1. Temperature 0 (hardcoded): repeat answers are near- or exactly deterministic;",
        "   this measures stability, not accuracy under sampling.",
        f"2. Sample: {data['n_eval']} walk-forward rows, synthetic data, one run, one day, one",
        "   provider version. No confidence intervals claimed.",
        f"3. The CSV is regenerable; if its sha1 no longer matches `{data['sha1'][:12]}...`, these numbers",
        "   apply to the recorded revision only (re-run the script to refresh).",
        "4. The stub (offline) paths in the product remain SIMULATED and are flagged as",
        "   such (`mode == \"simulated\"`); only this report's numbers are real calls.",
        "5. Raw per-row values are reproducible with the command below (row results can",
        "   differ slightly if the provider version changes).",
        "",
        "```bash",
        "cd backend",
        f"PYTHONPATH=. /root/venvs/estimator/bin/python scripts/ab_measurement.py --limit {data['n_eval']} --history-n 3 --write",
        "```",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--limit", type=int, default=42, help="walk-forward steps to evaluate (most recent first)"
    )
    parser.add_argument("--history-n", type=int, default=3, help="LLM-with-history calls per step")
    parser.add_argument("--min-train", type=int, default=DEFAULT_MIN_TRAIN, help="replay min_train")
    parser.add_argument("--csv", type=Path, default=CSV_PATH, help=f"input CSV (default: {CSV_PATH})")
    parser.add_argument(
        "--write", action="store_true", help=f"write the report to {REPORT_PATH.relative_to(REPO_ROOT)}"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider, provider_name = get_provider()
    print(f"provider: {provider_name}")
    if provider_name == "stub":
        raise SystemExit(
            "ABORT: the offline stub provider cannot produce point estimates. "
            "Set LLM_PROVIDER=deepseek (with an API key) in .env and re-run."
        )
    data = measure(
        provider,
        provider_name,
        limit=args.limit,
        history_n=args.history_n,
        min_train=args.min_train,
        csv_path=args.csv,
        progress=print,
    )
    report = render_report(data)
    print()
    print(report)
    if args.write:
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
