"""Distillation experiment: LLM teacher -> small per-feature student classifiers.

Turns the spec §6.2 roadmap line ("Có thể thay thế LLM bằng classifier nhỏ hơn KHI
CÓ ĐỦ DỮ LIỆU") into a measured experiment on the 240 synthetic emails:

- ``--label``: the DeepSeek teacher labels every email through the production path
  ``extract_features`` (one outer retry per email; failed emails are skipped and
  written as all-empty rows). Writes ``data/distillation_labels.csv``
  (``project_id, email_sha1, <15 features>``; ``1``/``0``/empty where empty means
  "teacher said null/unknown or the call failed"). Resumes already-labeled rows
  when the email sha1 still matches; ``--relabel`` forces a fresh run.
- ``--train``: one student pipeline per feature — TF-IDF (word 1-2 grams,
  min_df=2, sublinear_tf) + LogisticRegression(max_iter=1000,
  class_weight="balanced") — trained on teacher labels. Teacher-null cells are
  *unknown* and excluded from that feature's training. Evaluates 5-fold
  out-of-fold CV (micro/macro precision/recall/F1, predicting value==True, null
  counts as a miss, same convention as ``docs/EXTRACTION_EVAL.md``), builds a
  30/60/120/180/240 learning curve on nested seeded subsets and saves
  ``data/distilled_model.joblib``.
- ``--write``: renders ``docs/DISTILLATION_EXPERIMENT.md`` (<=120 lines) from an
  HTML-comment payload so it can be re-rendered offline.

Run from ``backend/`` with ``PYTHONPATH=.`` and the project venv::

    /root/venvs/estimator/bin/python scripts/distillation_experiment.py --label --train --write
    /root/venvs/estimator/bin/python scripts/distillation_experiment.py --train --write  # offline

The student decision rule lives in ``app/services/distilled.py`` (p>=0.5 -> 1,
p<=0.4 -> 0, dead band -> null) and ``evidence_quote`` is always null: the
student does not generate text.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline

from app.features import FEATURES
from app.services.distilled import (
    ABSENT_THRESHOLD,
    PRESENT_THRESHOLD,
    MODEL_SCHEMA,
    decide_value,
    save_distilled_model,
)
from app.services.extraction import extract_features
from app.services.providers import StubProvider, get_provider, get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "data" / "synthetic_history.csv"
GT_PATH = REPO_ROOT / "data" / "ground_truth.json"
LABELS_PATH = REPO_ROOT / "data" / "distillation_labels.csv"
MODEL_PATH = REPO_ROOT / "data" / "distilled_model.joblib"
DOC_PATH = REPO_ROOT / "docs" / "DISTILLATION_EXPERIMENT.md"

FAILURE_MARKER = "Không thể trích xuất"  # extraction.py degrade-to-null warning
PAYLOAD_RE = re.compile(r"<!-- distillation-data\s*(\{.*\})\s*-->", re.DOTALL)
MAX_REPORT_LINES = 120

CHARS_PER_TOKEN = 4.0  # rough heuristic, labelled as such in the report
PRICING_PEAK_USD = (0.30, 1.20)  # USD per 1M tokens, in/out, DeepSeek Flash peak
PRICING_OFFPEAK_USD = (0.15, 0.60)  # USD per 1M tokens, off-peak

SEED = 42
CURVE_SIZES = (30, 60, 120, 180, 240)
MIN_TRAIN_SAMPLES = 4  # below this a feature has no student (abstains)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def sha1_file(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _div(num: float, den: float) -> float | None:
    return num / den if den else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _f(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def load_emails() -> list[dict[str, Any]]:
    """CSV emails joined with ground truth, in ground-truth order."""
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    with CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        rows = {record["project_id"]: record for record in csv.DictReader(handle)}
    projects: list[dict[str, Any]] = []
    for project_id, entry in gt["projects"].items():
        record = rows.get(project_id)
        if record is None:
            continue
        email = record["email_text"]
        projects.append(
            {
                "project_id": project_id,
                "email": email,
                "email_sha1": sha1_text(email),
                "truth": {name: int(entry["features"][name]) for name in FEATURES},
                "mentioned": list(entry.get("mentioned", [])),
                "omitted": list(entry.get("omitted", [])),
                "negated": list(entry.get("negated", [])),
            }
        )
    return projects


# --------------------------------------------------------------------------- #
# Label stage
# --------------------------------------------------------------------------- #


class MeteredProvider:
    """Wraps an LLMProvider and counts prompt/response characters."""

    def __init__(self, inner: Any, name: str) -> None:
        self.inner = inner
        self.name = name
        self.calls = 0
        self.errors = 0
        self.in_chars = 0
        self.out_chars = 0

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        self.calls += 1
        self.in_chars += len(prompt) + (len(system) if system else 0)
        try:
            data = self.inner.complete_json(prompt, system)
        except BaseException:
            self.errors += 1
            raise
        self.out_chars += len(json.dumps(data, ensure_ascii=False))
        return data


def write_labels_csv(rows: list[dict[str, Any]]) -> None:
    # Atomic replace: a crash mid-write must never truncate already-labeled rows.
    tmp_path = LABELS_PATH.parent / (LABELS_PATH.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["project_id", "email_sha1", *FEATURES])
        for row in rows:
            writer.writerow(
                [row["project_id"], row["email_sha1"], *[row["labels"][n] for n in FEATURES]]
            )
    os.replace(tmp_path, LABELS_PATH)


def load_labels_rows() -> dict[str, dict[str, Any]]:
    """Existing labels CSV keyed by project_id (used for resume and training)."""
    if not LABELS_PATH.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with LABELS_PATH.open("r", encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            out[record["project_id"]] = {
                "project_id": record["project_id"],
                "email_sha1": (record.get("email_sha1") or "").strip(),
                "labels": {name: (record.get(name) or "").strip() for name in FEATURES},
            }
    return out


def run_label_stage(limit: int | None = None, relabel: bool = False) -> dict[str, Any]:
    """Label every email with the DeepSeek teacher; one outer retry, then skip."""
    projects = load_emails()
    if limit:
        projects = projects[:limit]
    provider, actual_name = get_provider("deepseek")
    if actual_name != "deepseek":
        raise SystemExit(
            f"Requested 'deepseek' but the factory fell back to '{actual_name}' "
            "(missing/unusable key). Refusing to label with the wrong teacher."
        )
    settings = get_settings()
    metered = MeteredProvider(provider, actual_name)
    existing = load_labels_rows()

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    resumed = 0
    started = time.perf_counter()
    for index, project in enumerate(projects, 1):
        project_id = project["project_id"]
        previous = existing.get(project_id)
        if (
            not relabel
            and previous
            and previous["email_sha1"] == project["email_sha1"]
            and any(previous["labels"].values())
        ):
            rows.append(previous)
            resumed += 1
            print(f"[{index}/{len(projects)}] {project_id} resumed", file=sys.stderr, flush=True)
            continue
        result = extract_features(project["email"], provider=(metered, actual_name))
        failed = any(FAILURE_MARKER in warning for warning in result.warnings)
        if failed:  # exactly one outer retry, then skip (same policy as extraction_eval)
            result = extract_features(project["email"], provider=(metered, actual_name))
            failed = any(FAILURE_MARKER in warning for warning in result.warnings)
        labels = {name: "" for name in FEATURES}
        if failed:
            skipped.append(project_id)
        else:
            for finding in result.findings:
                if finding.value is not None:
                    labels[finding.name] = "1" if finding.value else "0"
        rows.append(
            {"project_id": project_id, "email_sha1": project["email_sha1"], "labels": labels}
        )
        write_labels_csv(rows)  # incremental: a crash never loses labeled emails
        print(
            f"[{index}/{len(projects)}] {project_id} "
            f"{'FAILED (skipped)' if failed else 'ok'}",
            file=sys.stderr,
            flush=True,
        )

    total_seconds = time.perf_counter() - started
    in_tokens = metered.in_chars / CHARS_PER_TOKEN
    out_tokens = metered.out_chars / CHARS_PER_TOKEN
    return {
        "date": now_utc(),
        "teacher": actual_name,
        "teacher_model": settings.deepseek_model,
        "n_projects": len(projects),
        "n_labeled": len(projects) - len(skipped),
        "n_skipped": len(skipped),
        "skipped_ids": skipped,
        "n_resumed": resumed,
        "provider_calls": metered.calls,
        "provider_errors": metered.errors,
        "total_seconds": total_seconds,
        "avg_seconds": total_seconds / len(projects) if projects else None,
        "in_tokens_total": in_tokens,
        "out_tokens_total": out_tokens,
        "est_cost_peak_usd": in_tokens / 1e6 * PRICING_PEAK_USD[0]
        + out_tokens / 1e6 * PRICING_PEAK_USD[1],
        "est_cost_offpeak_usd": in_tokens / 1e6 * PRICING_OFFPEAK_USD[0]
        + out_tokens / 1e6 * PRICING_OFFPEAK_USD[1],
        "labels_sha1": sha1_file(LABELS_PATH),
        "csv_sha1": sha1_file(CSV_PATH),
        "gt_sha1": sha1_file(GT_PATH),
    }


# --------------------------------------------------------------------------- #
# Student training + evaluation
# --------------------------------------------------------------------------- #


def build_pipeline(seed: int = SEED) -> Pipeline:
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True),
            ),
            (
                "clf",
                LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed),
            ),
        ]
    )


def train_feature_pipeline(
    emails: list[str], labels: list[int | None], seed: int = SEED
) -> Pipeline | None:
    """Fit one student on teacher non-null labels; None when untrainable."""
    indices = [i for i, value in enumerate(labels) if value is not None]
    targets = [labels[i] for i in indices]
    if len(indices) < MIN_TRAIN_SAMPLES or len(set(targets)) < 2:
        return None
    pipeline = build_pipeline(seed)
    pipeline.fit([emails[i] for i in indices], targets)
    return pipeline


def cv_predictions(
    emails: list[str], labels: list[int | None], seed: int = SEED
) -> list[float | None]:
    """Out-of-fold P(present) per email; None where no fold could train.

    Folds are stratified over all emails (teacher-null = class 2) so that
    teacher-null rows are *predicted on* (they count against precision when the
    student asserts presence) but never trained on.
    """
    predictions: list[float | None] = [None] * len(emails)
    n_pos = sum(1 for value in labels if value == 1)
    n_neg = sum(1 for value in labels if value == 0)
    n_unknown = len(labels) - n_pos - n_neg
    limits = [5, n_pos, n_neg] + ([n_unknown] if n_unknown else [])
    n_splits = min(limits)
    if n_splits < 2:
        return predictions
    stratified = [2 if value is None else value for value in labels]
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for train_idx, test_idx in splitter.split(emails, stratified):
        pipeline = train_feature_pipeline(
            [emails[i] for i in train_idx], [labels[i] for i in train_idx], seed
        )
        if pipeline is None:
            continue
        try:
            probabilities = pipeline.predict_proba([emails[i] for i in test_idx])
            column = list(pipeline.classes_).index(1)
        except Exception:  # pragma: no cover - defensive
            continue
        for row, email_index in enumerate(test_idx):
            predictions[email_index] = float(probabilities[row][column])
    return predictions


def decide_list(predictions: list[float | None]) -> list[bool | None]:
    return [decide_value(p)[0] for p in predictions]


def present_metrics(
    pred: dict[str, list[bool | None]], truth: dict[str, list[int | None]]
) -> dict[str, Any]:
    """Micro/macro precision/recall/F1 for predicting value==True (null = miss)."""
    per_feature: dict[str, dict[str, Any]] = {}
    micro_tp = micro_fp = micro_fn = 0
    for name in FEATURES:
        tp = fp = fn = n_true = 0
        for value, target in zip(pred[name], truth[name]):
            if target == 1:
                n_true += 1
                if value is True:
                    tp += 1
                else:
                    fn += 1
            elif value is True:
                fp += 1
        precision = _div(tp, tp + fp)
        recall = _div(tp, n_true)
        per_feature[name] = {
            "n_true": n_true,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
        }
        micro_tp += tp
        micro_fp += fp
        micro_fn += fn
    micro_precision = _div(micro_tp, micro_tp + micro_fp)
    micro_recall = _div(micro_tp, micro_tp + micro_fn)

    def macro(key: str) -> float | None:
        values = [per_feature[n][key] for n in FEATURES if per_feature[n][key] is not None]
        return fmean(values) if values else None

    return {
        "per_feature": per_feature,
        "micro": {
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": _f1(micro_precision, micro_recall),
            "tp": micro_tp,
            "fp": micro_fp,
            "fn": micro_fn,
        },
        "macro": {
            "precision": macro("precision"),
            "recall": macro("recall"),
            "f1": macro("f1"),
        },
    }


def agreement_stats(
    pred: dict[str, list[bool | None]], truth: dict[str, list[int | None]]
) -> dict[str, Any]:
    """Emission mix and exact cell agreement (1/0/null) against a reference."""
    emit_one = emit_zero = emit_null = 0
    agree = 0
    total = 0
    truth_zero_total = truth_zero_correct = 0
    truth_null_total = truth_null_correct = 0
    for name in FEATURES:
        for value, target in zip(pred[name], truth[name]):
            total += 1
            if value is True:
                emit_one += 1
            elif value is False:
                emit_zero += 1
            else:
                emit_null += 1
            reference = None if target is None else bool(target)
            if value == reference:
                agree += 1
            if target == 0:
                truth_zero_total += 1
                truth_zero_correct += int(value is False)
            elif target is None:
                truth_null_total += 1
                truth_null_correct += int(value is None)
    return {
        "cells": total,
        "agree": agree,
        "agree_rate": _div(agree, total),
        "emit_one": emit_one,
        "emit_zero": emit_zero,
        "emit_null": emit_null,
        "emit_one_rate": _div(emit_one, total),
        "emit_zero_rate": _div(emit_zero, total),
        "emit_null_rate": _div(emit_null, total),
        "truth_zero_total": truth_zero_total,
        "truth_zero_recall": _div(truth_zero_correct, truth_zero_total),
        "truth_null_total": truth_null_total,
        "truth_null_recall": _div(truth_null_correct, truth_null_total),
    }


def behavior_stats(
    pred: dict[str, list[bool | None]], projects: list[dict[str, Any]]
) -> dict[str, Any]:
    """EXTRACTION_EVAL-style unknown/negation/wrongly-absent behaviour vs GT."""
    omitted_total = unknown_ok = 0
    negated_total = zero_ok = 0
    mentioned_total = wrongly_false = wrongly_null = 0
    for index, project in enumerate(projects):
        for name in project["omitted"]:
            omitted_total += 1
            unknown_ok += int(pred[name][index] is None)
        for name in project["negated"]:
            negated_total += 1
            zero_ok += int(pred[name][index] is False)
        for name in project["mentioned"]:
            mentioned_total += 1
            if pred[name][index] is False:
                wrongly_false += 1
            elif pred[name][index] is None:
                wrongly_null += 1
    return {
        "unknown_accuracy": _div(unknown_ok, omitted_total),
        "omitted_total": omitted_total,
        "unknown_ok": unknown_ok,
        "negation_accuracy": _div(zero_ok, negated_total),
        "negated_total": negated_total,
        "negation_ok": zero_ok,
        "mentioned_total": mentioned_total,
        "wrongly_false": wrongly_false,
        "wrongly_null": wrongly_null,
        "wrongly_false_fraction": _div(wrongly_false, mentioned_total),
    }


def stub_predictions(emails: list[str]) -> dict[str, list[bool | None]]:
    stub = StubProvider()
    per_feature: dict[str, list[bool | None]] = {name: [] for name in FEATURES}
    for email in emails:
        findings = stub.extract_findings(email)
        for name in FEATURES:
            value = findings[name]["value"]
            # StubProvider returns int 1/0/None; normalize to bool|None like the provider JSON.
            per_feature[name].append(None if value is None else bool(value))
    return per_feature


def fit_power_law(
    sizes: list[int], values: list[float | None]
) -> dict[str, Any] | None:
    """Rough fit y = a - b * n^(-c); None when the fit is not usable."""
    import numpy as np
    from scipy.optimize import curve_fit

    points = [(n, v) for n, v in zip(sizes, values) if v is not None]
    if len(points) < 3:
        return None
    xs = np.array([n for n, _ in points], dtype=float)
    ys = np.array([v for _, v in points], dtype=float)
    if float(np.ptp(ys)) < 1e-6:
        return {"asymptote": float(ys[0]), "b": 0.0, "c": 0.0, "note": "flat curve"}
    try:
        popt, _ = curve_fit(
            lambda n, a, b, c: a - b * np.power(n, -c),
            xs,
            ys,
            p0=[1.0, 1.0 - float(ys[0]), 0.5],
            maxfev=20000,
        )
    except Exception:
        return None
    a, b, c = (float(x) for x in popt)
    if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(c)) or b <= 0 or c <= 0:
        return None
    return {"asymptote": a, "b": b, "c": c, "note": "power law y = a - b*n^-c"}


def samples_for_target(fit: dict[str, Any] | None, target: float | None) -> float | None:
    """Estimate n where the fitted curve reaches ``target``; None if not reachable."""
    if not fit or target is None:
        return None
    a, b, c = fit.get("asymptote"), fit.get("b"), fit.get("c")
    if not a or not b or not c or a <= target:
        return None
    estimate = (b / (a - target)) ** (1.0 / c)
    return estimate if estimate == estimate and estimate != float("inf") else None


def run_train_stage(label_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Train students, evaluate CV + learning curve, save the model artifact."""
    projects = load_emails()
    label_rows = load_labels_rows()
    emails = [project["email"] for project in projects]
    n_emails = len(projects)

    gt = {name: [project["truth"][name] for project in projects] for name in FEATURES}
    teacher: dict[str, list[int | None]] = {name: [] for name in FEATURES}
    label_counts = {name: {"n_pos": 0, "n_neg": 0, "n_unknown": 0} for name in FEATURES}
    mismatched_projects: list[str] = []
    for project in projects:
        row = label_rows.get(project["project_id"])
        if row and row["email_sha1"] != project["email_sha1"]:
            mismatched_projects.append(project["project_id"])
        for name in FEATURES:
            token = row["labels"][name] if row else ""
            if token in ("0", "1"):
                value: int | None = int(token)
                label_counts[name]["n_pos" if value else "n_neg"] += 1
            else:
                value = None
                label_counts[name]["n_unknown"] += 1
            teacher[name].append(value)

    # Full-data 5-fold CV: out-of-fold student predictions for every email.
    student_values: dict[str, list[bool | None]] = {}
    for name in FEATURES:
        student_values[name] = decide_list(cv_predictions(emails, teacher[name]))

    teacher_pred = {
        name: [None if value is None else bool(value) for value in teacher[name]]
        for name in FEATURES
    }
    stub_pred = stub_predictions(emails)

    headline = {
        "stub_gt": present_metrics(stub_pred, gt),
        "teacher_gt": present_metrics(teacher_pred, gt),
        "student_gt": present_metrics(student_values, gt),
        "student_teacher": present_metrics(student_values, teacher),
        "stub_behavior": behavior_stats(stub_pred, projects),
        "teacher_behavior": behavior_stats(teacher_pred, projects),
        "student_behavior": behavior_stats(student_values, projects),
        "student_teacher_agreement": agreement_stats(student_values, teacher),
    }

    # Learning curve on nested seeded subsets.
    order = random.Random(SEED).sample(range(n_emails), n_emails)
    sizes = sorted({size for size in CURVE_SIZES if size < n_emails} | {n_emails})
    curve: list[dict[str, Any]] = []
    for size in sizes:
        indices = order[:size]
        subset_emails = [emails[i] for i in indices]
        subset_teacher = {name: [teacher[name][i] for i in indices] for name in FEATURES}
        subset_gt = {name: [gt[name][i] for i in indices] for name in FEATURES}
        subset_values: dict[str, list[bool | None]] = {}
        for name in FEATURES:
            subset_values[name] = decide_list(
                cv_predictions(subset_emails, subset_teacher[name])
            )
        fidelity = present_metrics(subset_values, subset_teacher)
        quality = present_metrics(subset_values, subset_gt)
        agreement = agreement_stats(subset_values, subset_teacher)
        curve.append(
            {
                "n": size,
                "fidelity_micro_f1": fidelity["micro"]["f1"],
                "fidelity_macro_f1": fidelity["macro"]["f1"],
                "quality_micro_f1": quality["micro"]["f1"],
                "quality_macro_f1": quality["macro"]["f1"],
                "agreement_rate": agreement["agree_rate"],
                "emit_one_rate": agreement["emit_one_rate"],
                "emit_zero_rate": agreement["emit_zero_rate"],
                "emit_null_rate": agreement["emit_null_rate"],
            }
        )

    extrapolation = {
        "quality": fit_power_law(sizes, [row["quality_micro_f1"] for row in curve]),
        "fidelity": fit_power_law(sizes, [row["fidelity_micro_f1"] for row in curve]),
    }

    # Final artifact: one pipeline per feature trained on all available labels.
    pipelines: dict[str, Any] = {}
    for name in FEATURES:
        pipelines[name] = train_feature_pipeline(emails, teacher[name])

    settings = get_settings()
    model = {
        "schema": MODEL_SCHEMA,
        "metadata": {
            "created_utc": now_utc(),
            "teacher": {
                "provider": label_meta["teacher"] if label_meta else "deepseek",
                "model": label_meta["teacher_model"] if label_meta else settings.deepseek_model,
            },
            "n_emails": n_emails,
            "n_skipped_projects": label_meta["n_skipped"] if label_meta else None,
            "seed": SEED,
            "thresholds": {"present": PRESENT_THRESHOLD, "absent": ABSENT_THRESHOLD},
            "student": "tfidf word 1-2 grams min_df=2 sublinear_tf + logistic regression max_iter=1000 class_weight=balanced",
            "label_counts": label_counts,
            "cv_micro_f1_vs_teacher": headline["student_teacher"]["micro"]["f1"],
            "cv_micro_f1_vs_gt": headline["student_gt"]["micro"]["f1"],
            "csv_sha1": sha1_file(CSV_PATH),
            "gt_sha1": sha1_file(GT_PATH),
            "labels_sha1": sha1_file(LABELS_PATH),
        },
        "pipelines": pipelines,
    }
    save_distilled_model(model, MODEL_PATH)

    return {
        "date": now_utc(),
        "n_emails": n_emails,
        "n_features_trained": sum(1 for pipe in pipelines.values() if pipe is not None),
        "label_counts": label_counts,
        "email_sha1_mismatches": mismatched_projects,
        "headline": headline,
        "curve": curve,
        "extrapolation": extrapolation,
        "model_path": str(MODEL_PATH.relative_to(REPO_ROOT))
        if MODEL_PATH.is_relative_to(REPO_ROOT)
        else str(MODEL_PATH),
        "model_bytes": MODEL_PATH.stat().st_size,
        "labels_sha1": sha1_file(LABELS_PATH),
        "csv_sha1": sha1_file(CSV_PATH),
        "gt_sha1": sha1_file(GT_PATH),
        "seed": SEED,
        "teacher_model": label_meta["teacher_model"] if label_meta else settings.deepseek_model,
    }


# --------------------------------------------------------------------------- #
# Report rendering
# --------------------------------------------------------------------------- #


def load_payload() -> dict[str, Any]:
    if not DOC_PATH.exists():
        return {}
    match = PAYLOAD_RE.search(DOC_PATH.read_text(encoding="utf-8"))
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _decision_lines(payload: dict[str, Any]) -> list[str]:
    train = payload["train"]
    headline = train["headline"]
    student = headline["student_gt"]["micro"]["f1"]
    teacher = headline["teacher_gt"]["micro"]["f1"]
    stub = headline["stub_gt"]["micro"]["f1"]
    fidelity = headline["student_teacher"]["micro"]["f1"]
    agreement = headline["student_teacher_agreement"]
    curve = train["curve"]
    fit = train["extrapolation"].get("quality")
    lines = [
        "## Decision (honest)",
        "",
        f"- At n={train['n_emails']} the student reaches micro-F1 {_f(student)} vs ground truth "
        f"(teacher {_f(teacher)}, stub {_f(stub)}); fidelity to the teacher's own labels is "
        f"{_f(fidelity)} with {_pct(agreement['agree_rate'])} exact cell agreement.",
    ]
    if len(curve) >= 2 and None not in (
        curve[-1]["quality_micro_f1"],
        curve[-2]["quality_micro_f1"],
    ):
        delta = curve[-1]["quality_micro_f1"] - curve[-2]["quality_micro_f1"]
        trend = "still improving" if delta > 0.01 else "roughly plateaued"
        lines.append(
            f"- Curve from n={curve[-2]['n']} to n={curve[-1]['n']}: quality micro-F1 "
            f"{delta:+.3f} -> {trend}."
        )
    if fit:
        estimate = samples_for_target(fit, teacher)
        lines.append(
            f"- Rough power-law fit (single seed, {len(curve)} points): asymptote "
            f"{_f(fit['asymptote'])} vs GT."
        )
        if estimate is None:
            lines.append(
                f"- The fit does not reach the teacher's {_f(teacher)} within this model class: "
                '"đủ dữ liệu" for LLM parity is NOT demonstrated at 240 emails — more (and more '
                "varied) emails, or a stronger student, are needed. Estimate only."
            )
        elif estimate <= 10000:
            lines.append(
                f"- Reaching teacher parity ({_f(teacher)}) would need ~{estimate:.0f} "
                f"teacher-labeled emails (estimate only; single seed, 5 curve points)."
            )
        else:
            lines.append(
                f"- Reaching teacher parity ({_f(teacher)}) would need ~{estimate:.0f} emails — "
                "beyond any practical budget for this corpus. Estimate only."
            )
    else:
        lines.append("- Power-law extrapolation not usable for this curve (too few/noisy points).")
    lines.append(
        '- "Đủ dữ liệu" here means enough teacher-labeled emails to match the LLM on THIS '
        "synthetic template corpus; it is a lower bound only — real RFPs are more varied."
    )
    lines.append("")
    return lines


def render_markdown(payload: dict[str, Any], include_payload: bool) -> str:
    label = payload.get("label")
    train = payload.get("train")
    lines: list[str] = [
        "# Distillation: LLM teacher -> small student extractors",
        "",
        f"Generated by `backend/scripts/distillation_experiment.py` on {now_utc()}.",
        "Spec §6.2 roadmap line (\"Có thể thay thế LLM bằng classifier nhỏ hơn KHI CÓ ĐỦ",
        "DỮ LIỆU\") measured: the DeepSeek teacher labels all synthetic emails, per-feature",
        "students train on those labels, and a learning curve shows what \"đủ dữ liệu\" costs.",
        "",
        "## Method",
        "",
        "- Teacher: `deepseek-flash` via the production path `extract_features`; one outer retry",
        "  per email; failed emails are skipped (empty label row, listed below).",
        "- Student: one binary pipeline per feature — `TfidfVectorizer(word 1-2 grams, min_df=2,",
        "  sublinear_tf=True)` + `LogisticRegression(max_iter=1000, class_weight=balanced)`.",
        "  Teacher-null cells (\"not mentioned\") are *unknown* and excluded from that feature's training.",
        "- Decision rule: p=P(present); p>=0.5 -> 1 (confidence p); p<=0.4 -> 0 (confidence 1-p);",
        "  0.4<p<0.5 -> null (abstain). `evidence_quote` is always null — no generation, no fabrication.",
        "- Runtime usage: set `LLM_PROVIDER=distilled` (or `get_provider(\"distilled\")`); if the model",
        "  file is missing the factory logs a warning and falls back to the offline stub provider.",
        "- Metrics: predicting value==True, null counts as a miss (same convention as",
        "  `docs/EXTRACTION_EVAL.md`); 5-fold out-of-fold CV, micro pooled / macro averaged.",
        "- Learning curve: nested seeded subsets (seed 42) of 30/60/120/180/240 emails, same CV.",
        "",
        "## Teacher labels (`data/distillation_labels.csv`)",
        "",
    ]
    if label:
        lines += [
            f"- Labeled {label['n_labeled']}/{label['n_projects']} emails "
            f"(skipped: {', '.join(label['skipped_ids']) if label['skipped_ids'] else 'none'}"
            f"{f'; resumed: {label['n_resumed']}' if label['n_resumed'] else ''}) "
            f"in {label['total_seconds'] / 60:.1f} min, {label['provider_calls']} provider calls "
            f"({label['provider_errors']} errors).",
            f"- Est. cost ${label['est_cost_peak_usd']:.4f} peak / "
            f"${label['est_cost_offpeak_usd']:.4f} off-peak (chars/4 heuristic).",
            f"- sha1: emails `{label['csv_sha1']}`, ground_truth `{label['gt_sha1']}`, "
            f"labels `{label['labels_sha1']}`; teacher model `{label['teacher_model']}`.",
        ]
    else:
        lines.append("- No label-stage metadata in this payload; counts below are from the CSV.")
    lines.append("")

    if not train:
        lines += ["_Training results pending (run `--train --write`)._", ""]
        if include_payload:
            lines += ["<!-- distillation-data " + json.dumps(payload, ensure_ascii=False, sort_keys=True) + " -->"]
        return "\n".join(lines)

    headline = train["headline"]

    def headline_row(label_text: str, metric: str, block_key: str) -> str:
        cells = []
        for system in ("stub_gt", "teacher_gt", "student_gt"):
            cells.append(_f(headline[system][metric][block_key]))
        return f"| {label_text} | " + " | ".join(cells) + " |"

    agreement = headline["student_teacher_agreement"]
    lines += [
        "## Student vs teacher vs stub (5-fold CV, all "
        f"{train['n_emails']} emails, current data revision)",
        "",
        "| metric | stub | deepseek teacher | distilled student |",
        "|---|--:|--:|--:|",
        headline_row("micro precision", "micro", "precision"),
        headline_row("micro recall", "micro", "recall"),
        headline_row("micro F1", "micro", "f1"),
        headline_row("macro F1", "macro", "f1"),
        "| TP / FP / FN ("
        + f"{train['n_emails'] * len(FEATURES)} cells)"
        + " | "
        + " | ".join(
            f"{headline[system]['micro']['tp']} / {headline[system]['micro']['fp']} / "
            f"{headline[system]['micro']['fn']}"
            for system in ("stub_gt", "teacher_gt", "student_gt")
        )
        + " |",
        "| unknown-accuracy on omitted | "
        + " | ".join(
            f"{_pct(headline[key]['unknown_accuracy'])} "
            f"({headline[key]['unknown_ok']}/{headline[key]['omitted_total']})"
            for key in ("stub_behavior", "teacher_behavior", "student_behavior")
        )
        + " |",
        "| negation accuracy (negated -> 0) | "
        + " | ".join(
            f"{_pct(headline[key]['negation_accuracy'])} "
            f"({headline[key]['negation_ok']}/{headline[key]['negated_total']})"
            for key in ("stub_behavior", "teacher_behavior", "student_behavior")
        )
        + " |",
        "| wrongly asserted 0 on mentioned | "
        + " | ".join(
            f"{_pct(headline[key]['wrongly_false_fraction'])} "
            f"({headline[key]['wrongly_false']}/{headline[key]['mentioned_total']})"
            for key in ("stub_behavior", "teacher_behavior", "student_behavior")
        )
        + " |",
        f"| student-teacher exact agreement | — | — | {_pct(agreement['agree_rate'])} "
        f"({agreement['agree']}/{agreement['cells']}) |",
        "",
        "## Learning curve (student, out-of-fold CV)",
        "",
        "| n emails | fidelity micro-F1 (vs teacher labels) | quality micro-F1 (vs GT) "
        "| quality macro-F1 | agreement | emitted 1 / 0 / null |",
        "|--:|--:|--:|--:|--:|--:|",
    ]
    for row in train["curve"]:
        lines.append(
            f"| {row['n']} | {_f(row['fidelity_micro_f1'])} | {_f(row['quality_micro_f1'])} "
            f"| {_f(row['quality_macro_f1'])} | {_pct(row['agreement_rate'])} "
            f"| {_pct(row['emit_one_rate'])} / {_pct(row['emit_zero_rate'])} "
            f"/ {_pct(row['emit_null_rate'])} |"
        )
    lines.append("")

    lines += _decision_lines(payload)

    lines += [
        "## Per feature (n=240, out-of-fold CV)",
        "",
        "| feature | teacher F1 vs GT | stub F1 vs GT | student F1 vs GT | student fidelity F1 "
        "| labels 1/0/unknown |",
        "|---|--:|--:|--:|--:|--:|",
    ]
    for name in FEATURES:
        counts = train["label_counts"][name]
        lines.append(
            f"| {name} | {_f(headline['teacher_gt']['per_feature'][name]['f1'])} "
            f"| {_f(headline['stub_gt']['per_feature'][name]['f1'])} "
            f"| {_f(headline['student_gt']['per_feature'][name]['f1'])} "
            f"| {_f(headline['student_teacher']['per_feature'][name]['f1'])} "
            f"| {counts['n_pos']}/{counts['n_neg']}/{counts['n_unknown']} |"
        )
    lines.append("")

    lines += [
        "## Limitations",
        "",
        "- Emails are synthetic and template-generated (docs/DECISIONS.md D4): the student may",
        "  exploit template vocabulary/style; a replacement claim for real RFPs needs real emails.",
        "- Labels are teacher output, not ground truth: teacher errors propagate; fidelity is capped",
        "  by the teacher's own consistency, quality by teacher quality.",
        "- Unknown handling: teacher-null cells are excluded from training; features with too few",
        "  labels have no student and abstain (value null). Explicit negation (0) is rare per feature.",
        "- Single seed for subsets/CV; one teacher sample (temperature 0 is not bit-stable); the",
        "  power-law extrapolation is indicative only.",
        "- The student emits no evidence quotes (evidence_quote=null); the UI must show that.",
    ]
    if train.get("email_sha1_mismatches"):
        lines.append(
            f"- WARNING: {len(train['email_sha1_mismatches'])} label rows were written on a "
            "different email revision and were treated as unknown: "
            + ", ".join(train["email_sha1_mismatches"][:10])
            + "."
        )
    if include_payload:
        lines += [
            "",
            "<!-- distillation-data "
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
            + " -->",
        ]
    return "\n".join(lines)


def save_report(payload: dict[str, Any]) -> None:
    markdown = render_markdown(payload, include_payload=True)
    DOC_PATH.write_text(markdown + "\n", encoding="utf-8")
    line_count = len(markdown.splitlines())
    print(f"wrote {DOC_PATH.relative_to(REPO_ROOT)} ({line_count} lines)", flush=True)
    if line_count > MAX_REPORT_LINES:
        print(f"WARNING: report has {line_count} lines (> {MAX_REPORT_LINES})", file=sys.stderr)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", action="store_true", help="run the DeepSeek teacher (API cost)")
    parser.add_argument("--train", action="store_true", help="train students + curve + save model")
    parser.add_argument("--write", action="store_true", help=f"render {DOC_PATH.name}")
    parser.add_argument("--relabel", action="store_true", help="ignore existing labels and relabel")
    parser.add_argument("--limit", type=int, default=None, help="cap emails in the label stage")
    args = parser.parse_args(argv)
    if not (args.label or args.train):  # offline default: retrain + re-render from labels
        args.train = True
        args.write = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = load_payload()
    payload["data"] = {"csv_sha1": sha1_file(CSV_PATH), "gt_sha1": sha1_file(GT_PATH)}

    if args.label:
        print(f"label stage: teacher=deepseek limit={args.limit or 'all'}", flush=True)
        payload["label"] = run_label_stage(limit=args.limit, relabel=args.relabel)
        payload["data"]["labels_sha1"] = payload["label"]["labels_sha1"]
        print(
            f"labels: {payload['label']['n_labeled']} labeled, "
            f"{payload['label']['n_skipped']} skipped, "
            f"{payload['label']['total_seconds'] / 60:.1f} min",
            flush=True,
        )
        if args.write:
            save_report(payload)

    if args.train:
        print("train stage: per-feature TF-IDF + logistic regression", flush=True)
        payload["train"] = run_train_stage(payload.get("label"))
        train = payload["train"]
        print(
            f"student: {train['n_features_trained']}/15 features trained, "
            f"micro-F1 vs teacher {_f(train['headline']['student_teacher']['micro']['f1'])}, "
            f"vs GT {_f(train['headline']['student_gt']['micro']['f1'])} "
            f"(teacher {_f(train['headline']['teacher_gt']['micro']['f1'])}, "
            f"stub {_f(train['headline']['stub_gt']['micro']['f1'])})",
            flush=True,
        )
        print(
            f"model: {train['model_path']} ({train['model_bytes'] / 1024:.0f} KiB)",
            flush=True,
        )

    if args.write and (args.label or args.train):
        save_report(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
