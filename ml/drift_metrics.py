"""Hand-rolled drift metrics: PSI + KS.

Written by hand (not pulled from a library) so the math is visible and learnable.

PSI (Population Stability Index): "how much has this distribution moved?"
  - Bin the reference (training) data into quantile bins.
  - Compare the % of reference vs current data falling in each bin.
  - PSI = sum( (cur% - ref%) * ln(cur% / ref%) )
  Rule of thumb:  < 0.1 stable | 0.1-0.2 moderate shift | > 0.2 significant.
  PSI is roughly sample-size stable, which is why it's an industry default.

KS (Kolmogorov-Smirnov, two-sample): max gap between the two cumulative
  distributions. More sensitive (especially in the tails) but over-fires on
  very large samples -- so we report both and let a human/threshold reconcile.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import ks_2samp

PSI_MODERATE = 0.1
PSI_SIGNIFICANT = 0.2


def psi(reference: np.ndarray, current: np.ndarray,
        bins: int = 10, epsilon: float = 1e-6) -> float:
    """Population Stability Index between a reference and current 1-D sample."""
    reference = np.asarray(reference, dtype=float)
    current = np.asarray(current, dtype=float)

    # Quantile bin edges from the reference distribution.
    quantiles = np.linspace(0, 100, bins + 1)
    edges = np.percentile(reference, quantiles)
    edges[0], edges[-1] = -np.inf, np.inf  # catch out-of-range current values

    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)

    ref_pct = np.clip(ref_counts / max(ref_counts.sum(), 1), epsilon, None)
    cur_pct = np.clip(cur_counts / max(cur_counts.sum(), 1), epsilon, None)

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def verdict(psi_value: float) -> str:
    if psi_value >= PSI_SIGNIFICANT:
        return "SIGNIFICANT"
    if psi_value >= PSI_MODERATE:
        return "MODERATE"
    return "STABLE"


@dataclass
class FeatureDrift:
    feature: str
    psi: float
    ks_stat: float
    ks_pvalue: float
    verdict: str


def feature_drift_report(reference: np.ndarray, current: np.ndarray,
                         feature_names: list[str]) -> list[FeatureDrift]:
    """Per-feature PSI + KS for two 2-D arrays with matching columns."""
    report: list[FeatureDrift] = []
    for i, name in enumerate(feature_names):
        ref_col, cur_col = reference[:, i], current[:, i]
        p = psi(ref_col, cur_col)
        ks = ks_2samp(ref_col, cur_col)
        report.append(FeatureDrift(
            feature=name, psi=p,
            ks_stat=float(ks.statistic), ks_pvalue=float(ks.pvalue),
            verdict=verdict(p),
        ))
    return report
