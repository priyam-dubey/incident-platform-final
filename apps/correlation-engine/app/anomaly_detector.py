"""
Rolling z-score anomaly detection, per (service_name, metric_name) pair.

Design choice: a fixed-size sliding window of recent samples (not an
exponential moving average) so the baseline reflects genuinely recent
behavior and old regime shifts age out completely rather than lingering with
diminishing weight. The z-score for an incoming value is computed against
the *existing* buffer, before that value is added to it - a value should
never be able to pull its own baseline toward itself, or a sustained spike
would quietly become "normal" partway through and stop triggering.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AnomalyResult:
    service_name: str
    metric_name: str
    observed_value: float
    baseline_mean: float
    baseline_stddev: float
    zscore: float
    occurred_at: datetime

    @property
    def anomaly_score(self) -> float:
        # Normalized, always-positive magnitude - convenient for ranking/sorting
        # anomalies without callers needing to know about signed z-scores.
        return abs(self.zscore)


class _MetricBaseline:
    def __init__(self, window_size: int) -> None:
        self._values: deque[float] = deque(maxlen=window_size)

    def zscore(self, value: float) -> float | None:
        """None if there isn't yet enough history to judge (cold start)."""
        if len(self._values) < 2:
            return None

        mean = sum(self._values) / len(self._values)
        variance = sum((v - mean) ** 2 for v in self._values) / len(self._values)
        stddev = math.sqrt(variance)

        if stddev == 0:
            # A perfectly flat baseline (e.g. error_rate has been exactly 0.0
            # for the whole window) means *any* deviation is meaningful, but
            # a divide-by-zero z-score is undefined - treat any difference as
            # maximally anomalous rather than crashing or silently ignoring it.
            return math.inf if value != mean else 0.0

        return (value - mean) / stddev

    def mean_and_stddev(self) -> tuple[float, float]:
        if not self._values:
            return 0.0, 0.0
        mean = sum(self._values) / len(self._values)
        variance = sum((v - mean) ** 2 for v in self._values) / len(self._values)
        return mean, math.sqrt(variance)

    def add(self, value: float) -> None:
        self._values.append(value)

    def __len__(self) -> int:
        return len(self._values)


class AnomalyDetector:
    def __init__(
        self,
        zscore_threshold: float = 3.0,
        window_size: int = 60,
        min_samples: int = 10,
    ) -> None:
        if zscore_threshold <= 0:
            raise ValueError("zscore_threshold must be positive")
        if window_size < 2:
            raise ValueError("window_size must be at least 2")
        if min_samples < 2:
            raise ValueError("min_samples must be at least 2")

        self._threshold = zscore_threshold
        self._window_size = window_size
        self._min_samples = min_samples
        self._baselines: dict[tuple[str, str], _MetricBaseline] = {}

    def observe(
        self,
        service_name: str,
        metric_name: str,
        value: float,
        occurred_at: datetime,
    ) -> AnomalyResult | None:
        key = (service_name, metric_name)
        baseline = self._baselines.setdefault(key, _MetricBaseline(self._window_size))

        result: AnomalyResult | None = None

        if len(baseline) >= self._min_samples:
            z = baseline.zscore(value)
            if z is not None and abs(z) >= self._threshold:
                mean, stddev = baseline.mean_and_stddev()
                result = AnomalyResult(
                    service_name=service_name,
                    metric_name=metric_name,
                    observed_value=value,
                    baseline_mean=mean,
                    baseline_stddev=stddev,
                    zscore=z,
                    occurred_at=occurred_at,
                )

        # Always feed the value into the baseline, anomalous or not - an
        # anomaly detector that stopped learning from unusual-but-real values
        # would never adapt to genuine regime shifts (e.g. a legitimate
        # traffic pattern change), and would keep re-flagging the new normal
        # as anomalous forever.
        baseline.add(value)
        return result

    def sample_count(self, service_name: str, metric_name: str) -> int:
        baseline = self._baselines.get((service_name, metric_name))
        return len(baseline) if baseline is not None else 0
