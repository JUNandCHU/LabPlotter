from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.signal import find_peaks, savgol_filter
from scipy.sparse.linalg import spsolve

from .i18n import tr


def asls_baseline(y: np.ndarray, lam: float = 1e6, p: float = 0.01, iterations: int = 10, upper: bool = False) -> np.ndarray:
    """Asymmetric least-squares baseline; upper=True follows trough spectra."""
    values = np.asarray(y, dtype=float)
    if upper:
        return -asls_baseline(-values, lam=lam, p=p, iterations=iterations, upper=False)
    length = len(values)
    if length < 3:
        return values.copy()
    d = sparse.diags([1.0, -2.0, 1.0], [0, -1, -2], shape=(length, length - 2), format="csc")
    penalty = lam * d.dot(d.T)
    weights = np.ones(length)
    for _ in range(iterations):
        z = spsolve(sparse.spdiags(weights, 0, length, length) + penalty, weights * values)
        weights = p * (values > z) + (1.0 - p) * (values < z)
        weights[weights == 0] = 1e-6
    return np.asarray(z)


def linear_endpoints_baseline(x: np.ndarray, y: np.ndarray, edge_fraction: float = 0.03) -> np.ndarray:
    """Robust straight line through median values at both ends of a spectrum."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    count = max(3, min(len(y) // 4, int(round(len(y) * edge_fraction))))
    left_x, right_x = float(np.median(x[:count])), float(np.median(x[-count:]))
    left_y, right_y = float(np.median(y[:count])), float(np.median(y[-count:]))
    if left_x == right_x:
        return np.full_like(y, (left_y + right_y) / 2)
    return left_y + (right_y - left_y) * (x - left_x) / (right_x - left_x)


def rubberband_baseline(x: np.ndarray, y: np.ndarray, upper: bool = False) -> np.ndarray:
    """Piecewise-linear convex-hull (rubberband) baseline."""
    x = np.asarray(x, dtype=float)
    values = np.asarray(y, dtype=float)
    if len(values) < 5:
        return linear_endpoints_baseline(x, values)
    window = min(101, max(11, len(values) // 200))
    if window % 2 == 0:
        window += 1
    if window >= len(values):
        window = len(values) - 1 if len(values) % 2 == 0 else len(values)
    smooth = savgol_filter(values, window, 2) if window >= 5 else values.copy()
    hull_values = -smooth if upper else smooth
    hull: list[int] = []
    for index in range(len(x)):
        while len(hull) >= 2:
            a, b = hull[-2], hull[-1]
            cross = (x[b] - x[a]) * (hull_values[index] - hull_values[a]) - (hull_values[b] - hull_values[a]) * (x[index] - x[a])
            if cross <= 0:
                hull.pop()
            else:
                break
        hull.append(index)
    baseline = np.interp(x, x[hull], hull_values[hull])
    return -baseline if upper else baseline


def modpoly_baseline(y: np.ndarray, order: int = 2, upper: bool = False, iterations: int = 100, tolerance: float = 1e-4) -> np.ndarray:
    """Iterative modified-polynomial baseline with automatic peak clipping."""
    values = -np.asarray(y, dtype=float) if upper else np.asarray(y, dtype=float)
    scaled_x = np.linspace(-1.0, 1.0, len(values))
    working = values.copy()
    previous = np.zeros_like(values)
    for _ in range(iterations):
        baseline = np.polyval(np.polyfit(scaled_x, working, max(1, int(order))), scaled_x)
        below = values[values < baseline] - baseline[values < baseline]
        sigma = float(np.std(below)) if len(below) > 2 else 0.0
        working = np.minimum(values, baseline + sigma)
        denominator = np.linalg.norm(previous) + 1e-12
        if np.linalg.norm(baseline - previous) / denominator < tolerance:
            break
        previous = baseline
    return -baseline if upper else baseline


def _difference_penalty(length: int, lam: float):
    difference = sparse.diags([1.0, -2.0, 1.0], [0, -1, -2], shape=(length, length - 2), format="csc")
    return lam * difference.dot(difference.T)


def arpls_baseline(y: np.ndarray, lam: float = 1e6, upper: bool = False, iterations: int = 50, tolerance: float = 1e-3) -> np.ndarray:
    """Asymmetrically reweighted penalized least-squares baseline."""
    values = -np.asarray(y, dtype=float) if upper else np.asarray(y, dtype=float)
    length = len(values)
    penalty = _difference_penalty(length, lam)
    weights = np.ones(length)
    baseline = values.copy()
    for _ in range(iterations):
        baseline = spsolve(sparse.spdiags(weights, 0, length, length) + penalty, weights * values)
        residual = values - baseline
        negative = residual[residual < 0]
        if len(negative) < 2:
            break
        mean, std = float(np.mean(negative)), float(np.std(negative))
        if std < 1e-12:
            break
        exponent = np.clip(2.0 * (residual - (-mean + 2.0 * std)) / std, -60, 60)
        new_weights = 1.0 / (1.0 + np.exp(exponent))
        if np.linalg.norm(new_weights - weights) / (np.linalg.norm(weights) + 1e-12) < tolerance:
            weights = new_weights
            break
        weights = new_weights
    return -np.asarray(baseline) if upper else np.asarray(baseline)


def airpls_baseline(y: np.ndarray, lam: float = 1e6, upper: bool = False, iterations: int = 30, tolerance: float = 1e-3) -> np.ndarray:
    """Adaptive iteratively reweighted penalized least-squares baseline."""
    values = -np.asarray(y, dtype=float) if upper else np.asarray(y, dtype=float)
    length = len(values)
    penalty = _difference_penalty(length, lam)
    weights = np.ones(length)
    baseline = values.copy()
    scale = np.sum(np.abs(values)) + 1e-12
    for iteration in range(1, iterations + 1):
        baseline = spsolve(sparse.spdiags(weights, 0, length, length) + penalty, weights * values)
        residual = values - baseline
        negative = residual < 0
        negative_sum = float(np.sum(np.abs(residual[negative])))
        if not np.any(negative) or negative_sum / scale < tolerance:
            break
        weights[~negative] = 0.0
        weights[negative] = np.exp(np.clip(iteration * np.abs(residual[negative]) / negative_sum, 0, 60))
        edge_weight = float(np.exp(min(60.0, iteration * np.max(np.abs(residual[negative])) / negative_sum)))
        weights[0] = weights[-1] = edge_weight
    return -np.asarray(baseline) if upper else np.asarray(baseline)


def estimate_ftir_baseline(
    x: np.ndarray,
    y: np.ndarray,
    method: str,
    orientation: str = "Transmittance (downward bands)",
    lam: float = 1e8,
    p: float = 0.01,
    poly_order: int = 2,
) -> np.ndarray:
    upper = orientation.startswith("Transmittance")
    if method.startswith("Linear endpoints"):
        return linear_endpoints_baseline(x, y)
    if method.startswith("Rubberband"):
        return rubberband_baseline(x, y, upper=upper)
    if method.startswith("Modified polynomial"):
        return modpoly_baseline(y, order=poly_order, upper=upper)
    if method.startswith("arPLS"):
        return arpls_baseline(y, lam=lam, upper=upper)
    if method.startswith("airPLS"):
        return airpls_baseline(y, lam=lam, upper=upper)
    return asls_baseline(y, lam=lam, p=p, upper=upper)


def normalize(values: np.ndarray, mode: str) -> np.ndarray:
    y = np.asarray(values, dtype=float)
    if mode == "Min-max (0–1)":
        span = np.nanmax(y) - np.nanmin(y)
        return (y - np.nanmin(y)) / span if span else y.copy()
    if mode == "Maximum = 1":
        maximum = np.nanmax(np.abs(y))
        return y / maximum if maximum else y.copy()
    if mode == "Vector (L2)":
        norm = np.linalg.norm(y)
        return y / norm if norm else y.copy()
    return y.copy()


def process_ftir(
    x: np.ndarray,
    y: np.ndarray,
    baseline_enabled: bool = False,
    baseline_method: str = "Linear endpoints (diagonal)",
    orientation: str = "Transmittance (downward bands)",
    lam: float = 1e8,
    p: float = 0.01,
    poly_order: int = 2,
    normalization_enabled: bool = False,
    normalization_mode: str = "Min-max (0–1)",
) -> np.ndarray:
    result = np.asarray(y, dtype=float).copy()
    if baseline_enabled:
        baseline = estimate_ftir_baseline(x, result, baseline_method, orientation, lam, p, poly_order)
        if orientation.startswith("Transmittance"):
            result = np.divide(result * 100.0, baseline, out=np.zeros_like(result), where=np.abs(baseline) > 1e-12)
        else:
            result = result - baseline
    if normalization_enabled:
        result = normalize(result, normalization_mode)
    return result


def ftir_peak_indices(y: np.ndarray, prominence_fraction: float = 0.03, max_peaks: int = 12, troughs: bool = True) -> np.ndarray:
    values = -np.asarray(y, dtype=float) if troughs else np.asarray(y, dtype=float)
    span = float(np.nanmax(values) - np.nanmin(values))
    if not span:
        return np.asarray([], dtype=int)
    peaks, props = find_peaks(values, prominence=span * prominence_fraction, distance=max(1, len(values) // 100))
    if len(peaks) > max_peaks:
        order = np.argsort(props["prominences"])[-max_peaks:]
        peaks = peaks[order]
    return np.sort(peaks)


def mean_curve(curves: list[tuple[np.ndarray, np.ndarray]], points: int = 500) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not curves:
        raise ValueError(tr("No curves"))
    left = max(float(np.nanmin(x)) for x, _ in curves)
    right = min(float(np.nanmax(x)) for x, _ in curves)
    if left >= right:
        raise ValueError(tr("Replicate X ranges do not overlap"))
    if all(np.all(np.asarray(x) > 0) for x, _ in curves) and right / max(left, 1e-30) > 100:
        grid = np.geomspace(left, right, points)
    else:
        grid = np.linspace(left, right, points)
    stack = np.vstack([np.interp(grid, np.asarray(x), np.asarray(y)) for x, y in curves])
    return grid, np.nanmean(stack, axis=0), np.nanstd(stack, axis=0, ddof=1 if len(stack) > 1 else 0)
