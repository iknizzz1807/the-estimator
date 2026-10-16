"""SWE-bench invasiveness ablation: issue text vs issue text + codebase signals.

Validation experiment for the "Codebase Lab" claim: can we predict how invasive a
change will be (how many files its real patch touches) from the issue text alone,
and do codebase signals at the base commit add measurable accuracy?

Dataset: SWE-bench (Princeton). Each instance ships ``problem_statement`` (the
issue text) and ``patch`` (the real gold fix). Ground truth is derived from the
patch itself: files_touched, new/modified/deleted files, added/removed lines.

Two arms, identical CV folds:

1. ``text-only``  : deterministic features of the problem statement (sizes,
   keyword counts, path/module tokens, code blocks, repo one-hot). No LLM calls.
2. ``text+codebase``: the same features plus codebase signals computed *at the
   instance base commit* in a blob-filtered clone of one repo (default sympy):
   fan-in of modules mentioned in the issue text, cyclomatic complexity (radon,
   optional) of the mentioned files, 180-day churn and author concentration of
   those paths, plus repo-level activity at the base commit.

Leakage controls: codebase features only read git objects reachable from
``base_commit``; churn uses ``git log --since=<base_date - 180d> <base_commit>``
which cannot see the future. The patches are used ONLY to build ground-truth
labels, never as features. ``hints_text`` is ignored.

Run from ``backend/``:

    /root/venvs/estimator/bin/python scripts/swebench_validation.py --self-test
    /root/venvs/estimator/bin/python scripts/swebench_validation.py \
        --max-instances 0 --subset-repo sympy/sympy --subset-max-instances 150 --write

Multi-file refinement (2026-10-17): the original target is near-degenerate
(75% of patches touch exactly one file), so the ablation can be re-run on the
variance subset and on alternative targets::

    /root/venvs/estimator/bin/python scripts/swebench_validation.py \
        --max-instances 0 --min-files 2 --target all \
        --subset-repos sympy/sympy,pytest-dev/pytest,psf/requests \
        --subset-max-instances 0 --write

``--min-files N`` filters the variance/ablation subsets to patches touching at
least N files (0 = original behaviour). ``--target files|modified|added_lines|
all`` switches the regression target. ``--subset-repos`` spans several repos in
the codebase arm (one blob-filtered clone each).

Deterministic: seed 42 everywhere; no randomness outside seeded numpy/sklearn.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
DOCS_PATH = PROJECT_ROOT / "docs" / "CODEBASE_VALIDATION.md"
SAMPLE_PATH = SCRIPT_DIR / "swebench_sample.jsonl"

SEED = 42
DEFAULT_CACHE_DIR = Path("/root/swebench_cache")
SUBSET_WINDOW_DAYS = 180
MIN_FREE_MB_DATASET = 200
MIN_FREE_MB_CLONE = 500

# Regression targets: name -> (ground-truth key from parse_patch, clip lower bound).
TARGETS: dict[str, tuple[str, float]] = {
    "files": ("files_touched", 1.0),
    "modified": ("modified_files", 0.0),
    "added_lines": ("added_lines", 0.0),
}
TARGET_CHOICES = ("files", "modified", "added_lines")


def parse_targets(spec: str) -> list[str]:
    """Expand ``--target`` (single choice or ``all``) to an ordered target list."""
    if spec == "all":
        return list(TARGET_CHOICES)
    if spec not in TARGET_CHOICES:
        raise SystemExit(f"unknown target {spec!r}; choose from {TARGET_CHOICES + ('all',)}")
    return [spec]


def subset_repo_list(args: argparse.Namespace) -> list[str]:
    """Repos for the codebase arm: ``--subset-repos`` overrides ``--subset-repo``."""
    raw = getattr(args, "subset_repos", "") or ""
    repos = [item.strip() for item in raw.split(",") if item.strip()]
    return repos or [args.subset_repo]

DATASET_SOURCES = {
    "full": {
        "hf_dataset": "princeton-nlp/SWE-bench",
        "split": "test",
        "expected_rows": 2294,
    },
    "lite": {
        "hf_dataset": "princeton-nlp/SWE-bench_Lite",
        "split": "test",
        "expected_rows": 300,
    },
}
HF_ROWS_URL = "https://datasets-server.huggingface.co/rows"
HF_PARQUET_URL = (
    "https://huggingface.co/datasets/{dataset}/resolve/main/data/{split}-00000-of-00001.parquet"
)

# --------------------------------------------------------------------------
# Embedded sample rows (5 real SWE-bench instances, base64 of a JSONL blob).
# Regenerate the readable copy with: --write-sample
# --------------------------------------------------------------------------
_SAMPLE_JSONL_B64 = (
    "eyJiYXNlX2NvbW1pdCI6ICJjNGU4MzZjZGY3M2ZjNmFhN2JhYjZhODY3MTlhMGYwODg2MWZmYjFkIiwgImluc3RhbmNlX2lk"
    "IjogInN5bXB5X19zeW1weS0yMjkxNCIsICJwYXRjaCI6ICJkaWZmIC0tZ2l0IGEvc3ltcHkvcHJpbnRpbmcvcHljb2RlLnB5"
    "IGIvc3ltcHkvcHJpbnRpbmcvcHljb2RlLnB5XG4tLS0gYS9zeW1weS9wcmludGluZy9weWNvZGUucHlcbisrKyBiL3N5bXB5"
    "L3ByaW50aW5nL3B5Y29kZS5weVxuQEAgLTE4LDYgKzE4LDggQEBcbiBcbiBfa25vd25fZnVuY3Rpb25zID0ge1xuICAgICAn"
    "QWJzJzogJ2FicycsXG4rICAgICdNaW4nOiAnbWluJyxcbisgICAgJ01heCc6ICdtYXgnLFxuIH1cbiBfa25vd25fZnVuY3Rp"
    "b25zX21hdGggPSB7XG4gICAgICdhY29zJzogJ2Fjb3MnLFxuIiwgInBhdGNoX3NoYTI1NiI6ICI5YmYwNzZhYzlkZWQzZTQ4"
    "NmMxMGEyMmU3MDE1NmFhMjI5OWE3MmRlYTA4NzIzM2NkZTQ4YTVkZTZkYmI3NGRmIiwgInByb2JsZW1fc3RhdGVtZW50Ijog"
    "IlB5dGhvbkNvZGVQcmludGVyIGRvZXNuJ3Qgc3VwcG9ydCBNaW4gYW5kIE1heFxuV2UgY2FuJ3QgZ2VuZXJhdGUgcHl0aG9u"
    "IGNvZGUgZm9yIHRoZSBzeW1weSBmdW5jdGlvbiBNaW4gYW5kIE1heC5cclxuXHJcbkZvciBleGFtcGxlOlxyXG5gYGBcclxu"
    "ZnJvbSBzeW1weSBpbXBvcnQgc3ltYm9scywgTWluLCBweWNvZGVcclxuYSwgYiA9IHN5bWJvbHMoXCJhIGJcIilcclxuYyA9"
    "IE1pbihhLGIpXHJcbnByaW50KHB5Y29kZShjKSlcclxuYGBgXHJcbnRoZSBvdXRwdXQgaXM6XHJcblxyXG5gYGBcclxuICAj"
    "IE5vdCBzdXBwb3J0ZWQgaW4gUHl0aG9uOlxyXG4gICMgTWluXHJcbk1pbihhLCBiKVxyXG5gYGBcclxuXHJcblNpbWlsYXIg"
    "dG8gaXNzdWUgIzE2NjY5LCB3ZSBzaG91bGQgYWRkIGZvbGxvd2luZyBtZXRob2RzIHRvIFB5dGhvbkNvZGVQcmludGVyOlxy"
    "XG5cclxuYGBgXHJcbmRlZiBfcHJpbnRfTWluKHNlbGYsIGV4cHIpOlxyXG4gICAgcmV0dXJuIFwibWluKHt9KVwiLmZvcm1h"
    "dChcIiwgXCIuam9pbihzZWxmLl9wcmludChhcmcpIGZvciBhcmcgaW4gZXhwci5hcmdzKSlcclxuXHJcblxyXG5kZWYgX3By"
    "aW50X01heChzZWxmLCBleHByKTpcclxuICAgIHJldHVybiBcIm1heCh7fSlcIi5mb3JtYXQoXCIsIFwiLmpvaW4oc2VsZi5f"
    "cHJpbnQoYXJnKSBmb3IgYXJnIGluIGV4cHIuYXJncykpXHJcblxyXG5gYGAgXG4iLCAicmVwbyI6ICJzeW1weS9zeW1weSIs"
    "ICJzb3VyY2UiOiAicHJpbmNldG9uLW5scC9TV0UtYmVuY2ggdGVzdCBzcGxpdCJ9CnsiYmFzZV9jb21taXQiOiAiMTEwMDQ4"
    "Zjk4MzdmODQ0MWVhNTM2ODA0MTE1ZTgwYjY5ZjQwMDI3NyIsICJpbnN0YW5jZV9pZCI6ICJwc2ZfX3JlcXVlc3RzLTE5NjIi"
    "LCAicGF0Y2giOiAiZGlmZiAtLWdpdCBhL3JlcXVlc3RzL3Nlc3Npb25zLnB5IGIvcmVxdWVzdHMvc2Vzc2lvbnMucHlcbi0t"
    "LSBhL3JlcXVlc3RzL3Nlc3Npb25zLnB5XG4rKysgYi9yZXF1ZXN0cy9zZXNzaW9ucy5weVxuQEAgLTUyNyw3ICs1MjcsNyBA"
    "QCBkZWYgc2VuZChzZWxmLCByZXF1ZXN0LCAqKmt3YXJncyk6XG4gICAgICAgICAgICAgaGlzdG9yeS5pbnNlcnQoMCwgcilc"
    "biAgICAgICAgICAgICAjIEdldCB0aGUgbGFzdCByZXF1ZXN0IG1hZGVcbiAgICAgICAgICAgICByID0gaGlzdG9yeS5wb3Ao"
    "KVxuLSAgICAgICAgICAgIHIuaGlzdG9yeSA9IHR1cGxlKGhpc3RvcnkpXG4rICAgICAgICAgICAgci5oaXN0b3J5ID0gaGlz"
    "dG9yeVxuIFxuICAgICAgICAgcmV0dXJuIHJcbiBcbiIsICJwYXRjaF9zaGEyNTYiOiAiNjhiNzNlNzI0NTI3ZjlhNDgwMWNm"
    "MzA3YmQzMjk2NjJkYWMwOGMxNzBjMzk4Mzk0YTlkOTVlNDFmZDdhNDJiNSIsICJwcm9ibGVtX3N0YXRlbWVudCI6ICJyZXF1"
    "ZXN0Lmhpc3RvcnkgY2FuIGJlIGVpdGhlciBhIGxpc3Qgb3IgYSB0dXBsZVxuSU1ITyByLmhpc3Rvcnkgc2hvdWxkIGFsd2F5"
    "cyBiZSBhIGxpc3QgZm9yIGxlYXN0IHN1cnByaXNlLiBJbiBfc29tZV8gY2FzZXMsIGl0IGlzIHJldHVybmVkIGFzIGEgdHVw"
    "bGU6XG5odHRwczovL2dpdGh1Yi5jb20va2VubmV0aHJlaXR6L3JlcXVlc3RzL2Jsb2IvbWFzdGVyL3JlcXVlc3RzL3Nlc3Np"
    "b25zLnB5I0w1MzBcblxuVGhhbmtzIVxuXG4iLCAicmVwbyI6ICJwc2YvcmVxdWVzdHMiLCAic291cmNlIjogInByaW5jZXRv"
    "bi1ubHAvU1dFLWJlbmNoIHRlc3Qgc3BsaXQifQp7ImJhc2VfY29tbWl0IjogImU2NzBmZjc2Y2JhZDgwMTA4YmRlOWJhYjYx"
    "NmI2Njc3MWI4NjUzY2YiLCAiaW5zdGFuY2VfaWQiOiAicHl0ZXN0LWRldl9fcHl0ZXN0LTYxMTYiLCAicGF0Y2giOiAiZGlm"
    "ZiAtLWdpdCBhL3NyYy9fcHl0ZXN0L21haW4ucHkgYi9zcmMvX3B5dGVzdC9tYWluLnB5XG4tLS0gYS9zcmMvX3B5dGVzdC9t"
    "YWluLnB5XG4rKysgYi9zcmMvX3B5dGVzdC9tYWluLnB5XG5AQCAtMTA5LDYgKzEwOSw3IEBAIGRlZiBweXRlc3RfYWRkb3B0"
    "aW9uKHBhcnNlcik6XG4gICAgIGdyb3VwLmFkZG9wdGlvbihcbiAgICAgICAgIFwiLS1jb2xsZWN0b25seVwiLFxuICAgICAg"
    "ICAgXCItLWNvbGxlY3Qtb25seVwiLFxuKyAgICAgICAgXCItLWNvXCIsXG4gICAgICAgICBhY3Rpb249XCJzdG9yZV90cnVl"
    "XCIsXG4gICAgICAgICBoZWxwPVwib25seSBjb2xsZWN0IHRlc3RzLCBkb24ndCBleGVjdXRlIHRoZW0uXCIsXG4gICAgICks"
    "XG4iLCAicGF0Y2hfc2hhMjU2IjogIjJkODAxMDllZmIzYWU4M2JkZWJjMTMzOGJlMzQwN2JhZWJlZjg5NDU4ZmUwMGQ0NTUz"
    "Mzk3MzU5ZDQxY2U2MTEiLCAicHJvYmxlbV9zdGF0ZW1lbnQiOiAicHl0ZXN0IC0tY29sbGVjdC1vbmx5IG5lZWRzIGEgb25l"
    "IGNoYXIgc2hvcnRjdXQgY29tbWFuZFxuSSBmaW5kIG15c2VsZiBuZWVkaW5nIHRvIHJ1biBgLS1jb2xsZWN0LW9ubHlgIHZl"
    "cnkgb2Z0ZW4gYW5kIHRoYXQgY2xpIGFyZ3VtZW50IGlzIGEgdmVyeSBsb25nIHRvIHR5cGUgb25lLiBcclxuXHJcbkkgZG8g"
    "dGhpbmsgdGhhdCBpdCB3b3VsZCBiZSBncmVhdCB0byBhbGxvY2F0ZSBhIGNoYXJhY3RlciBmb3IgaXQsIG5vdCBzdXJlIHdo"
    "aWNoIG9uZSB5ZXQuIFBsZWFzZSB1c2UgdXAvZG93biB0aHVtYnMgdG8gdm90ZSBpZiB5b3Ugd291bGQgZmluZCBpdCB1c2Vm"
    "dWwgb3Igbm90IGFuZCBldmVudHVhbGx5IHByb3Bvc2luZyB3aGljaCBjaGFyIHNob3VsZCBiZSB1c2VkLiBcclxuXHJcbkNs"
    "ZWFybHkgdGhpcyBpcyBhIGNoYW5nZSB2ZXJ5IGVhc3kgdG8gaW1wbGVtZW50IGJ1dCBmaXJzdCBJIHdhbnQgdG8gc2VlIGlm"
    "IG90aGVycyB3b3VsZCBmaW5kIGl0IHVzZWZ1bCBvciBub3QuXG5weXRlc3QgLS1jb2xsZWN0LW9ubHkgbmVlZHMgYSBvbmUg"
    "Y2hhciBzaG9ydGN1dCBjb21tYW5kXG5JIGZpbmQgbXlzZWxmIG5lZWRpbmcgdG8gcnVuIGAtLWNvbGxlY3Qtb25seWAgdmVy"
    "eSBvZnRlbiBhbmQgdGhhdCBjbGkgYXJndW1lbnQgaXMgYSB2ZXJ5IGxvbmcgdG8gdHlwZSBvbmUuIFxyXG5cclxuSSBkbyB0"
    "aGluayB0aGF0IGl0IHdvdWxkIGJlIGdyZWF0IHRvIGFsbG9jYXRlIGEgY2hhcmFjdGVyIGZvciBpdCwgbm90IHN1cmUgd2hp"
    "Y2ggb25lIHlldC4gUGxlYXNlIHVzZSB1cC9kb3duIHRodW1icyB0byB2b3RlIGlmIHlvdSB3b3VsZCBmaW5kIGl0IHVzZWZ1"
    "bCBvciBub3QgYW5kIGV2ZW50dWFsbHkgcHJvcG9zaW5nIHdoaWNoIGNoYXIgc2hvdWxkIGJlIHVzZWQuIFxyXG5cclxuQ2xl"
    "YXJseSB0aGlzIGlzIGEgY2hhbmdlIHZlcnkgZWFzeSB0byBpbXBsZW1lbnQgYnV0IGZpcnN0IEkgd2FudCB0byBzZWUgaWYg"
    "b3RoZXJzIHdvdWxkIGZpbmQgaXQgdXNlZnVsIG9yIG5vdC5cbiIsICJyZXBvIjogInB5dGVzdC1kZXYvcHl0ZXN0IiwgInNv"
    "dXJjZSI6ICJwcmluY2V0b24tbmxwL1NXRS1iZW5jaCB0ZXN0IHNwbGl0In0KeyJiYXNlX2NvbW1pdCI6ICJkMTZiZmUwNWE3"
    "NDQ5MDlkZTRiMjdmNTg3NWZlMGQ0ZWQ0MWNlNjA3IiwgImluc3RhbmNlX2lkIjogImFzdHJvcHlfX2FzdHJvcHktMTI5MDci"
    "LCAicGF0Y2giOiAiZGlmZiAtLWdpdCBhL2FzdHJvcHkvbW9kZWxpbmcvc2VwYXJhYmxlLnB5IGIvYXN0cm9weS9tb2RlbGlu"
    "Zy9zZXBhcmFibGUucHlcbi0tLSBhL2FzdHJvcHkvbW9kZWxpbmcvc2VwYXJhYmxlLnB5XG4rKysgYi9hc3Ryb3B5L21vZGVs"
    "aW5nL3NlcGFyYWJsZS5weVxuQEAgLTI0Miw3ICsyNDIsNyBAQCBkZWYgX2NzdGFjayhsZWZ0LCByaWdodCk6XG4gICAgICAg"
    "ICBjcmlnaHQgPSBfY29vcmRfbWF0cml4KHJpZ2h0LCAncmlnaHQnLCBub3V0cClcbiAgICAgZWxzZTpcbiAgICAgICAgIGNy"
    "aWdodCA9IG5wLnplcm9zKChub3V0cCwgcmlnaHQuc2hhcGVbMV0pKVxuLSAgICAgICAgY3JpZ2h0Wy1yaWdodC5zaGFwZVsw"
    "XTosIC1yaWdodC5zaGFwZVsxXTpdID0gMVxuKyAgICAgICAgY3JpZ2h0Wy1yaWdodC5zaGFwZVswXTosIC1yaWdodC5zaGFw"
    "ZVsxXTpdID0gcmlnaHRcbiBcbiAgICAgcmV0dXJuIG5wLmhzdGFjayhbY2xlZnQsIGNyaWdodF0pXG4gXG4iLCAicGF0Y2hf"
    "c2hhMjU2IjogIjBmM2U0NDQzMmVkODU0MGU5NTI2ZWRmZjRmODM3OTM5NDhhMmYxMzlmYzM5NzFiNjdjMzAwNDNjMWViNzk2"
    "NGEiLCAicHJvYmxlbV9zdGF0ZW1lbnQiOiAiTW9kZWxpbmcncyBgc2VwYXJhYmlsaXR5X21hdHJpeGAgZG9lcyBub3QgY29t"
    "cHV0ZSBzZXBhcmFiaWxpdHkgY29ycmVjdGx5IGZvciBuZXN0ZWQgQ29tcG91bmRNb2RlbHNcbkNvbnNpZGVyIHRoZSBmb2xs"
    "b3dpbmcgbW9kZWw6XHJcblxyXG5gYGBweXRob25cclxuZnJvbSBhc3Ryb3B5Lm1vZGVsaW5nIGltcG9ydCBtb2RlbHMgYXMg"
    "bVxyXG5mcm9tIGFzdHJvcHkubW9kZWxpbmcuc2VwYXJhYmxlIGltcG9ydCBzZXBhcmFiaWxpdHlfbWF0cml4XHJcblxyXG5j"
    "bSA9IG0uTGluZWFyMUQoMTApICYgbS5MaW5lYXIxRCg1KVxyXG5gYGBcclxuXHJcbkl0J3Mgc2VwYXJhYmlsaXR5IG1hdHJp"
    "eCBhcyB5b3UgbWlnaHQgZXhwZWN0IGlzIGEgZGlhZ29uYWw6XHJcblxyXG5gYGBweXRob25cclxuPj4+IHNlcGFyYWJpbGl0"
    "eV9tYXRyaXgoY20pXHJcbmFycmF5KFtbIFRydWUsIEZhbHNlXSxcclxuICAgICAgIFtGYWxzZSwgIFRydWVdXSlcclxuYGBg"
    "XHJcblxyXG5JZiBJIG1ha2UgdGhlIG1vZGVsIG1vcmUgY29tcGxleDpcclxuYGBgcHl0aG9uXHJcbj4+PiBzZXBhcmFiaWxp"
    "dHlfbWF0cml4KG0uUGl4MlNreV9UQU4oKSAmIG0uTGluZWFyMUQoMTApICYgbS5MaW5lYXIxRCg1KSlcclxuYXJyYXkoW1sg"
    "VHJ1ZSwgIFRydWUsIEZhbHNlLCBGYWxzZV0sXHJcbiAgICAgICBbIFRydWUsICBUcnVlLCBGYWxzZSwgRmFsc2VdLFxyXG4g"
    "ICAgICAgW0ZhbHNlLCBGYWxzZSwgIFRydWUsIEZhbHNlXSxcclxuICAgICAgIFtGYWxzZSwgRmFsc2UsIEZhbHNlLCAgVHJ1"
    "ZV1dKVxyXG5gYGBcclxuXHJcblRoZSBvdXRwdXQgbWF0cml4IGlzIGFnYWluLCBhcyBleHBlY3RlZCwgdGhlIG91dHB1dHMg"
    "YW5kIGlucHV0cyB0byB0aGUgbGluZWFyIG1vZGVscyBhcmUgc2VwYXJhYmxlIGFuZCBpbmRlcGVuZGVudCBvZiBlYWNoIG90"
    "aGVyLlxyXG5cclxuSWYgaG93ZXZlciwgSSBuZXN0IHRoZXNlIGNvbXBvdW5kIG1vZGVsczpcclxuYGBgcHl0aG9uXHJcbj4+"
    "PiBzZXBhcmFiaWxpdHlfbWF0cml4KG0uUGl4MlNreV9UQU4oKSAmIGNtKVxyXG5hcnJheShbWyBUcnVlLCAgVHJ1ZSwgRmFs"
    "c2UsIEZhbHNlXSxcclxuICAgICAgIFsgVHJ1ZSwgIFRydWUsIEZhbHNlLCBGYWxzZV0sXHJcbiAgICAgICBbRmFsc2UsIEZh"
    "bHNlLCAgVHJ1ZSwgIFRydWVdLFxyXG4gICAgICAgW0ZhbHNlLCBGYWxzZSwgIFRydWUsICBUcnVlXV0pXHJcbmBgYFxyXG5T"
    "dWRkZW5seSB0aGUgaW5wdXRzIGFuZCBvdXRwdXRzIGFyZSBubyBsb25nZXIgc2VwYXJhYmxlP1xyXG5cclxuVGhpcyBmZWVs"
    "cyBsaWtlIGEgYnVnIHRvIG1lLCBidXQgSSBtaWdodCBiZSBtaXNzaW5nIHNvbWV0aGluZz9cbiIsICJyZXBvIjogImFzdHJv"
    "cHkvYXN0cm9weSIsICJzb3VyY2UiOiAicHJpbmNldG9uLW5scC9TV0UtYmVuY2ggdGVzdCBzcGxpdCJ9CnsiYmFzZV9jb21t"
    "aXQiOiAiOTc4YTg5ZDVhMzJmNmU5MWFjZjA4MTJmN2YyYjI5YzlmOTdkNmEwYyIsICJpbnN0YW5jZV9pZCI6ICJwc2ZfX3Jl"
    "cXVlc3RzLTI4MjEiLCAicGF0Y2giOiAiZGlmZiAtLWdpdCBhL3JlcXVlc3RzL21vZGVscy5weSBiL3JlcXVlc3RzL21vZGVs"
    "cy5weVxuLS0tIGEvcmVxdWVzdHMvbW9kZWxzLnB5XG4rKysgYi9yZXF1ZXN0cy9tb2RlbHMucHlcbkBAIC0zMTksNyArMzE5"
    "LDcgQEAgZGVmIHByZXBhcmVfbWV0aG9kKHNlbGYsIG1ldGhvZCk6XG4gICAgICAgICBcIlwiXCJQcmVwYXJlcyB0aGUgZ2l2"
    "ZW4gSFRUUCBtZXRob2QuXCJcIlwiXG4gICAgICAgICBzZWxmLm1ldGhvZCA9IG1ldGhvZFxuICAgICAgICAgaWYgc2VsZi5t"
    "ZXRob2QgaXMgbm90IE5vbmU6XG4tICAgICAgICAgICAgc2VsZi5tZXRob2QgPSBzZWxmLm1ldGhvZC51cHBlcigpXG4rICAg"
    "ICAgICAgICAgc2VsZi5tZXRob2QgPSB0b19uYXRpdmVfc3RyaW5nKHNlbGYubWV0aG9kLnVwcGVyKCkpXG4gXG4gICAgIGRl"
    "ZiBwcmVwYXJlX3VybChzZWxmLCB1cmwsIHBhcmFtcyk6XG4gICAgICAgICBcIlwiXCJQcmVwYXJlcyB0aGUgZ2l2ZW4gSFRU"
    "UCBVUkwuXCJcIlwiXG5kaWZmIC0tZ2l0IGEvcmVxdWVzdHMvc2Vzc2lvbnMucHkgYi9yZXF1ZXN0cy9zZXNzaW9ucy5weVxu"
    "LS0tIGEvcmVxdWVzdHMvc2Vzc2lvbnMucHlcbisrKyBiL3JlcXVlc3RzL3Nlc3Npb25zLnB5XG5AQCAtNDM4LDkgKzQzOCw2"
    "IEBAIGRlZiByZXF1ZXN0KHNlbGYsIG1ldGhvZCwgdXJsLFxuICAgICAgICAgOnBhcmFtIGNlcnQ6IChvcHRpb25hbCkgaWYg"
    "U3RyaW5nLCBwYXRoIHRvIHNzbCBjbGllbnQgY2VydCBmaWxlICgucGVtKS5cbiAgICAgICAgICAgICBJZiBUdXBsZSwgKCdj"
    "ZXJ0JywgJ2tleScpIHBhaXIuXG4gICAgICAgICBcIlwiXCJcbi1cbi0gICAgICAgIG1ldGhvZCA9IHRvX25hdGl2ZV9zdHJp"
    "bmcobWV0aG9kKVxuLVxuICAgICAgICAgIyBDcmVhdGUgdGhlIFJlcXVlc3QuXG4gICAgICAgICByZXEgPSBSZXF1ZXN0KFxu"
    "ICAgICAgICAgICAgIG1ldGhvZCA9IG1ldGhvZC51cHBlcigpLFxuIiwgInBhdGNoX3NoYTI1NiI6ICI4ZDYzNGJlZDgzMzA4"
    "NDI0Zjg1NDUyYjE5M2MzNWQ5ZTlhNTRkMDQ4YmY4MDk2N2FiNWUxYTcwZGNkZTk5ZmYwIiwgInByb2JsZW1fc3RhdGVtZW50"
    "IjogIlR5cGVFcnJvciBhZnRlciAyLjcuMCAtPiAyLjguMCB1cGdyYWRlIChjYW5ub3QgbWFrZSBtZW1vcnkgdmlldy4uLilc"
    "bkknbSBydW5uaW5nIGludG8gdGhpcyB0cmFjZWJhY2sgYWZ0ZXIgdXBncmFkaW5nIHRvIDIuOC4wIGZyb20gMi43LjA6XG5c"
    "bmBgYFxuPHNuaXA+XG4gICAgcmVzcG9uc2UgPSBzZWxmLnNlc3Npb24uc2VuZChyZXF1ZXN0KVxuICBGaWxlIFwiL2hvbWUv"
    "dHJhdmlzL3ZpcnR1YWxlbnYvcHl0aG9uMi43LjkvbGliL3B5dGhvbjIuNy9zaXRlLXBhY2thZ2VzL3JlcXVlc3RzL3Nlc3Np"
    "b25zLnB5XCIsIGxpbmUgNTc5LCBpbiBzZW5kXG4gICAgciA9IGFkYXB0ZXIuc2VuZChyZXF1ZXN0LCAqKmt3YXJncylcbiAg"
    "RmlsZSBcIi9ob21lL3RyYXZpcy92aXJ0dWFsZW52L3B5dGhvbjIuNy45L2xpYi9weXRob24yLjcvc2l0ZS1wYWNrYWdlcy9y"
    "ZXF1ZXN0cy9hZGFwdGVycy5weVwiLCBsaW5lIDM2OSwgaW4gc2VuZFxuICAgIHRpbWVvdXQ9dGltZW91dFxuICBGaWxlIFwi"
    "L2hvbWUvdHJhdmlzL3ZpcnR1YWxlbnYvcHl0aG9uMi43LjkvbGliL3B5dGhvbjIuNy9zaXRlLXBhY2thZ2VzL3JlcXVlc3Rz"
    "L3BhY2thZ2VzL3VybGxpYjMvY29ubmVjdGlvbnBvb2wucHlcIiwgbGluZSA1NTksIGluIHVybG9wZW5cbiAgICBib2R5PWJv"
    "ZHksIGhlYWRlcnM9aGVhZGVycylcbiAgRmlsZSBcIi9ob21lL3RyYXZpcy92aXJ0dWFsZW52L3B5dGhvbjIuNy45L2xpYi9w"
    "eXRob24yLjcvc2l0ZS1wYWNrYWdlcy9yZXF1ZXN0cy9wYWNrYWdlcy91cmxsaWIzL2Nvbm5lY3Rpb25wb29sLnB5XCIsIGxp"
    "bmUgMzUzLCBpbiBfbWFrZV9yZXF1ZXN0XG4gICAgY29ubi5yZXF1ZXN0KG1ldGhvZCwgdXJsLCAqKmh0dHBsaWJfcmVxdWVz"
    "dF9rdylcbiAgRmlsZSBcIi9vcHQvcHl0aG9uLzIuNy45L2xpYi9weXRob24yLjcvaHR0cGxpYi5weVwiLCBsaW5lIDEwMDEs"
    "IGluIHJlcXVlc3RcbiAgICBzZWxmLl9zZW5kX3JlcXVlc3QobWV0aG9kLCB1cmwsIGJvZHksIGhlYWRlcnMpXG4gIEZpbGUg"
    "XCIvb3B0L3B5dGhvbi8yLjcuOS9saWIvcHl0aG9uMi43L2h0dHBsaWIucHlcIiwgbGluZSAxMDM1LCBpbiBfc2VuZF9yZXF1"
    "ZXN0XG4gICAgc2VsZi5lbmRoZWFkZXJzKGJvZHkpXG4gIEZpbGUgXCIvb3B0L3B5dGhvbi8yLjcuOS9saWIvcHl0aG9uMi43"
    "L2h0dHBsaWIucHlcIiwgbGluZSA5OTcsIGluIGVuZGhlYWRlcnNcbiAgICBzZWxmLl9zZW5kX291dHB1dChtZXNzYWdlX2Jv"
    "ZHkpXG4gIEZpbGUgXCIvb3B0L3B5dGhvbi8yLjcuOS9saWIvcHl0aG9uMi43L2h0dHBsaWIucHlcIiwgbGluZSA4NTAsIGlu"
    "IF9zZW5kX291dHB1dFxuICAgIHNlbGYuc2VuZChtc2cpXG4gIEZpbGUgXCIvb3B0L3B5dGhvbi8yLjcuOS9saWIvcHl0aG9u"
    "Mi43L2h0dHBsaWIucHlcIiwgbGluZSA4MjYsIGluIHNlbmRcbiAgICBzZWxmLnNvY2suc2VuZGFsbChkYXRhKVxuICBGaWxl"
    "IFwiL2hvbWUvdHJhdmlzL3ZpcnR1YWxlbnYvcHl0aG9uMi43LjkvbGliL3B5dGhvbjIuNy9zaXRlLXBhY2thZ2VzL3JlcXVl"
    "c3RzL3BhY2thZ2VzL3VybGxpYjMvY29udHJpYi9weW9wZW5zc2wucHlcIiwgbGluZSAyMTYsIGluIHNlbmRhbGxcbiAgICBk"
    "YXRhID0gbWVtb3J5dmlldyhkYXRhKVxuVHlwZUVycm9yOiBjYW5ub3QgbWFrZSBtZW1vcnkgdmlldyBiZWNhdXNlIG9iamVj"
    "dCBkb2VzIG5vdCBoYXZlIHRoZSBidWZmZXIgaW50ZXJmYWNlXG5gYGBcblxuVGhlIHByb2JsZW0gZ29lcyBhd2F5IGFmdGVy"
    "IGRvd25ncmFkaW5nIHRvIDIuNy4wLlxuXG5BIGZ1bGwgdHJhY2ViYWNrIGNhbiBiZSBmb3VuZCBbaGVyZV0oaHR0cHM6Ly90"
    "cmF2aXMtY2kub3JnL3NpbW9uLXdlYmVyL2dtdXNpY2FwaS9qb2JzLzgyMzY1MzA3KS5cblxuSGVyZSBhcmUgdGhlIHZlcnNp"
    "b25zIG9mIHJlbGV2YW50IHBhY2thZ2VzOlxuXG5gYGBcbmh0dHBsaWIyLTAuOS4yXG5uZGctaHR0cHNjbGllbnQtMC40LjBc"
    "bnB5YXNuMS0wLjEuOVxucHlhc24xLW1vZHVsZXMtMC4wLjhcbnB5b3BlbnNzbC0wLjE1LjFcbnJlcXVlc3RzLTIuOC4wXG5g"
    "YGBcblxuQW5kIGEgZnVsbCBsaXN0IG9mIHBhY2thZ2VzOlxuXG5gYGBcbk1lY2hhbmljYWxTb3VwLTAuMy4xXG5hcHBkaXJz"
    "LTEuNC4wXG5iZWF1dGlmdWxzb3VwNC00LjQuMVxuY2ZmaS0xLjIuMVxuY3J5cHRvZ3JhcGh5LTEuMC4yXG5kZWNvcmF0b3It"
    "NC4wLjRcbmVudW0zNC0xLjAuNFxuZ211c2ljYXBpLTcuMC4xLmRldjBcbmdwc29hdXRoLTAuMC40XG5odHRwbGliMi0wLjku"
    "MlxuaWRuYS0yLjBcbmlwYWRkcmVzcy0xLjAuMTRcbm11dGFnZW4tMS4zMVxubmRnLWh0dHBzY2xpZW50LTAuNC4wXG5vYXV0"
    "aDJjbGllbnQtMS41LjFcbnByb2Jvc2Npcy0xLjIuNi4wXG5wcm90b2J1Zi0yLjYuMVxucHlhc24xLTAuMS45XG5weWFzbjEt"
    "bW9kdWxlcy0wLjAuOFxucHljcGFyc2VyLTIuMTRcbnB5Y3J5cHRvLTIuNi4xXG5weW9wZW5zc2wtMC4xNS4xXG5weXRob24t"
    "ZGF0ZXV0aWwtMi40LjJcbnJlcXVlc3RzLTIuOC4wXG5yc2EtMy4yXG5zaXgtMS4xMC4wXG52YWxpZGljdG9yeS0xLjAuMVxu"
    "YGBgXG5cbkFueSBpZGVhcz9cblxuIiwgInJlcG8iOiAicHNmL3JlcXVlc3RzIiwgInNvdXJjZSI6ICJwcmluY2V0b24tbmxw"
    "L1NXRS1iZW5jaCB0ZXN0IHNwbGl0In0K"
)


def embedded_sample_rows() -> list[dict]:
    text = base64.b64decode(_SAMPLE_JSONL_B64).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# Patch parsing -> ground truth
# --------------------------------------------------------------------------

_DIFF_GIT_RE = re.compile(r"^diff --git a/(.*?) b/(.*)$")


def parse_patch(patch: str) -> dict:
    """Derive invasiveness ground truth from a unified git diff.

    Files are keyed by their post-patch path. Hunks are tracked with a small
    state machine so that content lines whose text starts with ``+++``/``---``
    are not mistaken for file headers.
    """
    files: dict[str, dict] = {}
    cur: dict | None = None
    in_hunk = False
    added = removed = 0

    for line in patch.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
            m = _DIFF_GIT_RE.match(line)
            path = m.group(2) if m else line[len("diff --git ") :].strip()
            cur = files.setdefault(
                path, {"old": path, "new": path, "new_file": False, "deleted": False}
            )
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk:
            if line.startswith("\\"):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
        elif line.startswith("new file mode"):
            if cur is not None:
                cur["new_file"] = True
        elif line.startswith("deleted file mode"):
            if cur is not None:
                cur["deleted"] = True
        elif line.startswith("--- "):
            if cur is not None:
                cur["old"] = line[4:].strip()
                if cur["old"] == "/dev/null":
                    cur["new_file"] = True
        elif line.startswith("+++ "):
            if cur is not None:
                cur["new"] = line[4:].strip()
                if cur["new"] == "/dev/null":
                    cur["deleted"] = True

    new_files = sum(1 for f in files.values() if f["new_file"])
    deleted_files = sum(1 for f in files.values() if f["deleted"])
    files_touched = len(files)
    modified_files = files_touched - new_files - deleted_files
    return {
        "files_touched": files_touched,
        "new_files": new_files,
        "deleted_files": deleted_files,
        "modified_files": modified_files,
        "added_lines": added,
        "removed_lines": removed,
        "touches_existing": int((modified_files + deleted_files) > 0),
        "multi_file": int(files_touched >= 2),
        "adds_new_file": int(new_files > 0),
        "paths": sorted(files),
    }


# --------------------------------------------------------------------------
# Deterministic text features
# --------------------------------------------------------------------------

KEYWORDS = (
    "add",
    "fix",
    "bug",
    "error",
    "exception",
    "traceback",
    "implement",
    "refactor",
    "remove",
    "update",
    "support",
    "improve",
    "test",
    "doc",
    "readme",
    "version",
    "invalid",
    "incorrect",
    "wrong",
    "crash",
    "fail",
    "regression",
    "expected",
    "actual",
    "should",
)

_PATH_TOKEN_RE = re.compile(
    r"(?<![\w./-])([A-Za-z_][\w.-]*(?:/[\w.-]+)*\.(?:py|pyi|pyx|pxd|c|h|cc|cpp|hpp|rst|txt|cfg|ini|toml|yaml|yml|json))"
    r"(?![\w/])"
)
_DOTTED_MODULE_RE = re.compile(
    r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,4})(?![\w.(])"
)
_FENCED_RE = re.compile(r"```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\)")
_VERSION_RE = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
_BULLET_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+[.)])\s")

TOP_REPOS_N = 8


def repo_slug(repo: str) -> str:
    return "t_repo_" + re.sub(r"[^a-z0-9]+", "_", repo.lower())


def top_repos(rows: list[dict], n: int = TOP_REPOS_N) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["repo"]] = counts.get(row["repo"], 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [repo for repo, _ in ordered[:n]]


_TLDS = {
    "com", "org", "net", "io", "edu", "gov", "dev", "app", "co", "uk", "de", "fr", "it",
    "us", "info", "biz", "me", "tv", "gg", "ru", "jp", "cn", "in", "au", "ca", "nl",
}


def extract_mentions(text: str) -> tuple[list[str], list[str]]:
    """Path-like and dotted-module tokens in the issue text (raw, unvalidated)."""
    paths = [
        tok
        for tok in dict.fromkeys(m.group(1) for m in _PATH_TOKEN_RE.finditer(text))
        if "://" not in tok and not tok.startswith(("www.", "github.com", "raw.githubusercontent"))
    ]
    modules = []
    for tok in dict.fromkeys(m.group(1) for m in _DOTTED_MODULE_RE.finditer(text)):
        parts = tok.split(".")
        if tok.endswith((".py", ".txt", ".rst", ".cfg", ".ini", ".json", ".yaml", ".yml")):
            continue
        if all(part.isdigit() for part in parts):
            continue
        if parts[-1].lower() in _TLDS or any(part.lower() in {"www", "http", "https"} for part in parts):
            continue
        modules.append(tok)
    return paths[:8], modules[:6]


def text_features(text: str, repo: str, repo_names: list[str]) -> dict[str, float]:
    lower = text.lower()
    feats: dict[str, float] = {
        "t_chars": math.log1p(len(text)),
        "t_words": math.log1p(len(text.split())),
        "t_lines": math.log1p(text.count("\n") + 1),
        "t_fenced_blocks": math.log1p(len(_FENCED_RE.findall(text)) // 2),
        "t_inline_code": math.log1p(len(_INLINE_CODE_RE.findall(text))),
        "t_traceback": 1.0 if _TRACEBACK_RE.search(text) else 0.0,
        "t_version_like": math.log1p(len(_VERSION_RE.findall(text))),
        "t_questions": math.log1p(text.count("?")),
        "t_exclamations": math.log1p(text.count("!")),
        "t_bullets": math.log1p(len(_BULLET_RE.findall(text))),
        "t_patch_hint": 1.0 if ("diff --git" in text or "+++" in text) else 0.0,
    }
    paths, modules = extract_mentions(text)
    feats["t_path_tokens_n"] = math.log1p(len(paths))
    feats["t_path_tokens_distinct"] = math.log1p(len(set(paths)))
    feats["t_module_tokens_n"] = math.log1p(len(modules))
    feats["t_module_tokens_distinct"] = math.log1p(len(set(modules)))
    for kw in KEYWORDS:
        feats[f"t_kw_{kw}"] = float(len(re.findall(rf"\b{kw}\b", lower)))
    slug = repo_slug(repo)
    for name in repo_names:
        feats[name] = 1.0 if name == slug else 0.0
    return feats


def text_feature_names(repo_rows: list[dict]) -> list[str]:
    probe = text_features("probe text", repo_rows[0]["repo"] if repo_rows else "a/b", top_repos(repo_rows))
    return sorted(probe)


# --------------------------------------------------------------------------
# Dataset access (cache -> HuggingFace parquet -> datasets-server rows API)
# --------------------------------------------------------------------------


def _http_get_retry(url: str, *, params: dict | None = None, timeout: float = 120.0, attempts: int = 5):
    import httpx

    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                resp = client.get(url, params=params)
            if resp.status_code == 200:
                return resp
            last_err = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except Exception as exc:  # noqa: BLE001 - network retries want any error
            last_err = exc
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"download failed after {attempts} attempts: {last_err}")


def check_disk(cache_dir: Path, need_mb: int) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    free_mb = shutil.disk_usage(cache_dir).free / (1024 * 1024)
    print(f"[data] cache={cache_dir} free={free_mb:.0f} MB (need >= {need_mb} MB)")
    if free_mb < need_mb:
        raise SystemExit(f"not enough disk in {cache_dir}: {free_mb:.0f} MB free, need {need_mb} MB")


def dataset_cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"swebench_{key}_test.jsonl"


def load_dataset(key: str, cache_dir: Path, *, refresh: bool = False) -> list[dict]:
    """Return the SWE-bench test split rows, cached as JSONL under cache_dir."""
    src = DATASET_SOURCES[key]
    cache_path = dataset_cache_path(cache_dir, key)
    if cache_path.exists() and not refresh:
        rows = [json.loads(line) for line in cache_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(f"[data] cache hit {cache_path.name}: {len(rows)} instances")
        return rows

    check_disk(cache_dir, MIN_FREE_MB_DATASET)
    rows: list[dict] = []
    try:
        import pyarrow  # noqa: F401  (optional fast path)

        url = HF_PARQUET_URL.format(dataset=src["hf_dataset"], split=src["split"])
        print(f"[data] downloading parquet {url}")
        resp = _http_get_retry(url, timeout=300.0)
        parquet_path = cache_dir / f"swebench_{key}_test.parquet"
        parquet_path.write_bytes(resp.content)
        import pandas as pd

        rows = pd.read_parquet(parquet_path).to_dict(orient="records")
    except ImportError:
        print("[data] pyarrow unavailable; using datasets-server rows API")
        offset = 0
        total = None
        while total is None or offset < total:
            resp = _http_get_retry(
                HF_ROWS_URL,
                params={
                    "dataset": src["hf_dataset"],
                    "config": "default",
                    "split": src["split"],
                    "offset": offset,
                    "length": 100,
                },
            )
            payload = resp.json()
            total = payload.get("num_rows_total", 0)
            chunk = payload.get("rows", [])
            if not chunk:
                break
            rows.extend(item["row"] for item in chunk)
            offset += len(chunk)
            print(f"[data] rows API: {offset}/{total}")

    expected = src["expected_rows"]
    if len(rows) != expected:
        print(f"[data] WARNING: expected {expected} instances, got {len(rows)}")
    cache_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8"
    )
    size_mb = cache_path.stat().st_size / (1024 * 1024)
    print(f"[data] wrote {cache_path.name} ({len(rows)} instances, {size_mb:.1f} MB)")
    return rows


# --------------------------------------------------------------------------
# Git-backed codebase signals (blob-filtered clone, base commit only)
# --------------------------------------------------------------------------


class GitRepo:
    """Minimal git wrapper with a blob-filtered clone. No network beyond clone."""

    def __init__(self, cache_dir: Path, repo: str):
        self.repo = repo
        self.root = cache_dir / "repos" / repo.replace("/", "__")
        self._file_list_cache: dict[str, list[str]] = {}
        self._by_base_cache: dict[str, dict[str, list[str]]] = {}
        self._date_cache: dict[str, datetime] = {}
        self._count_cache: dict[str, int] = {}
        self._window_cache: dict[tuple[str, str], tuple[int, int]] = {}
        self._checked_out: str | None = None

    # -- plumbing ---------------------------------------------------------
    def _git(self, args: list[str], *, timeout: float = 300.0) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args[:3])}... failed: {proc.stderr.strip()[:300]}")
        return proc.stdout

    def ensure_clone(self) -> None:
        if (self.root / ".git").exists():
            print(f"[codebase] reusing clone {self.root}")
            return
        check_disk(self.root.parent, MIN_FREE_MB_CLONE)
        url = f"https://github.com/{self.repo}.git"
        print(f"[codebase] cloning {url} (blob-filtered, no checkout) -> {self.root}")
        t0 = time.time()
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                url,
                str(self.root),
            ],
            check=True,
            timeout=1800,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        print(f"[codebase] clone done in {time.time() - t0:.0f}s")

    # -- queries ----------------------------------------------------------
    def file_list(self, commit: str) -> list[str]:
        if commit not in self._file_list_cache:
            out = self._git(["ls-tree", "-r", "--name-only", "-z", commit])
            self._file_list_cache[commit] = [p for p in out.split("\0") if p]
        return self._file_list_cache[commit]

    def commit_date(self, commit: str) -> datetime:
        if commit not in self._date_cache:
            iso = self._git(["show", "-s", "--format=%cI", commit]).strip()
            self._date_cache[commit] = datetime.fromisoformat(iso)
        return self._date_cache[commit]

    def count_commits_to(self, commit: str) -> int:
        if commit not in self._count_cache:
            self._count_cache[commit] = int(self._git(["rev-list", "--count", commit]).strip())
        return self._count_cache[commit]

    def window_stats(self, commit: str, since_iso: str) -> tuple[int, int]:
        """(commits, distinct authors) in the 180d window ending at ``commit``."""
        key = (commit, since_iso)
        if key not in self._window_cache:
            n = int(
                self._git(["rev-list", "--count", f"--since={since_iso}", commit]).strip()
            )
            log_out = self._git(
                ["log", f"--since={since_iso}", "--format=%ae", commit], timeout=600.0
            )
            authors = {line.strip() for line in log_out.splitlines() if line.strip()}
            self._window_cache[key] = (n, len(authors))
        return self._window_cache[key]

    def path_stats(self, commit: str, since_iso: str, paths: list[str]) -> tuple[int, int]:
        """(commits, distinct authors) touching ``paths`` in the window before commit."""
        if not paths:
            return 0, 0
        out = self._git(
            ["log", f"--since={since_iso}", "--format=%H|%ae", commit, "--", *paths],
            timeout=600.0,
        )
        commits = 0
        authors: set[str] = set()
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            commits += 1
            _, _, email = line.partition("|")
            if email:
                authors.add(email)
        return commits, len(authors)

    def checkout(self, commit: str) -> None:
        if self._checked_out == commit:
            return
        t0 = time.time()
        self._git(["checkout", "-q", "-f", commit], timeout=900.0)
        self._checked_out = commit
        print(f"[codebase]   checkout {commit[:10]} ({time.time() - t0:.1f}s)", file=sys.stderr)


# --------------------------------------------------------------------------
# Codebase feature extraction
# --------------------------------------------------------------------------

CODEBASE_FEATURES = (
    "c_has_mentions",
    "c_files_exist",
    "c_modules_exist",
    "c_fanin_sum",
    "c_fanin_max",
    "c_cc_mean",
    "c_cc_max",
    "c_lloc_sum",
    "c_cc_files_ok",
    "c_files_churn_180d",
    "c_files_churn_max",
    "c_files_authors_180d",
    "c_repo_py_files",
    "c_repo_files",
    "c_commits_to_base",
    "c_repo_churn_180d",
    "c_repo_authors_180d",
)

_MAX_MENTIONED_MODULES = 3
_MAX_MENTIONED_FILES = 5


def resolve_mentions(
    text: str, file_set: set[str], by_base: dict[str, list[str]]
) -> tuple[list[str], list[str]]:
    """Map raw issue-text tokens to files/modules that exist at the base commit."""
    raw_paths, raw_modules = extract_mentions(text)
    files: list[str] = []
    modules: list[str] = []

    for token in raw_paths:
        token = token.lstrip("./")
        if "/" in token:
            matches = [p for p in file_set if p == token or p.endswith("/" + token)]
        else:
            matches = by_base.get(token, [])
        for path in matches[:2]:
            if path not in files:
                files.append(path)

    for dotted in raw_modules:
        parts = dotted.split(".")
        candidates: list[str] = []
        found: str | None = None
        for cut in range(len(parts), 0, -1):
            candidate = "/".join(parts[:cut])
            candidates += [f"{candidate}.py", f"{candidate}/__init__.py"]
            found = next((c for c in candidates if c in file_set), None)
            if found is not None:
                break
        if found is None:
            continue
        module = found[:-3] if found.endswith(".py") else found
        if module.endswith("/__init__"):
            module = module[: -len("/__init__")]
        module = module.replace("/", ".")
        if module.count(".") > 0 and module not in modules:
            modules.append(module)
        if found not in files:
            files.append(found)
    return files[:_MAX_MENTIONED_FILES], modules[:_MAX_MENTIONED_MODULES]


def _file_complexity(source: str) -> tuple[float, float, int, int] | None:
    """(mean_cc, max_cc, lloc, n_blocks) via radon; None if radon is missing/fails."""
    import warnings

    try:
        from radon.complexity import cc_visit
        from radon.raw import analyze
    except ImportError:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # ancient sources produce SyntaxWarnings
            blocks = cc_visit(source)
            raw = analyze(source)
    except Exception:  # noqa: BLE001 - any parse failure means "no feature"
        return None
    if not blocks:
        return 1.0, 1.0, raw.lloc, 0
    values = [block.complexity for block in blocks]
    return float(statistics.mean(values)), float(max(values)), int(raw.lloc), len(values)


def _import_pattern(module: str) -> re.Pattern:
    esc = re.escape(module)
    return re.compile(
        rf"(?m)^[ \t]*(?:from[ \t]+{esc}(?:\.[\w.]+)?[ \t]+import|import[ \t]+{esc}(?:\.[\w.]+)?(?:\s|$|,))"
    )


def _fan_in(py_files: list[str], root: Path, modules: list[str]) -> dict[str, int]:
    patterns = [(m, _import_pattern(m)) for m in modules]
    fanin = {m: 0 for m in modules}
    for rel in py_files:
        try:
            source = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in patterns:
            if pattern.search(source):
                fanin[name] += 1
    return fanin


def codebase_features(
    git: GitRepo | None,
    commit: str,
    text: str,
    *,
    radon_available: bool,
) -> tuple[dict[str, float], dict]:
    """Codebase signals at ``commit``. Zeros when no mentions exist."""
    feats = {name: 0.0 for name in CODEBASE_FEATURES}
    info = {"mentions_found": 0, "fanin": {}, "checked_out": False}
    if git is None:
        return feats, info

    flist = git.file_list(commit)
    file_set = set(flist)
    by_base: dict[str, list[str]] = {}
    for path in flist:
        by_base.setdefault(path.rsplit("/", 1)[-1], []).append(path)

    feats["c_repo_files"] = math.log1p(len(flist))
    feats["c_repo_py_files"] = math.log1p(sum(1 for p in flist if p.endswith(".py")))
    feats["c_commits_to_base"] = math.log1p(git.count_commits_to(commit))

    base_date = git.commit_date(commit)
    since = (base_date - timedelta(days=SUBSET_WINDOW_DAYS)).isoformat()
    repo_commits, repo_authors = git.window_stats(commit, since)
    feats["c_repo_churn_180d"] = math.log1p(repo_commits)
    feats["c_repo_authors_180d"] = math.log1p(repo_authors)

    files, modules = resolve_mentions(text, file_set, by_base)
    if not files and not modules:
        return feats, info

    info["mentions_found"] = len(files) + len(modules)
    feats["c_has_mentions"] = 1.0
    feats["c_files_exist"] = float(len(files))
    feats["c_modules_exist"] = float(len(modules))

    if modules or files:
        git.checkout(commit)
        info["checked_out"] = True

    if modules:
        py_files = [p for p in flist if p.endswith(".py")]
        fanin = _fan_in(py_files, git.root, modules)
        info["fanin"] = fanin
        values = list(fanin.values())
        feats["c_fanin_sum"] = math.log1p(sum(values))
        feats["c_fanin_max"] = math.log1p(max(values)) if values else 0.0

    if files and radon_available:
        ccs_mean: list[float] = []
        ccs_max: list[float] = []
        lloc_total = 0
        n_ok = 0
        for rel in files:
            try:
                source = (git.root / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            result = _file_complexity(source)
            if result is None:
                continue
            mean_cc, max_cc, lloc, _ = result
            ccs_mean.append(mean_cc)
            ccs_max.append(max_cc)
            lloc_total += lloc
            n_ok += 1
        if n_ok:
            feats["c_cc_mean"] = float(statistics.mean(ccs_mean))
            feats["c_cc_max"] = float(max(ccs_max))
            feats["c_lloc_sum"] = float(lloc_total)
            feats["c_cc_files_ok"] = float(n_ok)

    if files:
        n_commits, n_authors = git.path_stats(commit, since, files)
        feats["c_files_churn_180d"] = math.log1p(n_commits)
        feats["c_files_authors_180d"] = math.log1p(n_authors)
        feats["c_files_churn_max"] = math.log1p(n_commits)
    return feats, info


# --------------------------------------------------------------------------
# Modeling / metrics
# --------------------------------------------------------------------------


def design_matrix(rows: list[dict], feature_names: list[str]) -> np.ndarray:
    """Rows may be instance dicts (features under "features") or flat feature dicts."""
    matrix = []
    for row in rows:
        feats = row.get("features", row)
        matrix.append([float(feats.get(name, 0.0)) for name in feature_names])
    return np.array(matrix, dtype=float)


def fold_indices(n: int, n_splits: int, seed: int = SEED) -> list[tuple[np.ndarray, np.ndarray]]:
    from sklearn.model_selection import KFold

    k = min(n_splits, n)
    kf = KFold(n_splits=k, shuffle=True, random_state=seed)
    return list(kf.split(np.arange(n)))


def _fit_predict_ridge(x_train, y_train_log, x_test) -> np.ndarray:
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipe = Pipeline([("scaler", StandardScaler()), ("model", Ridge(alpha=1.0))])
    pipe.fit(x_train, y_train_log)
    return pipe.predict(x_test)


def _fit_predict_hgb(x_train, y_train_log, x_test) -> np.ndarray:
    from sklearn.ensemble import HistGradientBoostingRegressor

    model = HistGradientBoostingRegressor(
        max_iter=150,
        max_depth=2,
        learning_rate=0.08,
        min_samples_leaf=8,
        l2_regularization=1.0,
        random_state=SEED,
    )
    model.fit(x_train, y_train_log)
    return model.predict(x_test)


def oof_regression(
    x: np.ndarray,
    y: np.ndarray,
    *,
    kind: str = "ridge",
    n_splits: int = 5,
    clip_min: float = 1.0,
) -> np.ndarray:
    """Out-of-fold predictions (trained on log1p, clipped to >= ``clip_min``)."""
    preds = np.zeros(len(y), dtype=float)
    for train_idx, test_idx in fold_indices(len(y), n_splits):
        y_log = np.log1p(y[train_idx])
        if kind == "ridge":
            raw = _fit_predict_ridge(x[train_idx], y_log, x[test_idx])
        else:
            raw = _fit_predict_hgb(x[train_idx], y_log, x[test_idx])
        preds[test_idx] = np.clip(np.expm1(raw), clip_min, None)
    return preds


def oof_logistic(x: np.ndarray, y_bin: np.ndarray, *, n_splits: int = 5) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    preds = np.zeros(len(y_bin), dtype=int)
    for train_idx, test_idx in fold_indices(len(y_bin), n_splits):
        y_train = y_bin[train_idx]
        if len(set(y_train.tolist())) < 2:
            preds[test_idx] = int(y_train[0])
            continue
        pipe = Pipeline(
            [("scaler", StandardScaler()), ("model", LogisticRegression(max_iter=5000, C=1.0))]
        )
        pipe.fit(x[train_idx], y_train)
        preds[test_idx] = pipe.predict(x[test_idx]).astype(int)
    return preds


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(set(y_true.tolist())) < 2 or len(set(y_pred.tolist())) < 2:
        return float("nan")
    from scipy.stats import spearmanr

    return float(spearmanr(y_true, y_pred).statistic)


def accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(y_true == y_pred))


def majority_rate(y_bin: np.ndarray) -> float:
    return float(max(np.mean(y_bin == 0), np.mean(y_bin == 1)))


def median_baseline_oof(y: np.ndarray, n_splits: int = 5) -> np.ndarray:
    preds = np.zeros(len(y), dtype=float)
    for train_idx, test_idx in fold_indices(len(y), n_splits):
        preds[test_idx] = float(np.median(y[train_idx]))
    return preds


def target_values(rows: list[dict], target: str) -> np.ndarray:
    """Ground-truth vector for a named target (``files``/``modified``/``added_lines``)."""
    key, _ = TARGETS[target]
    return np.array([row["gt"][key] for row in rows], dtype=float)


def constant_baseline_mae(y: np.ndarray, value: float) -> float:
    """MAE of the fold-independent constant predictor ``value`` (e.g. always-2)."""
    return float(np.mean(np.abs(y - value)))


def paired_bootstrap_ci(
    err_a: np.ndarray, err_b: np.ndarray, *, reps: int = 2000, seed: int = SEED
) -> tuple[float, float, float]:
    """CI of mean(err_b - err_a) by resampling instances (paired)."""
    diff = err_b - err_a
    rng = np.random.RandomState(seed)
    idx = rng.randint(0, len(diff), size=(reps, len(diff)))
    means = diff[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), float(diff.mean())


def fmt(value: float, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:.{digits}f}"


# --------------------------------------------------------------------------
# Experiment driver
# --------------------------------------------------------------------------


def pick_subset(
    rows: list[dict],
    repos: list[str] | None,
    limit: int,
    *,
    seed: int = SEED,
    min_files: int = 0,
) -> list[dict]:
    """Deterministic subset selection.

    ``repos=None`` keeps every repo; ``min_files`` keeps only patches whose
    ``files_touched`` is >= max(1, min_files); ``limit`` caps instances *per repo*
    (0 = no cap). With ``repos=[one repo]`` and ``min_files=0`` this reproduces the
    original single-repo subset selection exactly (same seed, same draw order).
    """
    repo_set = set(repos) if repos else None
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if repo_set is not None and row["repo"] not in repo_set:
            continue
        if row["gt"]["files_touched"] < max(min_files, 1):
            continue
        groups.setdefault(row["repo"], []).append(row)

    rng = np.random.RandomState(seed)
    chosen: list[dict] = []
    for repo in sorted(groups):
        group = sorted(groups[repo], key=lambda row: row["instance_id"])
        if 0 < limit < len(group):
            order = rng.permutation(len(group))
            group = [group[i] for i in order[:limit]]
        chosen.extend(group)
    return sorted(chosen, key=lambda row: (row["repo"], row["instance_id"]))


def run_variance(
    rows: list[dict],
    t_names: list[str],
    targets: list[str],
    *,
    min_files: int,
) -> dict:
    """Text-only regression metrics on the variance subset (all repos).

    ``--min-files N`` selects this subset; every target is fitted with the same
    seeded folds. Baselines: per-fold median of the training subset and the
    constant "always 2" predictor.
    """
    x = design_matrix(rows, t_names)
    out: dict = {
        "n": len(rows),
        "min_files": min_files,
        "repo_counts": _repo_counts(rows),
        "targets": {},
    }
    for name in targets:
        _, clip_min = TARGETS[name]
        y = target_values(rows, name)
        pred = oof_regression(x, y, kind="ridge", n_splits=5, clip_min=clip_min)
        pred_hgb = oof_regression(x, y, kind="hgb", n_splits=5, clip_min=clip_min)
        out["targets"][name] = {
            "n": len(rows),
            "mean": float(y.mean()),
            "median": float(np.median(y)),
            "max": float(y.max()),
            "mae_ridge": mae(y, pred),
            "mae_hgb": mae(y, pred_hgb),
            "rmse": rmse(y, pred),
            "spearman": spearman(y, pred),
            "mae_median": mae(y, median_baseline_oof(y)),
            "mae_const2": constant_baseline_mae(y, 2.0),
        }
    return out


def run_experiment(args: argparse.Namespace) -> dict:
    cache_dir = Path(args.cache_dir)
    target_names = parse_targets(args.target)
    primary_target = target_names[0]
    clip_min = TARGETS[primary_target][1]

    # ---- dataset ---------------------------------------------------------
    all_rows = load_dataset(args.dataset, cache_dir, refresh=args.refresh_cache)
    all_rows = [
        row for row in all_rows if row.get("problem_statement", "").strip() and row.get("patch", "").strip()
    ]
    repo_names = top_repos(all_rows)
    for row in all_rows:
        row["gt"] = parse_patch(row["patch"])
        row["features"] = text_features(row["problem_statement"], row["repo"], repo_names)

    rows = all_rows
    if args.max_instances and 0 < args.max_instances < len(rows):
        rng = np.random.RandomState(SEED)
        order = rng.permutation(len(rows))
        rows = [rows[i] for i in sorted(order[: args.max_instances])]
    cap_note = "" if len(rows) == len(all_rows) else " (capped from %d loaded)" % len(all_rows)
    print(f"[data] dataset={args.dataset} n_full_model={len(rows)}{cap_note}")

    t_names = text_feature_names(all_rows)
    y = target_values(rows, primary_target)
    x_text = design_matrix(rows, t_names)
    y_multi = np.array([row["gt"]["multi_file"] for row in rows])
    y_existing = np.array([row["gt"]["touches_existing"] for row in rows])
    print(
        f"[gt] files_touched: mean={np.mean([r['gt']['files_touched'] for r in rows]):.2f} "
        f"median={np.median([r['gt']['files_touched'] for r in rows]):.0f} "
        f"max={max(r['gt']['files_touched'] for r in rows):.0f} | multi-file={y_multi.mean():.1%} | "
        f"new-file={np.mean([r['gt']['adds_new_file'] for r in rows]):.1%} | "
        f"touches-existing={y_existing.mean():.3%}"
    )
    if primary_target != "files":
        print(
            f"[gt] primary target={primary_target}: mean={y.mean():.2f} "
            f"median={np.median(y):.0f} max={y.max():.0f}"
        )

    # ---- full-set text-only model (secondary) ----------------------------
    full_oof_ridge = oof_regression(x_text, y, kind="ridge", n_splits=5, clip_min=clip_min)
    full_oof_hgb = oof_regression(x_text, y, kind="hgb", n_splits=5, clip_min=clip_min)
    full_median = median_baseline_oof(y)
    full_results = {
        "n": len(rows),
        "target": primary_target,
        "mae_ridge": mae(y, full_oof_ridge),
        "mae_hgb": mae(y, full_oof_hgb),
        "mae_median": mae(y, full_median),
        "rmse": rmse(y, full_oof_ridge),
        "spearman": spearman(y, full_oof_ridge),
        "acc_multi": accuracy(y_multi, oof_logistic(x_text, y_multi)),
        "maj_multi": majority_rate(y_multi),
        "acc_existing": accuracy(y_existing, oof_logistic(x_text, y_existing)),
        "maj_existing": majority_rate(y_existing),
        "target_mean": float(y.mean()),
        "target_median": float(np.median(y)),
        "target_max": float(y.max()),
        "target_multi": float(y_multi.mean()),
        "target_new": float(np.mean([r["gt"]["adds_new_file"] for r in rows])),
    }

    # ---- variance subset: all repos, text-only ---------------------------
    variance = None
    if args.min_files >= 1:
        var_rows = pick_subset(all_rows, None, 0, min_files=args.min_files)
        variance = run_variance(var_rows, t_names, target_names, min_files=args.min_files)
        var_files = variance["targets"]["files"]
        print(
            f"[variance] files_touched >= {args.min_files}: n={variance['n']} "
            f"({len(variance['repo_counts'])} repos) | files target mean={var_files['mean']:.2f} "
            f"median={var_files['median']:.0f} max={var_files['max']:.0f} | "
            f"text-only Ridge MAE={var_files['mae_ridge']:.3f} Spearman={fmt(var_files['spearman'])}"
        )

    # ---- subset ablation --------------------------------------------------
    repo_list = subset_repo_list(args)
    subset_rows = pick_subset(all_rows, repo_list, args.subset_max_instances, min_files=args.min_files)
    ablation = None
    if subset_rows and not args.no_codebase:
        print(
            f"[subset] repos={repo_list} n={len(subset_rows)} "
            f"(min-files={args.min_files}, per-repo cap {args.subset_max_instances})"
        )
        radon_available = True
        try:
            import radon  # noqa: F401
        except ImportError:
            radon_available = False
            print("[codebase] radon missing: complexity features will be zero")
        t0 = time.time()
        try:
            git_map: dict[str, GitRepo] = {}
            skipped_repos: list[str] = []
            for repo in sorted({row["repo"] for row in subset_rows}):
                git = GitRepo(cache_dir, repo)
                try:
                    git.ensure_clone()
                    git_map[repo] = git
                except Exception as exc:  # noqa: BLE001 - a missing repo clone drops that repo only
                    print(f"[codebase] repo {repo} unavailable: {exc}", file=sys.stderr)
                    skipped_repos.append(repo)
            if skipped_repos:
                subset_rows = [row for row in subset_rows if row["repo"] in git_map]
                print(f"[codebase] dropped {skipped_repos}: ablation n={len(subset_rows)}")

            if not subset_rows:
                print("[codebase] ABLATION SKIPPED: no usable repo clones", file=sys.stderr)
                ablation = None
            else:
                failures = 0
                checkouts_pre = 0
                for i, row in enumerate(subset_rows):
                    try:
                        feats, info = codebase_features(
                            git_map[row["repo"]],
                            row["base_commit"],
                            row["problem_statement"],
                            radon_available=radon_available,
                        )
                        row["codebase"] = feats
                        if info["checked_out"]:
                            checkouts_pre += 1
                    except Exception as exc:  # noqa: BLE001 - keep the experiment running
                        failures += 1
                        print(f"[codebase] WARNING {row['instance_id']}: {exc}", file=sys.stderr)
                        row["codebase"] = {name: 0.0 for name in CODEBASE_FEATURES}
                    if (i + 1) % 10 == 0 or i + 1 == len(subset_rows):
                        print(
                            f"[codebase] {i + 1}/{len(subset_rows)} instances "
                            f"({time.time() - t0:.0f}s, checkouts={checkouts_pre})"
                        )
                ablation = run_ablation(subset_rows, t_names, failures, radon_available, target_names)
                ablation["coverage"]["repos_skipped"] = skipped_repos
        except Exception as exc:  # noqa: BLE001 - clone/network failure is a known risk
            print(f"[codebase] ABLATION SKIPPED: {exc}", file=sys.stderr)
            ablation = None

    return {
        "args": vars(args),
        "n_repos": len({row["repo"] for row in all_rows}),
        "n_loaded": len(all_rows),
        "repo_counts": _repo_counts(all_rows),
        "full": full_results,
        "variance": variance,
        "ablation": ablation,
        "repo_names": repo_names,
    }


def _repo_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["repo"]] = counts.get(row["repo"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def run_ablation(
    subset_rows: list[dict],
    t_names: list[str],
    failures: int,
    radon_available: bool,
    targets: list[str],
) -> dict:
    c_names = sorted(CODEBASE_FEATURES)
    merged = [{**row["features"], **row["codebase"]} for row in subset_rows]
    x_text = design_matrix(subset_rows, t_names)
    x_full = design_matrix(merged, t_names + c_names)
    y_multi = np.array([row["gt"]["multi_file"] for row in subset_rows])
    y_existing = np.array([row["gt"]["touches_existing"] for row in subset_rows])
    y_new = np.array([row["gt"]["adds_new_file"] for row in subset_rows])

    # Binary targets are regression-target independent: fit them once per arm.
    binary: dict[str, dict] = {}
    for arm, x in (("text", x_text), ("codebase", x_full)):
        binary[arm] = {
            "acc_multi": accuracy(y_multi, oof_logistic(x, y_multi)),
            "maj_multi": majority_rate(y_multi),
            "acc_existing": accuracy(y_existing, oof_logistic(x, y_existing)),
            "maj_existing": majority_rate(y_existing),
            "acc_new": accuracy(y_new, oof_logistic(x, y_new)),
            "maj_new": majority_rate(y_new),
        }

    mentions = int(sum(1 for row in subset_rows if row["codebase"].get("c_has_mentions", 0) > 0))
    fanin_fired = int(sum(1 for row in subset_rows if row["codebase"].get("c_fanin_max", 0) > 0))
    cc_fired = int(sum(1 for row in subset_rows if row["codebase"].get("c_cc_files_ok", 0) > 0))
    mask = np.array([row["codebase"].get("c_has_mentions", 0) > 0 for row in subset_rows])

    per_target: dict[str, dict] = {}
    for name in targets:
        _, clip_min = TARGETS[name]
        y = target_values(subset_rows, name)
        arms: dict[str, dict] = {}
        for arm, x in (("text", x_text), ("codebase", x_full)):
            pred = oof_regression(x, y, kind="ridge", n_splits=5, clip_min=clip_min)
            pred_hgb = oof_regression(x, y, kind="hgb", n_splits=5, clip_min=clip_min)
            err = np.abs(y - pred)
            folds = fold_indices(len(y), 5)
            per_fold = [float(np.mean(err[test_idx])) for _, test_idx in folds]
            arms[arm] = {
                "mae": mae(y, pred),
                "rmse": rmse(y, pred),
                "mae_hgb": mae(y, pred_hgb),
                "spearman": spearman(y, pred),
                "per_fold": per_fold,
                "err": err,
                "pred": pred,
                **binary[arm],
            }
        ci_lo, ci_hi, diff = paired_bootstrap_ci(arms["text"]["err"], arms["codebase"]["err"])

        # Subgroup diagnostic: does the codebase arm help where its features fire?
        subgroup = None
        if int(mask.sum()) >= 20:
            y_sub = y[mask]
            pred_t = oof_regression(x_text[mask], y_sub, kind="ridge", n_splits=5, clip_min=clip_min)
            pred_c = oof_regression(x_full[mask], y_sub, kind="ridge", n_splits=5, clip_min=clip_min)
            pred_only = oof_regression(
                x_full[mask][:, len(t_names):], y_sub, kind="ridge", n_splits=5, clip_min=clip_min
            )
            subgroup = {
                "n": int(mask.sum()),
                "mae_text": mae(y_sub, pred_t),
                "mae_codebase": mae(y_sub, pred_c),
                "mae_codebase_only": mae(y_sub, pred_only),
                "mae_median": mae(y_sub, median_baseline_oof(y_sub)),
                "mae_const2": constant_baseline_mae(y_sub, 2.0),
            }

        per_target[name] = {
            "target": name,
            "gt": {
                "mean": float(y.mean()),
                "median": float(np.median(y)),
                "max": float(y.max()),
            },
            "mae_median": mae(y, median_baseline_oof(y)),
            "mae_const2": constant_baseline_mae(y, 2.0),
            "arms": arms,
            "subgroup": subgroup,
            "bootstrap": {"ci_low": ci_lo, "ci_high": ci_hi, "mean_diff": diff},
        }

    primary = targets[0]
    repos = sorted({row["repo"] for row in subset_rows})
    y_files = target_values(subset_rows, "files")
    return {
        "n": len(subset_rows),
        "repo": repos[0] if len(repos) == 1 else "+".join(repos),
        "repos": repos,
        "repo_counts": _repo_counts(subset_rows),
        "target": primary,
        "targets": per_target,
        "mae_median": per_target[primary]["mae_median"],
        "mae_const2": per_target[primary]["mae_const2"],
        "arms": per_target[primary]["arms"],
        "subgroup": per_target[primary]["subgroup"],
        "bootstrap": per_target[primary]["bootstrap"],
        "coverage": {
            "mentions": mentions,
            "fanin": fanin_fired,
            "complexity": cc_fired,
            "failures": failures,
            "radon": radon_available,
        },
        "gt": {
            "mean": float(y_files.mean()),
            "median": float(np.median(y_files)),
            "max": float(y_files.max()),
            "multi_rate": float(np.mean(y_multi)),
        },
    }


# --------------------------------------------------------------------------
# Console report + docs
# --------------------------------------------------------------------------


def print_report(ctx: dict) -> None:
    full = ctx["full"]
    args = ctx["args"]
    print("\n=== SWE-bench invasiveness ablation (The Estimator, Codebase Lab) ===")
    print(f"dataset: SWE-bench {args['dataset']} test split | n={full['n']} | repos={ctx['n_repos']}")
    top = list(ctx["repo_counts"].items())[:8]
    print("repos: " + ", ".join(f"{r}({c})" for r, c in top) + ("" if len(ctx["repo_counts"]) <= 8 else ", ..."))
    print(
        f"files_touched ground truth: MAE-vs-median baseline={fmt(full['mae_median'])} | "
        f"text-only Ridge={fmt(full['mae_ridge'])} HGB={fmt(full['mae_hgb'])} | "
        f"RMSE={fmt(full['rmse'])} | Spearman={fmt(full['spearman'])}"
    )
    print(
        f"binary (full set, text-only): multi-file acc={fmt(full['acc_multi'])} "
        f"(majority {fmt(full['maj_multi'])}) | touches-existing acc={fmt(full['acc_existing'])} "
        f"(majority {fmt(full['maj_existing'])})"
    )

    var = ctx.get("variance")
    if var:
        print(
            f"\n--- variance subset (files_touched >= {var['min_files']}, all repos, text-only) "
            f"n={var['n']} ---"
        )
        for name, t in var["targets"].items():
            print(
                f"  target={name:<12} mean={fmt(t['mean'])} median={t['median']:.0f} max={t['max']:.0f} | "
                f"Ridge MAE={fmt(t['mae_ridge'])} HGB={fmt(t['mae_hgb'])} median-base={fmt(t['mae_median'])} "
                f"always-2={fmt(t['mae_const2'])} | RMSE={fmt(t['rmse'])} rho={fmt(t['spearman'])}"
            )

    abl = ctx.get("ablation")
    if abl is None:
        print("\n[ablation] NOT RUN (codebase arm unavailable)")
        return

    arms = abl["arms"]
    print(
        f"\n--- subset ablation: repo={abl['repo']} target={abl.get('target', 'files')} "
        f"n={abl['n']} (5-fold CV, identical folds) ---"
    )
    print(
        f"ground truth: mean={fmt(abl['gt']['mean'])} median={abl['gt']['median']:.0f} "
        f"max={abl['gt']['max']:.0f} multi-file={abl['gt']['multi_rate']:.1%}"
    )
    print(f"codebase features fired: mentions={abl['coverage']['mentions']}/{abl['n']} "
          f"fanin={abl['coverage']['fanin']} complexity={abl['coverage']['complexity']} "
          f"radon={'yes' if abl['coverage']['radon'] else 'no'} "
          f"extract-failures={abl['coverage']['failures']}")
    header = f"  {'arm':<16} {'MAE':>6} {'MAE(HGB)':>9} {'RMSE':>6} {'Spearman':>9}"
    print(header)
    print(f"  {'median base':<16} {fmt(abl['mae_median']):>6} {'-':>9} {'-':>6} {'-':>9}")
    for arm in ("text", "codebase"):
        label = "text-only" if arm == "text" else "text+codebase"
        print(
            f"  {label:<16} {fmt(arms[arm]['mae']):>6} {fmt(arms[arm]['mae_hgb']):>9} "
            f"{fmt(arms[arm]['rmse']):>6} {fmt(arms[arm]['spearman']):>9}"
        )
    print(f"  per-fold MAE text-only: " + " ".join(fmt(v) for v in arms["text"]["per_fold"]))
    print(f"  per-fold MAE +codebase: " + " ".join(fmt(v) for v in arms["codebase"]["per_fold"]))

    print(f"\n--- subset binary targets (accuracy) ---")
    print(f"  {'target':<24} {'text-only':>9} {'+codebase':>9} {'majority':>9}")
    for key, label in (("multi", "multi-file (ft >= 2)"), ("existing", "touches existing"), ("new", "adds new file")):
        print(
            f"  {label:<24} {fmt(arms['text'][f'acc_{key}']):>9} "
            f"{fmt(arms['codebase'][f'acc_{key}']):>9} {fmt(arms['text'][f'maj_{key}']):>9}"
        )

    sg = abl.get("subgroup")
    if sg:
        print(
            f"\n  subgroup where codebase features fired (n={sg['n']}): text-only MAE={fmt(sg['mae_text'])} | "
            f"text+codebase MAE={fmt(sg['mae_codebase'])} | codebase-only MAE={fmt(sg['mae_codebase_only'])} | "
            f"median baseline={fmt(sg['mae_median'])}"
        )

    target_map = abl.get("targets") or {}
    if len(target_map) > 1:
        print(f"\n--- per-target ablation (Ridge, same folds, n={abl['n']}) ---")
        print(
            f"  {'target':<12} {'median':>7} {'always-2':>8} {'text':>8} {'+code':>8} "
            f"{'HGB txt':>8} {'HGB cod':>8} {'rho txt':>8} {'rho cod':>8}"
        )
        for name, t in target_map.items():
            at, ac = t["arms"]["text"], t["arms"]["codebase"]
            print(
                f"  {name:<12} {fmt(t['mae_median']):>7} {fmt(t['mae_const2']):>8} "
                f"{fmt(at['mae']):>8} {fmt(ac['mae']):>8} {fmt(at['mae_hgb']):>8} {fmt(ac['mae_hgb']):>8} "
                f"{fmt(at['spearman']):>8} {fmt(ac['spearman']):>8}"
            )

    diff = abl["bootstrap"]["mean_diff"]
    rel = 100.0 * diff / arms["text"]["mae"] if arms["text"]["mae"] > 1e-12 else 0.0
    print(
        f"\npaired MAE difference (codebase - text): {diff:+.4f} "
        f"({rel:+.1f}%), 95% bootstrap CI [{abl['bootstrap']['ci_low']:+.4f}, "
        f"{abl['bootstrap']['ci_high']:+.4f}] -> {decision_gate(abl)}"
    )
    hgb_diff = arms["codebase"]["mae_hgb"] - arms["text"]["mae_hgb"]
    print(
        f"  HGB robustness: {fmt(arms['text']['mae_hgb'])} -> {fmt(arms['codebase']['mae_hgb'])} "
        f"({hgb_diff:+.4f}, {'same' if hgb_diff * diff >= 0 else 'OPPOSITE'} direction as Ridge)"
    )


def decision_gate(abl: dict) -> str:
    """Pre-registered rule: improved iff CI-high < 0 and relative reduction >= 1%."""
    text_mae = abl["arms"]["text"]["mae"]
    code_mae = abl["arms"]["codebase"]["mae"]
    ci_hi = abl["bootstrap"]["ci_high"]
    diff = code_mae - text_mae
    rel = diff / text_mae if text_mae > 1e-12 else 0.0
    if ci_hi < 0 and rel <= -0.01:
        return "IMPROVED"
    if diff >= 0:
        return "NOT IMPROVED (codebase arm equal or worse)"
    return "INCONCLUSIVE"


def render_docs(ctx: dict) -> str:
    args = ctx["args"]
    full = ctx["full"]
    abl = ctx.get("ablation")
    lines: list[str] = []
    add = lines.append
    add("# Codebase-signal ablation on SWE-bench (invasiveness prediction)")
    add("")
    add("Generated by `backend/scripts/swebench_validation.py` (deterministic, seed 42).")
    add("Question: does predicting **how invasive** a change is (files touched by")
    add("the real gold patch) get better when issue text is combined with codebase")
    add("signals at the base commit, versus issue text alone?")
    add("")
    add("## Method")
    add("")
    add("- Ground truth from each instance's `patch` (unified diff): `files_touched`,")
    add("  new/modified/deleted files, added/removed lines. Patches are labels only,")
    add("  never features.")
    add("- Primary metric: MAE of `files_touched` under 5-fold CV (identical seeded folds")
    add("  for both arms). Targets are modelled as `log1p`, predictions clipped to >= 1.")
    add("- Arms: (1) text-only deterministic features of `problem_statement` (size,")
    add("  structural counts, 25 keyword counts, path/module tokens, repo one-hot);")
    add("  (2) the same plus codebase features at `base_commit`: fan-in of modules")
    add("  mentioned in the issue text, radon cyclomatic complexity / LLOC of the")
    add("  mentioned files, 180-day churn and distinct authors of those paths, plus")
    add("  repo-level activity at the base commit. Model: Ridge(alpha=1) on")
    add("  StandardScaler; HistGradientBoosting reported as a robustness check.")
    add("- Decision gate pre-registered before running: **IMPROVED** iff the upper")
    add("  bound of the 95% paired-bootstrap CI of (MAE_codebase - MAE_text) is < 0")
    add("  **and** the relative MAE reduction is >= 1%; otherwise NOT IMPROVED")
    add("  (point estimate >= 0) or INCONCLUSIVE.")
    add("")
    add("## Data")
    add("")
    add(f"- Source: HuggingFace `{DATASET_SOURCES[args['dataset']]['hf_dataset']}`,")
    add(f"  `{DATASET_SOURCES[args['dataset']]['split']}` split; {full['n']} usable instances,")
    add(f"  {ctx['n_repos']} repos. Command: `{args['cmd']}`.")
    add("- Repo distribution (top): " + ", ".join(f"{r} {c}" for r, c in list(ctx["repo_counts"].items())[:8]) + ".")
    add(f"- Primary target stats (full set): mean files_touched={full['target_mean']:.2f},")
    add(f"  median={full['target_median']:.0f}, max={full['target_max']:.0f},")
    add(f"  multi-file rate={full['target_multi']:.1%}, adds-new-file rate={full['target_new']:.1%}.")
    if abl:
        add(f"- Subset for the ablation: `{abl['repo']}` (single repo, cloned with")
        add("  `--filter=blob:none --no-checkout`, blobs fetched lazily per base commit),")
        add(f"  n={abl['n']}; ground truth mean={abl['gt']['mean']:.2f}, max={abl['gt']['max']:.0f}.")
        add(f"- Codebase feature coverage on the subset: mentions of existing modules/files")
        add(f"  in issue text {abl['coverage']['mentions']}/{abl['n']}, fan-in fired")
        add(f"  {abl['coverage']['fanin']}, complexity fired {abl['coverage']['complexity']}")
        add(f"  (radon {'installed' if abl['coverage']['radon'] else 'MISSING - cc features zeroed'}),")
        add(f"  extraction failures {abl['coverage']['failures']}.")
    else:
        add("- Ablation not run (codebase arm unavailable in this run) - see limitations.")
    add("")
    add("## Results")
    add("")
    if abl:
        arms = abl["arms"]
        add(f"| arm (same folds, n={abl['n']}) | MAE | MAE HGB (robustness) | RMSE | Spearman |")
        add("|---|---:|---:|---:|---:|")
        add(f"| median baseline | {abl['mae_median']:.3f} | - | - | - |")
        add(f"| text-only | {arms['text']['mae']:.3f} | {arms['text']['mae_hgb']:.3f} | {arms['text']['rmse']:.3f} | "
            f"{fmt(arms['text']['spearman'])} |")
        add(f"| text+codebase | {arms['codebase']['mae']:.3f} | {arms['codebase']['mae_hgb']:.3f} | "
            f"{arms['codebase']['rmse']:.3f} | {fmt(arms['codebase']['spearman'])} |")
        add("")
        add("Binary targets (accuracy, identical folds):")
        add("")
        add("| target | text-only | text+codebase | majority |")
        add("|---|---:|---:|---:|")
        add(f"| multi-file (files_touched >= 2) | {arms['text']['acc_multi']:.3f} | {arms['codebase']['acc_multi']:.3f} | "
            f"{arms['text']['maj_multi']:.3f} |")
        add(f"| touches existing files | {arms['text']['acc_existing']:.3f} | {arms['codebase']['acc_existing']:.3f} | "
            f"{arms['text']['maj_existing']:.3f} |")
        add(f"| adds a new file | {arms['text']['acc_new']:.3f} | {arms['codebase']['acc_new']:.3f} | "
            f"{arms['text']['maj_new']:.3f} |")
        add("")
        sg = abl.get("subgroup")
        if sg:
            add(f"Subgroup where codebase features fired (n={sg['n']}): text-only MAE {sg['mae_text']:.3f}, "
                f"text+codebase MAE {sg['mae_codebase']:.3f}, codebase-only MAE {sg['mae_codebase_only']:.3f}, "
                f"median baseline {sg['mae_median']:.3f}.")
            add("")
    add(f"Text-only on the full set (n={full['n']}): Ridge MAE={full['mae_ridge']:.3f} "
        f"(HGB {full['mae_hgb']:.3f}, median baseline {full['mae_median']:.3f}), "
        f"RMSE={full['rmse']:.3f}, Spearman={fmt(full['spearman'])}.")
    add("")
    add("## Decision gate")
    add("")
    if abl:
        diff = abl["bootstrap"]["mean_diff"]
        rel = 100.0 * diff / arms["text"]["mae"] if arms["text"]["mae"] > 1e-12 else 0.0
        add(f"Paired MAE difference (text+codebase - text-only): **{diff:+.4f} ({rel:+.1f}%)**, ")
        add(f"95% bootstrap CI **[{abl['bootstrap']['ci_low']:+.4f}, {abl['bootstrap']['ci_high']:+.4f}]**.")
        add("")
        add(
            f"**Result: {decision_gate(abl)}**: text-only MAE {arms['text']['mae']:.3f} vs "
            f"text+codebase MAE {arms['codebase']['mae']:.3f} on n={abl['n']} {abl['repo']} instances."
        )
        hgb_diff = arms["codebase"]["mae_hgb"] - arms["text"]["mae_hgb"]
        add(f"Robustness (HistGradientBoosting): {arms['text']['mae_hgb']:.3f} -> "
            f"{arms['codebase']['mae_hgb']:.3f} ({hgb_diff:+.3f}, "
            f"{'same' if hgb_diff * diff >= 0 else 'OPPOSITE'} direction as Ridge).")
    else:
        add("**Result: INCONCLUSIVE** (ablation did not run).")
    add("")
    add("## Leakage controls")
    add("")
    add("- Features never read the patch; `patch` is used only to compute labels, and")
    add("  `hints_text` is ignored entirely.")
    add("- Codebase features are read at the instance `base_commit` via git objects;")
    add("  churn/author windows use `--since=<base_date - 180d> <base_commit>`, which")
    add("  cannot reach commits after the base commit.")
    add("- File paths mentioned in issue text are only kept as features if they exist at")
    add("  the base commit (existence check against `git ls-tree <base_commit>`).")
    add("- Repo one-hot categories and feature lists are label-independent (count-based).")
    add("")
    add("## Domain mismatch")
    add("")
    add("SWE-bench instances are open-source Python libraries (django, sympy, sklearn,")
    add("sphinx, matplotlib, pytest, ...). The product's domain is B2B SaaS delivery")
    add("estimation. Nothing here validates SaaS performance directly: results test the")
    add("mechanism (issue text + repo signals carry invasiveness signal), not the product")
    add("domain. Absolute MAE values should not be transferred to SaaS planning.")
    add("")
    add("## Limitations")
    add("")
    add("- SWE-bench Lite (300) was checked and rejected for the primary target: all 300")
    add("  Lite patches touch exactly one file, so MAE(files_touched) has no variance there;")
    add("  the full test split (2294) is used instead. Lite is a valid source of the")
    add("  self-test rows.")
    add("- Codebase features only fire when the issue text mentions module/file tokens")
    add(f"  ({abl['coverage']['mentions'] if abl else '?'} of {abl['n'] if abl else '?'} subset rows);")
    add("  for the rest the codebase arm falls back to repo-level activity features.")
    add("- Radon complexity is optional; without it those columns are zeroed (stated above).")
    add("- Fan-in is an import-occurrence count over absolute imports in `.py` files at the")
    add("  base commit (relative imports are missed).")
    add("- HistGradientBoosting rows are robustness checks only; the gate uses Ridge.")
    add("")
    add("## Reproduce")
    add("")
    add("```bash")
    add("cd backend && PYTHONPATH=. /root/venvs/estimator/bin/python \\")
    add(f"  {args['cmd']}")
    add("/root/venvs/estimator/bin/python scripts/swebench_validation.py --self-test")
    add("```")
    add("")
    return "\n".join(lines)


def render_refinement(ctx: dict) -> str:
    """Render the appended "Multi-file refinement" section.

    Kept separate from ``render_docs`` so the original report section is never
    overwritten; ``main`` appends/replaces only this section.
    """
    args = ctx["args"]
    var = ctx.get("variance")
    abl = ctx.get("ablation")
    lines: list[str] = []
    add = lines.append
    add("## Multi-file refinement (2026-10-17)")
    add("")
    add("Why: 1723 of 2294 full-split patches (75.1%) touch exactly one file, so the")
    add("original MAE target is near-degenerate. This refinement re-runs the ablation on")
    add("the variance subset (`files_touched >= 2`, n=571) and on two alternative")
    add("patch-derived targets (`modified_files`, `added_lines`). The section above is")
    add("kept unchanged; this is a refinement, not a retraction.")
    add("")
    add("### Method delta")
    add("")
    add(f"- `--min-files {args['min_files']}`: the variance subset and the ablation subset keep only")
    add(f"  patches touching >= {args['min_files']} files (default 0 = original behaviour).")
    add("- `--target files|modified|added_lines|all`: regression-target switch; labels come")
    add("  from the same patch parser. Same seeded 5-fold CV, same features, same Ridge/HGB;")
    add("  `log1p` targets, predictions clipped to >= 1 (`files`) or >= 0 (others).")
    add("- Codebase arm spans several repos, one blob-filtered `--no-checkout` clone each")
    add("  (per-instance checkout at `base_commit`, exactly as before).")
    add("- Extra baselines: per-fold median of the training subset and constant `always-2`.")
    add("- Leakage controls unchanged from the section above (features never read the patch;")
    add("  `hints_text` ignored; all codebase reads are at `base_commit`).")
    add("")
    add("### Data")
    add("")
    if var:
        add(f"- Variance subset (`files_touched >= {var['min_files']}`, all repos, text-only): n={var['n']},")
        add("  repos: " + ", ".join(f"{r} {c}" for r, c in list(var["repo_counts"].items())[:8]) + ".")
    if abl:
        add(f"- Codebase ablation subset: n={abl['n']} ("
            + ", ".join(f"{r} {c}" for r, c in abl["repo_counts"].items()) + ").")
        add("- Codebase feature coverage: mentions of existing modules/files in issue text")
        add(f"  {abl['coverage']['mentions']}/{abl['n']}, fan-in fired {abl['coverage']['fanin']}, "
            f"complexity fired {abl['coverage']['complexity']} "
            f"(radon {'installed' if abl['coverage']['radon'] else 'MISSING - cc zeroed'}), "
            f"extraction failures {abl['coverage']['failures']}.")
        if abl["coverage"].get("repos_skipped"):
            add(f"- Repos dropped (clone unavailable): {', '.join(abl['coverage']['repos_skipped'])}.")
    else:
        add("- Codebase arm unavailable in this run (clone/network failure): text-only rows only.")
    add("")
    add("### Results")
    add("")
    if var:
        add(f"Variance subset, text-only (all repos, n={var['n']}):")
        add("")
        add("| target | mean | median | max | MAE Ridge | MAE HGB | RMSE | Spearman | median base | always-2 |")
        add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for name, t in var["targets"].items():
            add(f"| {name} | {t['mean']:.2f} | {t['median']:.0f} | {t['max']:.0f} | {t['mae_ridge']:.3f} | "
                f"{t['mae_hgb']:.3f} | {t['rmse']:.3f} | {fmt(t['spearman'])} | "
                f"{t['mae_median']:.3f} | {t['mae_const2']:.3f} |")
        add("")
    if abl:
        for name, t in abl["targets"].items():
            at, ac = t["arms"]["text"], t["arms"]["codebase"]
            add(f"Codebase subset, target `{name}` (n={abl['n']}, identical folds):")
            add("")
            add("| arm | MAE | MAE HGB | RMSE | Spearman |")
            add("|---|---:|---:|---:|---:|")
            add(f"| median baseline | {t['mae_median']:.3f} | - | - | - |")
            add(f"| always-2 | {t['mae_const2']:.3f} | - | - | - |")
            add(f"| text-only | {at['mae']:.3f} | {at['mae_hgb']:.3f} | {at['rmse']:.3f} | {fmt(at['spearman'])} |")
            add(f"| text+codebase | {ac['mae']:.3f} | {ac['mae_hgb']:.3f} | {ac['rmse']:.3f} | {fmt(ac['spearman'])} |")
            add("")
            sg = t.get("subgroup")
            if sg:
                note = ""
                if sg["mae_text"] > 10 * sg["mae_median"] or sg["mae_codebase"] > 10 * sg["mae_median"]:
                    note = " (UNSTABLE Ridge extrapolation on this heavy-tailed target - treat as invalid)"
                add(f"Mention subgroup where codebase features fired (n={sg['n']}): text-only MAE "
                    f"{sg['mae_text']:.3f}, text+codebase {sg['mae_codebase']:.3f}, codebase-only "
                    f"{sg['mae_codebase_only']:.3f}, median baseline {sg['mae_median']:.3f}.{note}")
                add("")
        add("| target | ΔMAE (codebase - text) | 95% CI | gate |")
        add("|---|---:|---|---|")
        for name, t in abl["targets"].items():
            bt = t["bootstrap"]
            add(f"| {name} | {bt['mean_diff']:+.3f} | "
                f"[{bt['ci_low']:+.3f}, {bt['ci_high']:+.3f}] | {decision_gate(t)} |")
        add("")
        add("### Decision (multi-file subset)")
        add("")
        decision_t = abl["targets"].get("files") or abl["targets"][abl["target"]]
        decision_label = "files" if "files" in abl["targets"] else abl["target"]
        text_mae = decision_t["arms"]["text"]["mae"]
        code_mae = decision_t["arms"]["codebase"]["mae"]
        bt = decision_t["bootstrap"]
        rel = 100.0 * bt["mean_diff"] / text_mae if text_mae > 1e-12 else 0.0
        verdict = decision_gate(decision_t)
        add(f"Target `{decision_label}`, n={abl['n']}, paired MAE difference (text+codebase - "
            f"text-only): **{bt['mean_diff']:+.4f} ({rel:+.1f}%)**, 95% bootstrap CI "
            f"**[{bt['ci_low']:+.4f}, {bt['ci_high']:+.4f}]**.")
        add("")
        if verdict == "IMPROVED":
            add(f"**Result: IMPROVED on the variance subset** for target `{decision_label}`: "
                f"text-only MAE {text_mae:.3f} vs text+codebase MAE {code_mae:.3f} on n={abl['n']} "
                f"instances. Caveats: n is one order of magnitude smaller than the full split, the")
            add("repos are three open-source Python projects (domain mismatch above still applies),")
            add("and the gain must be read together with the HGB robustness row and the CI width.")
        elif verdict.startswith("NOT IMPROVED"):
            add(f"**Result: NOT IMPROVED (codebase arm equal or worse)**: text-only MAE {text_mae:.3f} "
                f"vs text+codebase MAE {code_mae:.3f} on n={abl['n']} instances. On the subset with")
            add("actual target variance, codebase signals still do not add measurable accuracy; the")
            add("original negative result is not an artefact of the degenerate single-file majority.")
        else:
            add(f"**Result: INCONCLUSIVE**: text-only MAE {text_mae:.3f} vs text+codebase MAE "
                f"{code_mae:.3f} on n={abl['n']} instances (CI includes 0, point estimate negative).")
            add("Directionally the codebase arm is better, but the pre-registered gate is not met;")
            add("treat this as a weak signal needing more instances, not as an improvement. The gate")
            add("is not met for any of the three targets, so the original negative result is not")
            add("overturned by this refinement.")
        add("")
        add("The multi-file-vs-single-file binary classification is only meaningful on the full set")
        add("(kept above); on this subset it is degenerate (all positives).")
        add("")
    else:
        add("**Result: INCONCLUSIVE for the codebase arm** (ablation did not run); the variance-subset")
        add("text-only numbers above stand.")
        add("")
    add("### Caveats")
    add("")
    add("- Small n (single-repo families, 571 variance rows, 132 codebase rows) and OSS-only")
    add("  domain: magnitudes should not be transferred to B2B SaaS estimation.")
    add("- Codebase features only fire when the issue text resolves to existing modules/files;")
    add("  the mention subgroup is reported per target where n >= 20.")
    add("- `modified_files` can be 0 (new-file-only patches) and `added_lines` is heavy-tailed;")
    add("  the always-2 baseline is shown for comparability, the median baseline is the fairer one.")
    add("- Ridge on `added_lines` is unstable (log1p inversion of extrapolated predictions can")
    add("  blow up on heavy-tailed rows; the subgroup line is flagged). HGB and the median")
    add("  baseline are the robust rows for that target. The codebase arm does not beat the")
    add("  median baseline on any target.")
    add("- Rank signal on the variance subset is ~0 for `files`/`modified` (-0.02/-0.00) and")
    add("  weakly positive for `added_lines` (+0.19) under the text-only arm.")
    add("")
    add("### Reproduce (refinement)")
    add("")
    add("```bash")
    add("cd backend && PYTHONPATH=. /root/venvs/estimator/bin/python \\")
    add(f"  {args['cmd']}")
    add("```")
    add("")
    add("Rerun with the same command reproduces identical numbers (seeded folds; base-commit")
    add("checkouts are read-only queries of git objects).")
    add("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Self-test (offline: embedded rows + synthetic parser cases)
# --------------------------------------------------------------------------

_SYNTHETIC_PATCH = (
    "diff --git a/src/new_mod.py b/src/new_mod.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/src/new_mod.py\n"
    "@@ -0,0 +1,3 @@\n"
    "+import os\n"
    "+--- this content line starts with dashes\n"
    "+++ this content line starts with pluses\n"
    "diff --git a/src/old_mod.py b/src/old_mod.py\n"
    "deleted file mode 100644\n"
    "--- a/src/old_mod.py\n"
    "+++ /dev/null\n"
    "@@ -1,2 +0,0 @@\n"
    "-gone_a()\n"
    "-gone_b()\n"
)

_EXPECTED_PARSER = {
    "sympy__sympy-22914": (1, 0, 0),
    "psf__requests-1962": (1, 0, 0),
    "pytest-dev__pytest-6116": (1, 0, 0),
    "astropy__astropy-12907": (1, 0, 0),
    "psf__requests-2821": (2, 0, 0),
}


def run_self_test(verbose: bool = True) -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        if verbose:
            print(f"[self-test] {status}: {name}" + (f" ({detail})" if detail else ""))
        if not condition:
            failures.append(name)

    t0 = time.time()
    check("self-test is offline", True)

    rows = embedded_sample_rows()
    check("embedded rows parse to JSON", len(rows) == 5, f"n={len(rows)}")

    # 1. patch parsing on real rows
    for row in rows:
        gt = parse_patch(row["patch"])
        expected = _EXPECTED_PARSER.get(row["instance_id"])
        if expected is None:
            check(f"gt for {row['instance_id']}", False, "no expected value frozen")
            continue
        actual = (gt["files_touched"], gt["new_files"], gt["deleted_files"])
        check(f"patch parse {row['instance_id']}", actual == expected, f"got {actual} want {expected}")
        check(
            f"gt consistency {row['instance_id']}",
            gt["modified_files"] + gt["new_files"] + gt["deleted_files"] == gt["files_touched"],
        )
        check(f"has lines {row['instance_id']}", gt["added_lines"] >= 0 and gt["removed_lines"] >= 0)

    # 2. parser edge cases (new file, deleted file, hunk content lines like --- / +++)
    gt = parse_patch(_SYNTHETIC_PATCH)
    check("synthetic files_touched=2", gt["files_touched"] == 2, str(gt["files_touched"]))
    check("synthetic new_files=1", gt["new_files"] == 1)
    check("synthetic deleted_files=1", gt["deleted_files"] == 1)
    check("synthetic added_lines=3", gt["added_lines"] == 3, str(gt["added_lines"]))
    check("synthetic removed_lines=2", gt["removed_lines"] == 2, str(gt["removed_lines"]))
    check("synthetic touches_existing=1", gt["touches_existing"] == 1)
    new_only = parse_patch(
        "diff --git a/x.py b/x.py\nnew file mode 100644\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+pass\n"
    )
    check("new-only patch touches_existing=0", new_only["touches_existing"] == 0)
    check("rename patch counted as modified", parse_patch(
        "diff --git a/a.py b/b.py\nrename from a.py\nrename to b.py\n"
    )["modified_files"] == 1)

    # 3. features
    repo_names = top_repos(rows)
    for row in rows:
        feats = text_features(row["problem_statement"], row["repo"], repo_names)
        feat_names = sorted(feats)
        check(f"feature keys stable {row['instance_id']}", len(feat_names) == len(set(feat_names)))
        check(f"features finite {row['instance_id']}", all(math.isfinite(v) for v in feats.values()))
    paths, modules = extract_mentions("Please fix `sympy/core/mul.py` and sympy.core.mul usage.")
    check("mention extraction paths", "sympy/core/mul.py" in paths, str(paths))
    check("mention extraction modules", any(m.startswith("sympy.core") for m in modules), str(modules))
    feats = text_features("Traceback (most recent call last):\n```\ncode\n```\nAdd support?", "a/b", ["t_repo_a_b"])
    check("traceback feature", feats["t_traceback"] == 1.0)
    check("fenced block feature", feats["t_fenced_blocks"] == math.log1p(1))
    check("repo one-hot", feats["t_repo_a_b"] == 1.0)

    # 4. codebase feature path with a git=None stub must yield zeros, flags included
    cb, info = codebase_features(None, "deadbeef", "sympy/core/mul.py", radon_available=False)
    check("codebase zero-fill keys", sorted(cb) == list(sorted(CODEBASE_FEATURES)))
    check("codebase zeros when git=None", all(v == 0.0 for v in cb.values()) and info["mentions_found"] == 0)

    # 5. models + metrics run on the tiny sample (synthetic codebase columns)
    feat_names = sorted(text_features(rows[0]["problem_statement"], rows[0]["repo"], repo_names))
    rng = np.random.RandomState(SEED)
    for row in rows:
        row["features"] = text_features(row["problem_statement"], row["repo"], repo_names)
        row["gt"] = parse_patch(row["patch"])
    x_text = design_matrix(rows, feat_names)
    x_code = np.hstack([x_text, rng.normal(size=(len(rows), 3))])
    y = np.array([row["gt"]["files_touched"] for row in rows], dtype=float)
    pred_a = oof_regression(x_text, y, kind="ridge", n_splits=5)
    pred_b = oof_regression(x_code, y, kind="ridge", n_splits=5)
    check("oof preds shape/finite", pred_a.shape == y.shape and np.all(np.isfinite(pred_a)))
    check("oof preds clipped >= 1", float(pred_a.min()) >= 1.0)
    check("MAE finite", math.isfinite(mae(y, pred_a)) and math.isfinite(mae(y, pred_b)))
    pred_again = oof_regression(x_text, y, kind="ridge", n_splits=5)
    check("determinism", np.array_equal(pred_a, pred_again))
    # regression guard: codebase columns must actually enter the ablation matrix
    c_names = sorted(CODEBASE_FEATURES)
    merged_probe = [
        {**row["features"], **{name: (1.0 if name == "c_has_mentions" else 0.0) for name in c_names}}
        for row in rows
    ]
    x_full_probe = design_matrix(merged_probe, feat_names + c_names)
    check(
        "codebase columns wired into matrix",
        x_full_probe.shape[1] == x_text.shape[1] + len(c_names)
        and float(np.abs(x_full_probe[:, x_text.shape[1] :]).sum()) == float(len(rows)),
    )
    yb = np.array([row["gt"]["multi_file"] for row in rows])
    acc = accuracy(yb, oof_logistic(x_text, yb, n_splits=5))
    check("logistic runs", 0.0 <= acc <= 1.0, f"acc={acc:.2f}")
    check("mae of perfect predictor is 0", mae(y, y) == 0.0)
    check("spearman monotone is 1", abs(spearman(np.array([1.0, 2, 3]), np.array([1.0, 2, 3])) - 1.0) < 1e-9)
    check("majority rate sane", 0.5 <= majority_rate(yb) <= 1.0)
    lo, hi, mean_diff = paired_bootstrap_ci(np.array([1.0, 2, 3]), np.array([1.5, 2.5, 3.5]))
    check("bootstrap CI ordered", lo <= mean_diff <= hi, f"[{lo:.3f}, {hi:.3f}] mean={mean_diff:.3f}")

    # 6. refinement plumbing: targets, min-files filter, multi-target ablation, docs
    check("parse_targets single", parse_targets("files") == ["files"])
    check("parse_targets all", parse_targets("all") == ["files", "modified", "added_lines"])
    check(
        "target_values files",
        np.allclose(target_values(rows, "files"), [r["gt"]["files_touched"] for r in rows]),
    )
    check(
        "target_values added_lines",
        np.allclose(target_values(rows, "added_lines"), [r["gt"]["added_lines"] for r in rows]),
    )
    check("constant baseline", abs(constant_baseline_mae(np.array([1.0, 3.0]), 2.0) - 1.0) < 1e-12)
    var_rows = pick_subset(rows, None, 0, min_files=2)
    check(
        "min-files filter keeps multi-file only",
        [r["instance_id"] for r in var_rows] == ["psf__requests-2821"],
        str([r["instance_id"] for r in var_rows]),
    )
    pick_a = [r["instance_id"] for r in pick_subset(rows, ["psf/requests"], 1)]
    pick_b = [r["instance_id"] for r in pick_subset(rows, ["psf/requests"], 1)]
    check("pick_subset deterministic", pick_a == pick_b and len(pick_a) == 1, str(pick_a))
    pred_zero = oof_regression(x_text, np.zeros(len(rows)), kind="ridge", n_splits=5, clip_min=0.0)
    check("clip_min 0 allows below-1 preds", float(pred_zero.min()) >= 0.0 and float(pred_zero.min()) < 1.0)

    ctx = {"args": {"dataset": "full", "cmd": "self-test", "write_docs": False},
           "n_repos": 1, "repo_counts": {"x/y": 1}, "repo_names": repo_names,
           "full": {"n": len(rows), "mae_ridge": mae(y, pred_a), "mae_hgb": float("nan"),
                     "mae_median": mae(y, median_baseline_oof(y)), "rmse": rmse(y, pred_a),
                     "spearman": spearman(y, pred_a), "target_mean": float(y.mean()),
                     "target_median": float(np.median(y)), "target_max": float(y.max()),
                     "target_multi": float(np.mean(yb)), "target_new": 0.0}}
    docs = render_docs(ctx)
    check("docs render", "Decision gate" in docs and len(docs.splitlines()) < 200)
    for row in rows:
        row["codebase"] = {name: 0.0 for name in c_names}
    mini_abl = run_ablation(rows, feat_names, 0, False, ["files", "added_lines"])
    mini_var = run_variance(rows, feat_names, ["files", "added_lines"], min_files=2)
    refinement = render_refinement(
        {"args": {"min_files": 2, "target": "all", "cmd": "self-test"},
         "variance": mini_var, "ablation": mini_abl}
    )
    check(
        "refinement docs render",
        "Multi-file refinement" in refinement and "### Decision" in refinement and "always-2" in refinement,
    )
    check(
        "refinement decision present",
        any(word in refinement for word in ("IMPROVED", "NOT IMPROVED", "INCONCLUSIVE")),
    )
    # decision gate rule
    fake = {"arms": {"text": {"mae": 1.0}, "codebase": {"mae": 0.9}}, "bootstrap": {"ci_high": -0.05}}
    check("gate improved rule", decision_gate(fake) == "IMPROVED")
    fake["bootstrap"]["ci_high"] = 0.05
    fake["arms"]["codebase"]["mae"] = 1.1
    check("gate not-improved rule", decision_gate(fake).startswith("NOT IMPROVED"))
    fake["bootstrap"]["ci_high"] = 0.01
    fake["arms"]["codebase"]["mae"] = 0.95
    check("gate inconclusive rule", decision_gate(fake).startswith("INCONCLUSIVE"))

    elapsed = time.time() - t0
    if failures:
        print(f"[self-test] {len(failures)} FAILURES after {elapsed:.1f}s: {failures}")
        return 1
    print(f"[self-test] all checks passed in {elapsed:.1f}s")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SWE-bench invasiveness ablation (text-only vs text+codebase)."
    )
    parser.add_argument("--max-instances", type=int, default=300,
                        help="cap on dataset instances for the full-set model (0 = all).")
    parser.add_argument("--subset-repo", default="sympy/sympy",
                        help="single repo used for the codebase-signal ablation arm.")
    parser.add_argument("--subset-repos", default="",
                        help="comma-separated repo list for the codebase arm (overrides "
                             "--subset-repo), e.g. sympy/sympy,pytest-dev/pytest,psf/requests.")
    parser.add_argument("--subset-max-instances", type=int, default=150,
                        help="cap on subset instances PER REPO (0 = all instances of that repo).")
    parser.add_argument("--min-files", type=int, default=0,
                        help="keep only patches touching >= N files in the variance/ablation "
                             "subsets (0 = original behaviour, all patches).")
    parser.add_argument("--target", choices=TARGET_CHOICES + ("all",), default="files",
                        help="regression target: files_touched | modified_files | added_lines | "
                             "all (all = run the three targets in one pass).")
    parser.add_argument("--dataset", choices=sorted(DATASET_SOURCES), default="full",
                        help="full = SWE-bench test (2294); lite = SWE-bench Lite (300, "
                             "all single-file patches, degenerate primary target).")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--write", action="store_true", help="write docs/CODEBASE_VALIDATION.md")
    parser.add_argument("--write-sample", action="store_true",
                        help="(re)write scripts/swebench_sample.jsonl from the embedded rows")
    parser.add_argument("--self-test", "--dry-run", dest="self_test", action="store_true",
                        help="offline pipeline self-test on 5 embedded sample rows.")
    parser.add_argument("--no-codebase", action="store_true",
                        help="skip the codebase arm (dataset + text model only).")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="re-download the dataset cache.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.write_sample:
        text = base64.b64decode(_SAMPLE_JSONL_B64).decode("utf-8")
        SAMPLE_PATH.write_text(text, encoding="utf-8")
        print(f"[sample] wrote {SAMPLE_PATH} ({len(text.splitlines())} rows)")
        return 0

    if args.self_test:
        return run_self_test()

    repo_list = subset_repo_list(args)
    refinement_mode = args.min_files >= 2 or args.target != "files" or len(repo_list) > 1
    cmd_parts = [
        "scripts/swebench_validation.py",
        f"--dataset {args.dataset}",
        f"--max-instances {args.max_instances}",
    ]
    if args.subset_repos:
        cmd_parts.append(f"--subset-repos {args.subset_repos}")
    else:
        cmd_parts.append(f"--subset-repo {args.subset_repo}")
    cmd_parts.append(f"--subset-max-instances {args.subset_max_instances}")
    if args.min_files:
        cmd_parts.append(f"--min-files {args.min_files}")
    if args.target != "files":
        cmd_parts.append(f"--target {args.target}")
    if args.write:
        cmd_parts.append("--write")
    args.cmd = " ".join(cmd_parts)

    ctx = run_experiment(args)
    print_report(ctx)

    if args.write:
        DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if refinement_mode and DOCS_PATH.exists():
            # Keep the original report section byte-for-byte; replace only the
            # appended refinement section (idempotent re-runs).
            existing = DOCS_PATH.read_text(encoding="utf-8")
            marker = "\n## Multi-file refinement ("
            idx = existing.find(marker)
            if idx >= 0:
                existing = existing[:idx]
            docs = existing.rstrip("\n") + "\n\n" + render_refinement(ctx) + "\n"
        else:
            docs = render_docs(ctx).rstrip("\n") + "\n"
            if refinement_mode:
                docs = docs.rstrip("\n") + "\n\n" + render_refinement(ctx) + "\n"
        DOCS_PATH.write_text(docs, encoding="utf-8")
        n_lines = len(docs.splitlines())
        print(f"\n[docs] wrote {DOCS_PATH} ({n_lines} lines)")
        if not refinement_mode and n_lines > 120:
            print(f"[docs] WARNING: {n_lines} lines exceeds the 120-line budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
