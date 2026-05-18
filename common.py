"""Shared configuration and helpers for pipeline-ml.

Everything here is computed relative to THIS file's location, so every script
works the same no matter which directory you run it from. Keeping one source of
truth for paths/feature names avoids training-serving skew (the #1 silent ML
failure) inside our own project.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.datasets import make_classification

# --- Paths (CWD-independent) -------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
BASELINE_PATH = ARTIFACTS_DIR / "baseline.npz"
PRED_DB = REPO_ROOT / "predictions.db"

# MLflow tracking + registry live in a local SQLite file (no server needed).
# SQLite needs the Model Registry, which the plain file:// store does not support.
MLFLOW_TRACKING_URI = f"sqlite:///{REPO_ROOT.as_posix()}/mlflow.db"
MLFLOW_ARTIFACT_ROOT = (REPO_ROOT / "mlartifacts").as_uri()
MLFLOW_EXPERIMENT = "pipeline-ml"

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
