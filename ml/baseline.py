"""Save / load the training feature distribution used as the drift reference.

The drift job needs a fixed snapshot of "what the data looked like at training
time" to compare production traffic against. We persist a sample of the training
features to artifacts/baseline.npz.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path
from common import ARTIFACTS_DIR, BASELINE_PATH, training_data  # noqa: E402

BASELINE_SAMPLE = 3000


def save_baseline(X: np.ndarray) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    sample = X[:BASELINE_SAMPLE]
    np.savez_compressed(BASELINE_PATH, X=sample)
    return BASELINE_PATH


def load_baseline() -> np.ndarray:
    if not BASELINE_PATH.exists():
        raise FileNotFoundError(
            f"{BASELINE_PATH} missing -- run ml/train.py (or ml/baseline.py) first."
        )
    with np.load(BASELINE_PATH) as data:
        return data["X"]


if __name__ == "__main__":
    X, _ = training_data()
    path = save_baseline(X)
    print(f"Baseline saved: {path}  shape={load_baseline().shape}")
