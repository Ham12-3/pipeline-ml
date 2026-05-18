"""Provenance helper: given an MLflow run_id (stamped on every prediction),
return HOW that model was made — params, metrics, the git commit, and the
dataset fingerprint. This is the "training" half of a lineage receipt; the
"serving" half (the prediction row) comes from db.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient

sys.path.insert(0, str(Path(__file__).resolve().parent))  # repo root on path
from common import MLFLOW_TRACKING_URI  # noqa: E402


def run_provenance(run_id: str) -> dict | None:
    """Training-run provenance for `run_id`, or None if the run is missing."""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    try:
        run = MlflowClient().get_run(run_id)
    except Exception:
        return None
    data, info = run.data, run.info
    return {
        "run_id": run_id,
        "experiment_id": info.experiment_id,
        "status": info.status,
        "params": dict(data.params),       # n_estimators, max_depth, n_samples…
        "metrics": dict(data.metrics),     # accuracy, f1
        "git_sha": data.tags.get("git_sha"),
        "dataset_hash": data.tags.get("dataset_hash"),
    }
