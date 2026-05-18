"""Batch drift job.

Reads the most recent predictions from the SQLite prediction log, compares each
feature against the saved training baseline using PSI + KS, and prints a report.
In M0 it just prints a number; in M4 it will push that number to Prometheus so
Argo Rollouts can auto-roll-back on it.

Run from repo root:  python services/drift_job/drift_job.py --limit 1000
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path
from common import FEATURE_NAMES, PRED_DB  # noqa: E402
from ml.baseline import load_baseline  # noqa: E402
from ml.drift_metrics import feature_drift_report  # noqa: E402


def recent_features(limit: int) -> np.ndarray:
    if not PRED_DB.exists():
        raise FileNotFoundError(f"{PRED_DB} not found -- send some /predict traffic first.")
    with sqlite3.connect(PRED_DB) as con:
        rows = con.execute(
            "SELECT features FROM predictions ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    if not rows:
        raise SystemExit("No predictions logged yet.")
    return np.array([json.loads(r[0]) for r in rows], dtype=float)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000,
                    help="how many recent predictions to analyse")
    args = ap.parse_args()

    baseline = load_baseline()
    current = recent_features(args.limit)
    report = feature_drift_report(baseline, current, FEATURE_NAMES)

    print(f"\nDrift report  (baseline n={len(baseline)}, current n={len(current)})")
    print("-" * 64)
    print(f"{'feature':<8}{'PSI':>10}{'KS stat':>10}{'KS p':>10}  verdict")
    worst = 0.0
    for fd in report:
        worst = max(worst, fd.psi)
        print(f"{fd.feature:<8}{fd.psi:>10.4f}{fd.ks_stat:>10.4f}"
              f"{fd.ks_pvalue:>10.4f}  {fd.verdict}")
    print("-" * 64)

    overall = ("DRIFT DETECTED (significant)" if worst >= 0.2
               else "moderate drift" if worst >= 0.1
               else "stable")
    print(f"RESULT: max PSI = {worst:.4f}  ->  {overall}\n")


if __name__ == "__main__":
    main()
