"""Region processing from immutable source spectra, with a shared integral basis."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace

import numpy as np

from .nmr import comparison_metrics, integral_ratios, preprocess_pair


class ComparisonSession:
    def __init__(self, a, b, result):
        self.a_raw, self.b_raw = deepcopy(a), deepcopy(b)
        self.reset(result)

    def reset(self, result):
        """Apply manually edited settings to the view and shared integral basis."""
        self.result = result
        self.integral_settings = replace(result.settings)
        self._cache = {self._key(result.settings): result}

    @staticmethod
    def _key(settings):
        return tuple(asdict(settings).items())

    @staticmethod
    def _bounds(low, high):
        low, high = float(low), float(high)
        if not np.isfinite([low, high]).all() or low >= high:
            raise ValueError("Comparison minimum must be less than maximum and both must be finite.")
        return low, high

    def _process(self, settings):
        key = self._key(settings)
        if key not in self._cache:
            result = preprocess_pair(self.a_raw, self.b_raw, settings)
            if len(self._cache) >= 16:
                del self._cache[next(iter(self._cache))]
            self._cache[key] = result
        return self._cache[key]

    def region_result(self, low, high):
        low, high = self._bounds(low, high)
        # A region shortcut uses that region for automatic alignment as well.
        # Always process the original spectra, never a cropped/normalized view.
        settings = replace(self.result.settings, ppm_min=low, ppm_max=high,
                           alignment_min=None, alignment_max=None)
        return self._process(settings)

    def select_region(self, low, high):
        result = self.region_result(low, high)
        self.result = result
        return result

    def statistics(self, comparison, aliphatic, aromatic):
        metrics, results = {}, {}
        for label, bounds in (("Comparison range", comparison),
                              ("Aliphatic region", aliphatic), ("Aromatic region", aromatic)):
            try:
                result = self.result if label == "Comparison range" else self.region_result(*bounds)
                metrics[label] = comparison_metrics(result, *bounds)
                results[label] = result
            except (ValueError, TypeError) as exc:
                metrics[label] = {"error": str(exc), "requested_range_ppm": list(bounds)}
        return metrics, results

    def integrals(self, aliphatic, aromatic):
        alow, ahigh = self._bounds(*aliphatic)
        rlow, rhigh = self._bounds(*aromatic)
        # Keep this basis independent of the selected view. Both integration
        # regions share one alignment and one normalization factor per spectrum.
        settings = replace(self.integral_settings,
                           ppm_min=min(self.integral_settings.ppm_min, alow, rlow),
                           ppm_max=max(self.integral_settings.ppm_max, ahigh, rhigh))
        result = self._process(settings)
        return result, integral_ratios(result, aliphatic, aromatic)
