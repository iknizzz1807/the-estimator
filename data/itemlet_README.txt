Itemlet project-level validation subset — source, license, extraction notes
---------------------------------------------------------------------------
Source: "Itemlet Dataset: A Multi-project, Multi-domain, and Feature-engineered
Dataset for Empirical Software Engineering" — Zenodo record 19411554,
https://doi.org/10.5281/zenodo.19411554 . 727,282 Jira issues from 204
open-source projects across 19 domains, with absolute effort
("Total Time Logged (hours)") and 108 engineered columns.
License: Creative Commons Attribution 4.0 International (CC-BY-4.0).
Attribution: the Itemlet dataset authors (Zenodo 10.5281/zenodo.19411554).
This derived subset is redistributed under the same CC-BY-4.0 license.

Files downloaded via the Zenodo API on 2026-10-16 (all MD5 verified against
the record's checksums; cached under /root/itemlet_cache, not committed):
- project_summary.csv      18,832 B    md5 f8f4cf3ffd64c8cd663db3c0d8a07f05
- project_domain.csv       16,382 B    md5 3a49d0835731aab84f18ceca108ad0ae
- data_dictionary.csv      16,010 B    md5 e62d3884e7deca03a106b86469ea9d48
- itemlet_dataset.parquet 107,856,639 B md5 e80d4f6b521d5ace92c039fb49325480
- extraction_config.json    1,655 B    md5 8c6502de0ab9aa41c5410f75a1085709
(itemlet_dataset.csv, 438,479,440 B, md5 ea0426869723cd4792b37e928019bb81,
was NOT downloaded: the parquet carries the same rows and was verified.)

Derived subset: data/itemlet_projects.csv — 204 rows x 50 cols, ~65 KB,
md5 c3a5e24337dea991905de813fa70bd4a. Regenerate deterministically with
`cd backend && PYTHONPATH=. /root/venvs/estimator/bin/python
scripts/itemlet_validation.py --build` (requires pyarrow; rebuild is
md5-identical).

How it was built (backend/scripts/itemlet_validation.py --build):
- target_hours = sum("Total Time Logged (hours)") per project_key over all
  727,282 parquet issues; target_person_days = target_hours / 8 (conversion
  label only, not a claim). 90/204 projects have zero logged time (target 0;
  kept in the CSV, skipped by the validation — no absolute-effort target).
- Issue aggregates (11 parquet columns read): issue-type shares (Bug, Story),
  Done-status share, distinct assignee accounts, mean comments, mean Total
  Days, technical-lexicon share, High/Highest-priority share, and
  n_issues_logged / logging_coverage = n_issues_logged / issue_count.
- Project descriptors merged from project_summary.csv (issue_count,
  resolved_count, story-point coverage/median, cycle time, sprint count) and
  project_domain.csv (domain_notes). issue_count cross-check summary vs
  parquet: 0 mismatches.
- 15 features are documented in docs/ITEMLET_VALIDATION.md; heavy-tailed
  durations/counts are log1p-transformed. Deterministic imputation with the
  overall median for 1 null cycle time, 18 null date spans, 1 null
  mean_total_days; stub_* shares filled with 0 when no summary sample exists.
- stub_* columns: the product's offline StubProvider run on a deterministic
  sample of up to 40 issue summaries per project (sorted by issue_key, evenly
  spaced; 8,160 summaries total). Diagnostic only — no signal (see report).
- Column notes: median_hours_per_issue is the median over ALL issues (0h for
  most projects — logging is sparse); n_issues_logged counts issues with > 0
  logged hours.

Known data caveats (details in docs/ITEMLET_VALIDATION.md): only 6.5% of all
issues have any logged time; 90/204 projects have none; logging coverage of
the 114 usable projects is median 3.2%. Total logged hours is therefore a
noisy lower-bound proxy for true project effort. v1.0 data dictionary notes
"Completion Time (hours)" is identical to "Cycle Time (hours)" due to a
derivation error (neither is used as a feature).
