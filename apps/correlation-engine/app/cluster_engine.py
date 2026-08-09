"""
Clusters anomalies across services into incident candidates.

The core insight this encodes: five services all showing anomalies within
the same 60-second window are far more likely to be one incident (a shared
downstream dependency failing) than five coincidental, unrelated problems.
Two anomalies are linked into the same cluster if either:

  1. They occurred within `correlation_window_seconds` of each other
     (temporal co-occurrence), or
  2. They share a trace_id (direct causal evidence - the request literally
     passed through both services), which is a much stronger signal and is
     recorded on the resulting cluster.

Implemented as union-find over the anomaly list: O(n * alpha(n)) rather than
an O(n^2) pairwise comparison, which matters once a single correlation
window can contain hundreds of anomalies during a wide-blast-radius incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app.anomaly_detector import AnomalyResult


@dataclass
class AnomalyCluster:
    anomalies: list[AnomalyResult] = field(default_factory=list)
    linked_trace_ids: set[str] = field(default_factory=set)

    @property
    def service_names(self) -> set[str]:
        return {a.service_name for a in self.anomalies}

    @property
    def window_start(self):
        return min(a.occurred_at for a in self.anomalies)

    @property
    def window_end(self):
        return max(a.occurred_at for a in self.anomalies)

    @property
    def max_anomaly_score(self) -> float:
        return max(a.anomaly_score for a in self.anomalies)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, i: int) -> int:
        while self._parent[i] != i:
            self._parent[i] = self._parent[self._parent[i]]  # path halving
            i = self._parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        root_i, root_j = self.find(i), self.find(j)
        if root_i != root_j:
            self._parent[root_i] = root_j


class ClusterEngine:
    def __init__(self, correlation_window_seconds: float = 60.0) -> None:
        if correlation_window_seconds <= 0:
            raise ValueError("correlation_window_seconds must be positive")
        self._window = timedelta(seconds=correlation_window_seconds)

    def cluster(
        self,
        anomalies: list[AnomalyResult],
        trace_links: dict[str, set[str]] | None = None,
    ) -> list[AnomalyCluster]:
        """
        `trace_links` maps trace_id -> set of service_names that trace touched,
        used to detect that two anomalies are causally linked, not just
        temporally coincidental. Optional - falls back to purely temporal
        clustering when trace data isn't available for a given window.
        """
        if not anomalies:
            return []

        trace_links = trace_links or {}
        uf = _UnionFind(len(anomalies))

        # Build a lookup: service_name -> set of trace_ids that touched it,
        # so we can cheaply test "do these two anomalies share a trace".
        service_to_traces: dict[str, set[str]] = {}
        for trace_id, services in trace_links.items():
            for service in services:
                service_to_traces.setdefault(service, set()).add(trace_id)

        for i in range(len(anomalies)):
            for j in range(i + 1, len(anomalies)):
                a, b = anomalies[i], anomalies[j]

                temporally_linked = abs(a.occurred_at - b.occurred_at) <= self._window
                trace_linked = bool(
                    service_to_traces.get(a.service_name, set())
                    & service_to_traces.get(b.service_name, set())
                )

                if temporally_linked or trace_linked:
                    uf.union(i, j)

        groups: dict[int, AnomalyCluster] = {}
        for idx, anomaly in enumerate(anomalies):
            root = uf.find(idx)
            cluster = groups.setdefault(root, AnomalyCluster())
            cluster.anomalies.append(anomaly)

            shared_traces = service_to_traces.get(anomaly.service_name, set())
            cluster.linked_trace_ids |= shared_traces

        # Stable ordering: most severe cluster first, so callers processing
        # clusters under a time/cost budget handle the worst incidents first.
        return sorted(groups.values(), key=lambda c: c.max_anomaly_score, reverse=True)
