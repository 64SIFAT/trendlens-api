"""Statistical analysis helpers for TrendLens.

The application uses annual means derived from NASA POWER monthly PRECTOTCORR
values. Estimates are descriptive; the API explicitly warns that serial dependence
and grid-cell representativeness can affect inferential interpretation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import math
import numpy as np
from scipy.stats import kendalltau, theilslopes


@dataclass
class TrendResult:
    years: list[int]
    values: list[float]
    slope: float
    intercept: float
    ci_low: float
    ci_high: float
    tau: float | None
    p_value: float | None
    n_years: int
    coverage: float
    unit: str


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        raise ValueError("At least three annual observations are required.")
    return float(theilslopes(y, x)[0])


def _block_bootstrap_slopes(years: np.ndarray, values: np.ndarray, *, reps: int = 500,
                            block: int = 2, seed: int = 20261029) -> np.ndarray:
    """Residual circular moving-block bootstrap for slope uncertainty.

    Detrends with a Theil-Sen line, resamples residual blocks, and refits slopes.
    This is a practical uncertainty estimate, not a substitute for a full
    domain-specific model of precipitation seasonality or autocorrelation.
    """
    base_slope, base_intercept, _, _ = theilslopes(values, years)
    fitted = base_intercept + base_slope * years
    residuals = values - fitted
    n = len(values)
    rng = np.random.default_rng(seed)
    slopes = []
    block = max(1, min(block, n))
    starts_needed = math.ceil(n / block)
    for _ in range(reps):
        chunks = []
        for start in rng.integers(0, n, size=starts_needed):
            idx = (np.arange(start, start + block) % n)
            chunks.extend(residuals[idx].tolist())
        synthetic = fitted + np.asarray(chunks[:n])
        try:
            slopes.append(_slope(years, synthetic))
        except (ValueError, FloatingPointError):
            continue
    return np.asarray(slopes, dtype=float)


def analyze_series(years: Sequence[int], values: Sequence[float], *, unit: str = "mm/day") -> TrendResult:
    pairs = [(int(y), float(v)) for y, v in zip(years, values)
             if v is not None and np.isfinite(v)]
    pairs.sort(key=lambda pair: pair[0])
    if len(pairs) < 10:
        raise ValueError("At least 10 valid annual observations are required for this analysis.")
    x = np.asarray([p[0] for p in pairs], dtype=float)
    y = np.asarray([p[1] for p in pairs], dtype=float)
    if len(np.unique(x)) != len(x):
        raise ValueError("Duplicate annual observations were found.")
    slope, intercept, _, _ = theilslopes(y, x)
    boot = _block_bootstrap_slopes(x, y)
    if len(boot) >= 100:
        ci_low, ci_high = np.quantile(boot, [0.025, 0.975]).tolist()
    else:
        _, _, ci_low, ci_high = theilslopes(y, x, alpha=0.95)
    tau_result = kendalltau(x, y, nan_policy="omit")
    return TrendResult(
        years=[int(v) for v in x], values=[float(v) for v in y],
        slope=float(slope), intercept=float(intercept),
        ci_low=float(ci_low), ci_high=float(ci_high),
        tau=float(tau_result.statistic) if np.isfinite(tau_result.statistic) else None,
        p_value=float(tau_result.pvalue) if np.isfinite(tau_result.pvalue) else None,
        n_years=len(x), coverage=len(x) / max(1, int(x[-1] - x[0] + 1)), unit=unit,
    )


def compare_trends(a: TrendResult, b: TrendResult, *, reps: int = 500,
                   seed: int = 20261029) -> dict:
    """Estimate slope difference and a paired block-bootstrap 95% interval.

    Difference is slope(A) - slope(B). The same resampled year-block indices are
    applied to both series after detrending, preserving shared temporal blocks.
    Only overlapping years are compared.
    """
    map_a = dict(zip(a.years, a.values))
    map_b = dict(zip(b.years, b.values))
    common = sorted(set(map_a) & set(map_b))
    if len(common) < 10:
        raise ValueError("The two locations need at least 10 overlapping annual observations.")
    x = np.asarray(common, dtype=float)
    ya = np.asarray([map_a[y] for y in common], dtype=float)
    yb = np.asarray([map_b[y] for y in common], dtype=float)
    sa, ia, _, _ = theilslopes(ya, x)
    sb, ib, _, _ = theilslopes(yb, x)
    fa, fb = ia + sa*x, ib + sb*x
    ra, rb = ya-fa, yb-fb
    n = len(x); block = min(2, n); rng = np.random.default_rng(seed + 1)
    slopes = []
    starts_needed = math.ceil(n / block)
    for _ in range(reps):
        chunks_a, chunks_b = [], []
        for start in rng.integers(0, n, size=starts_needed):
            idx = np.arange(start, start+block) % n
            chunks_a.extend(ra[idx].tolist()); chunks_b.extend(rb[idx].tolist())
        boot_a = fa + np.asarray(chunks_a[:n]); boot_b = fb + np.asarray(chunks_b[:n])
        slopes.append(_slope(x, boot_a) - _slope(x, boot_b))
    lo, hi = np.quantile(np.asarray(slopes), [0.025, 0.975]).tolist()
    diff = float(sa - sb)
    return {
        "overlapping_years": common,
        "slope_a_minus_b": diff,
        "ci_low": float(lo), "ci_high": float(hi),
        "unit": f"{a.unit}/year difference",
        "direction": "A increases faster" if diff > 0 else ("B increases faster" if diff < 0 else "similar estimated slopes"),
        "interval_excludes_zero": bool(lo > 0 or hi < 0),
        "interpretation": (
            "The estimated slope difference interval excludes zero; interpret with the stated data and model limitations."
            if (lo > 0 or hi < 0) else
            "The estimated slope difference interval includes zero; this analysis does not clearly distinguish the slopes."
        ),
    }
