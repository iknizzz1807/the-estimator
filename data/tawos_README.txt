TAWOS validation subset - source, license, extraction notes
-----------------------------------------------------------
Source: TAWOS v1.1 (Tawosi et al., MSR 2022), official record
https://doi.org/10.5522/04/21308124 (UCL RDR, TAWOS.sql.zip, 637.6 MB MySQL dump).
License: Apache-2.0 (figshare record; TAWOS README terms of use request research
use; attribution kept here). Mirror used instead of the dump (dump download was
~75 KB/s on this device): https://github.com/barkhahbpp/tawosdataset , per-project
CSVs I spot-checked against the official Issue schema (Title, Description,
Story_Point, Type columns).
Column mapping: story_id = "<csv stem>:<1-based source row>"; project_id = csv
stem (e.g. 28datamanagement); description = Title + " " + Description (whitespace
collapsed, truncated to 2000 chars); story_points = Story_Point.
Filter: 0.5 <= Story_Point <= 100 (drops 699 sub-0.5 entries and 141 entries up
to 26,710,114, flagged as noise) + non-empty text; deterministic sample: per
project sort by (Creation_Date, Title, Description), keep all if <= 150 rows else
150 evenly spaced rows. Final: 5,850 rows, 39 projects (150 each), 3.3 MB.
Details/results: docs/TAWOS_VALIDATION.md; runner: backend/scripts/tawos_validation.py.
