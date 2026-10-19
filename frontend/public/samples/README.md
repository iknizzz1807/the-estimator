# Sample CSV files

Ready-to-import example files for The Estimator. Download one and import it
as-is — no preparation needed — or open it, edit a few values, and re-import
to watch the model react.

The app serves these files at `/samples/<filename>`, for example:
`/samples/sample_01_tiny.csv`.

## Files

| File | Rows | Purpose |
| --- | --- | --- |
| `sample_01_tiny.csv` | 5 | Smallest possible file; all rows `done`, easy to edit `actual_days` by hand. |
| `sample_02_small.csv` | 25 | Small mixed set (~90% `done`). |
| `sample_03_medium.csv` | 100 | Medium mixed set (~85% `done`). |
| `sample_04_large.csv` | 500 | Large file for big-file / performance testing. |
| `sample_05_edge_cases.csv` | 24 | Mixed accepted styles plus 4 intentionally invalid rows that demonstrate the skip report. |

Files `sample_01` through `sample_04` import cleanly: `imported` equals the row
count and `skipped` is 0. `sample_05_edge_cases.csv` intentionally reports
4 skipped rows.

## Import rules

- `project_id` — unique within the file and not already in the database.
- `date` — `YYYY-MM-DD`.
- `status` — one of `done`, `in_progress`, `pending`.
- `done` rows must have a numeric `actual_days` greater than 0.
- Non-done rows must leave `actual_days` empty.
- `team_estimate` — optional number; keep it plausible (within ±40% of
  `actual_days` for done rows).
- `feat_*` columns — `0` or `1`.
- `is_synthetic` — `0` for real (non-generated) history.
- `email_text` — 1–2 sentences describing the project (English or Vietnamese).

## Tips

- Column order does not matter; columns are matched by name.
- Extra columns are ignored — only the canonical columns are read.
- Re-importing the same `project_id` is skipped as a duplicate. Change the id,
  or use "Reset demo data" first.
- Keep files UTF-8 encoded.
- Edit `actual_days` and re-import to see the model react.
