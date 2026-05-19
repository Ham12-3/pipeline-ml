"""Train the toy model, log everything to MLflow, register it, set the
`production` alias, and save the drift baseline.

Run from anywhere:  python ml/train.py
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow.tracking import MlflowClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path
from common import (  # noqa: E402
    MLFLOW_ARTIFACT_ROOT, MLFLOW_EXPERIMENT, MLFLOW_TRACKING_URI,
    MODEL_ALIAS, MODEL_NAME, RANDOM_SEED, git_sha, training_data,
)
from ml.baseline import save_baseline  # noqa: E402

PARAMS = dict(n_estimators=120, max_depth=8, random_state=RANDOM_SEED, n_jobs=-1)


def dataset_hash(X, y) -> str:
    return hashlib.sha256(X.tobytes() + y.tobytes()).hexdigest()[:16]


def ensure_experiment() -> None:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    if mlflow.get_experiment_by_name(MLFLOW_EXPERIMENT) is None:
        mlflow.create_experiment(MLFLOW_EXPERIMENT,
                                 artifact_location=MLFLOW_ARTIFACT_ROOT)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)


def main(bad: bool = False) -> None:
    X, y = training_data()
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_SEED, stratify=y)

    if bad:
        # Deliberately destroy the label signal so the model learns nothing
        # (~chance accuracy). Used to PROVE the canary auto-rollback fires.
        y_tr = np.random.default_rng(0).permutation(y_tr)

    model = RandomForestClassifier(**PARAMS).fit(X_tr, y_tr)
    preds = model.predict(X_te)
    acc = accuracy_score(y_te, preds)
    f1 = f1_score(y_te, preds)
    dhash = dataset_hash(X, y)
    sha = git_sha()

    ensure_experiment()
    with mlflow.start_run() as run:
        mlflow.log_params({**PARAMS, "n_samples": len(X),
                           "model": "RandomForest", "deliberately_bad": bad})
        mlflow.log_metrics({"accuracy": acc, "f1": f1})
        mlflow.set_tags({"git_sha": sha, "dataset_hash": dhash,
                         "quality": "bad" if bad else "good"})
        mlflow.sklearn.log_model(model, artifact_path="model",
                                 registered_model_name=MODEL_NAME)
        run_id = run.info.run_id

    client = MlflowClient()
    versions = client.search_model_versions(f"run_id='{run_id}'")
    version = max(int(v.version) for v in versions)
    client.set_registered_model_alias(MODEL_NAME, MODEL_ALIAS, version)

    save_baseline(X_tr)

    print("=" * 64)
    if bad:
        print("!! DELIBERATELY BAD MODEL (labels shuffled) -- for rollback demo")
    print(f"Trained RandomForest  accuracy={acc:.4f}  f1={f1:.4f}")
    print(f"MLflow run_id   : {run_id}")
    print(f"Registered model: {MODEL_NAME} v{version}  alias='{MODEL_ALIAS}'")
    print(f"git_sha={sha}  dataset_hash={dhash}")
    print(f"Tracking URI    : {MLFLOW_TRACKING_URI}")
    print("Baseline saved for drift detection.")
    print("=" * 64)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", action="store_true",
                    help="train a deliberately bad model (shuffled labels)")
    args = ap.parse_args()
    main(bad=args.bad or os.environ.get("TRAIN_BAD") == "1")
