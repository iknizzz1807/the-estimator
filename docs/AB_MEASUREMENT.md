# A/B measurement - real provider run

Measured on 2026-10-16 19:36 UTC with the configured provider. This is the
evidence behind the honest demo claims: how each baseline scores on the same
walk-forward rows, and how stable a temperature-0 LLM is across repeats. It
replaces the pre-build "+/-15 days" expectation flagged in docs/SPEC.md sec.6.4.

**Provider:** deepseek, temperature 0 forced in providers.py (JSON-object
output, thinking disabled). **Data:** `data/synthetic_history.csv`, sha1
`e9e0a0969febbbdaa2ff84b6ff7b649bc2bbf5be` - 52 finished rows (status == done).

## Method

1. `replay(min_train=10)` over the CSV in (date, project_id) order:
   42 walk-forward steps; the 42 most recent steps were
   evaluated. System p10/p50/p90 are trained only on earlier rows.
2. Per step: 1 LLM-only call (exact `POST /api/ab` prompt) +
   3 LLM-with-history calls (per-row mean used, like the API
   contract; the history prompt shows the up-to-15 most recent finished
   projects **before that step** (project_id, active features, actual days -
   exactly the rows the replay model trained on, so no future leakage) and asks
   for `{"days": <number>}`.
3. Robustness: 1 retry per failed call, then the row is skipped. Failures this
   run: 0/42 rows; a run aborts above
   30% failures before writing anything.
4. Variance probe: 5 repeats of the LLM-only call on one representative
   email (the most recent step, `P052`).

## Results - same 42 rows for every baseline

| baseline | MAE (days) | rows | what it is |
| --- | --- | --- | --- |
| System (calibrated p50) | 23.50 | 42 | Ridge on log-days + conformal interval, replay step |
| Team human estimate | 30.40 | 42 | the historical team estimate |
| LLM-only | 242.98 | 42 | 1 call/row, no history |
| LLM + company history | 35.96 | 42 | mean of 3 calls/row, prompt shows the recent projects |

System p10-p90 coverage on those rows: 83.3% (full replay,
all 42 steps: 83.3%). Full-replay MAE: system
23.50, team 30.40. The replay's built-in
LLM-only baseline is SIMULATED and was not used here.

Calls: llm_only 42 ok / 42 attempts; llm_history
42 ok / 126 attempts; probe 5 ok /
5 attempts.

## Run-to-run variance at temperature 0 (the "+/-15 days" claim)

Probe: LLM-only prompt, 5 repeats, email of `P052`.

- values: 360, 360, 360, 360, 360
- mean 360.00, std 0.000, min..max 360.00..360.00 (range 0 days)
- std as % of mean: 0.0%

Reading: at temperature 0 the provider is effectively deterministic on this
sample, so run-to-run spread is not where LLM error comes from - the MAE table
above is. The "+/-15 days" figure in docs/SPEC.md sec.6.4 was a pre-build
expectation, never measured; treat the number in this section as the measured
replacement. It says nothing about temperature > 0 runs (not measured).

## Cost (rough heuristic)

- input chars 400559 -> tokens ~ chars/4 = 100140; output
  chars 2498 -> ~624 tokens; 173 calls total.
- DeepSeek-V4.1-Flash list price at cache-miss PEAK rates ($0.30/M in, $1.20/M out,
  api-docs.deepseek.com/quick_start/pricing, 2026-10-16) gives an upper bound of
  **~$0.0308** for this run (off-peak is half price; cached input is far cheaper).

## Honest notes

1. Temperature 0 (hardcoded): repeat answers are near- or exactly deterministic;
   this measures stability, not accuracy under sampling.
2. Sample: 42 walk-forward rows, synthetic data, one run, one day, one
   provider version. No confidence intervals claimed.
3. The CSV is regenerable; if its sha1 no longer matches `e9e0a0969feb...`, these numbers
   apply to the recorded revision only (re-run the script to refresh).
4. The stub (offline) paths in the product remain SIMULATED and are flagged as
   such (`mode == "simulated"`); only this report's numbers are real calls.
5. Raw per-row values are reproducible with the command below (row results can
   differ slightly if the provider version changes).

```bash
cd backend
PYTHONPATH=. /root/venvs/estimator/bin/python scripts/ab_measurement.py --limit 42 --history-n 3 --write
```
