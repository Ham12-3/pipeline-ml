"""Shared configuration and helpers for pipeline-ml.

Everything here is computed relative to THIS file's location, so every script
works the same no matter which directory you run it from. Keeping one source of
truth for paths/feature names avoids training-serving skew (the #1 silent ML
failure) inside our own project.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.datasets import make_classification

# --- Paths (CWD-independent) -------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent

# --- Config: env var wins, local default preserves M0 behavior ---------------
# Every infrastructure location is read from an environment variable. With NO
# env vars set this is byte-for-byte the old M0 setup (local SQLite files), so
# `python ml/train.py` still works on a bare laptop. Docker Compose sets these
# vars to point the SAME code at Postgres + a real MLflow server instead.
# Nothing about *where data lives* is hardcoded anymore.

# Drift baseline lives here. In containers this is a shared volume so the
# train job and the drift job see the same file.
ARTIFACTS_DIR = Path(os.environ.get("PIPELINE_ARTIFACTS_DIR",
                                    str(REPO_ROOT / "artifacts")))
BASELINE_PATH = ARTIFACTS_DIR / "baseline.npz"

# Prediction log. A SQLAlchemy URL so the SAME code targets either a local
# SQLite file or the shared Postgres service (sqlite:/// vs postgresql://).
PREDICTIONS_DB_URL = os.environ.get(
    "PREDICTIONS_DB_URL",
    f"sqlite:///{(REPO_ROOT / 'predictions.db').as_posix()}",
)
# Back-compat: some M0 code/docs still refer to the raw SQLite file path.
PRED_DB = REPO_ROOT / "predictions.db"

# MLflow tracking + registry. Local default = the M0 SQLite file (no server
# needed). Compose overrides this with http://mlflow:5000 (a real server).
MLFLOW_TRACKING_URI = os.environ.get(
    "MLFLOW_TRACKING_URI",
    f"sqlite:///{REPO_ROOT.as_posix()}/mlflow.db",
)
MLFLOW_ARTIFACT_ROOT = os.environ.get(
    "MLFLOW_ARTIFACT_ROOT",
    (REPO_ROOT / "mlartifacts").as_uri(),
)
MLFLOW_EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT", "pipeline-ml")

# --- Model / data contract ---------------------------------------------------
MODEL_NAME = "income-clf"
MODEL_ALIAS = "production"          # what the inference service serves
N_FEATURES = 8
FEATURE_NAMES = [f"f{i}" for i in range(N_FEATURES)]
RANDOM_SEED = 42


POOL_SIZE = 20000        # one fixed universe of data
TRAIN_SIZE = 6000        # first slice -> training; the rest -> "production stream"


@lru_cache(maxsize=1)
def _pool():
    """One fixed dataset. KEY INSIGHT: the distribution itself is seeded by
    `random_state`, so calling make_classification with a *different* seed gives
    a *different distribution*, not "more of the same". To get fresh
    in-distribution samples we must draw from disjoint rows of ONE generated
    pool. Rows are i.i.d. + shuffled, so any slice is a valid sample.
    """
    X, y = make_classification(
        n_samples=POOL_SIZE,
        n_features=N_FEATURES,
        n_informative=5,
        n_redundant=2,
        n_clusters_per_class=2,
        class_sep=1.0,
        random_state=RANDOM_SEED,
    )
    return X.astype(np.float64), y.astype(int)


def training_data():
    """First slice of the pool -> used to train + build the drift baseline."""
    X, y = _pool()
    return X[:TRAIN_SIZE], y[:TRAIN_SIZE]


def production_sample(n: int, seed: int = 999):
    """`n` rows drawn from the held-out part of the SAME pool -> same
    distribution as training, so undrifted traffic stays STABLE.
    """
    X, y = _pool()
    Xp, yp = X[TRAIN_SIZE:], y[TRAIN_SIZE:]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(Xp), size=n)
    return Xp[idx], yp[idx]


def apply_drift(X: np.ndarray, feature_index: int = 0,
                factor: float = 1.8, shift: float = 2.0) -> np.ndarray:
    """Return a copy of X with one feature distribution deliberately moved.

    This simulates real-world data drift (covariate shift) so we can prove the
    detector fires.
    """
    Xd = X.copy()
    Xd[:, feature_index] = Xd[:, feature_index] * factor + shift
    return Xd


def git_sha() -> str:
    """Best-effort short git SHA of the current commit (for lineage)."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"
