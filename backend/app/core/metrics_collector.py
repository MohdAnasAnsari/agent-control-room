"""
In-process rolling-window metrics collector.

Tracks request duration, status codes, and execution outcomes.
Computes p50/p95/p99 on demand.
Triggers alerts when thresholds are exceeded.

The collector is a module-level singleton; call record_request() from the
HTTP middleware and check_alert_thresholds() from a background task.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from statistics import median, quantiles
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# ── Configurable alert thresholds ─────────────────────────────────────────────

ERROR_RATE_THRESHOLD   = 0.05   # 5 %   of requests per minute
P95_LATENCY_THRESHOLD  = 5000   # ms    p95 response time
EXEC_FAIL_THRESHOLD    = 0.20   # 20%   workflow execution failure rate
CHECK_INTERVAL_S       = 60     # how often the background loop checks thresholds

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class _RequestSample:
    timestamp: float       # time.time()
    endpoint: str
    method: str
    status_code: int
    duration_ms: float
    user_id: Optional[str] = None


@dataclass
class PercentileSnapshot:
    p50: float
    p95: float
    p99: float
    sample_count: int
    window_seconds: int


@dataclass
class MetricsSummary:
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float          # 0.0–1.0
    requests_per_minute: float
    sample_count: int
    top_slow_endpoints: list[dict]


# ── Collector ──────────────────────────────────────────────────────────────────

class MetricsCollector:
    """
    Singleton metrics collector.

    Call startup() at app start to launch the background alert checker.
    Call shutdown() on app stop.
    """

    # Keep at most 50 k samples in memory (~8 MB at ~160 bytes/sample)
    _MAX_SAMPLES = 50_000

    def __init__(self) -> None:
        self._samples: deque[_RequestSample] = deque(maxlen=self._MAX_SAMPLES)
        self._exec_total = 0
        self._exec_failed = 0
        self._last_alert_ts: dict[str, float] = {}
        self._alert_cooldown_s = 300   # don't re-fire the same alert for 5 min
        self._background_task: Optional[asyncio.Task] = None

    # ── record ─────────────────────────────────────────────────────────────────

    def record_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: float,
        user_id: Optional[str] = None,
    ) -> None:
        self._samples.append(
            _RequestSample(
                timestamp=time.time(),
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                duration_ms=duration_ms,
                user_id=user_id,
            )
        )

    def record_execution(self, *, success: bool) -> None:
        self._exec_total += 1
        if not success:
            self._exec_failed += 1

    # ── query ──────────────────────────────────────────────────────────────────

    def percentiles(self, window_s: int = 300) -> PercentileSnapshot:
        """Compute p50/p95/p99 over the last `window_s` seconds."""
        cutoff = time.time() - window_s
        durations = [s.duration_ms for s in self._samples if s.timestamp >= cutoff]
        if not durations:
            return PercentileSnapshot(p50=0, p95=0, p99=0, sample_count=0, window_seconds=window_s)
        durations_sorted = sorted(durations)
        n = len(durations_sorted)
        return PercentileSnapshot(
            p50=_percentile(durations_sorted, 50),
            p95=_percentile(durations_sorted, 95),
            p99=_percentile(durations_sorted, 99),
            sample_count=n,
            window_seconds=window_s,
        )

    def error_rate(self, window_s: int = 60) -> float:
        """Fraction of 4xx/5xx responses in the last `window_s` seconds."""
        cutoff = time.time() - window_s
        recent = [s for s in self._samples if s.timestamp >= cutoff]
        if not recent:
            return 0.0
        errors = sum(1 for s in recent if s.status_code >= 400)
        return errors / len(recent)

    def requests_per_minute(self, window_s: int = 60) -> float:
        cutoff = time.time() - window_s
        count = sum(1 for s in self._samples if s.timestamp >= cutoff)
        return count * (60 / window_s)

    def execution_failure_rate(self) -> float:
        if self._exec_total == 0:
            return 0.0
        return self._exec_failed / self._exec_total

    def top_slow_endpoints(self, window_s: int = 3600, top_n: int = 5) -> list[dict]:
        """Return the top-N endpoints by average response time."""
        cutoff = time.time() - window_s
        buckets: dict[str, list[float]] = {}
        for s in self._samples:
            if s.timestamp >= cutoff:
                buckets.setdefault(s.endpoint, []).append(s.duration_ms)
        ranked = sorted(
            [
                {"endpoint": ep, "avg_ms": sum(v) / len(v), "count": len(v)}
                for ep, v in buckets.items()
            ],
            key=lambda x: x["avg_ms"],
            reverse=True,
        )
        return ranked[:top_n]

    def summary(self, window_s: int = 300) -> MetricsSummary:
        p = self.percentiles(window_s)
        return MetricsSummary(
            p50_ms=round(p.p50, 1),
            p95_ms=round(p.p95, 1),
            p99_ms=round(p.p99, 1),
            error_rate=round(self.error_rate(60), 4),
            requests_per_minute=round(self.requests_per_minute(60), 1),
            sample_count=p.sample_count,
            top_slow_endpoints=self.top_slow_endpoints(window_s),
        )

    # ── Prometheus text format ─────────────────────────────────────────────────

    def prometheus_text(self) -> str:
        p = self.percentiles(300)
        er = self.error_rate(60)
        rpm = self.requests_per_minute(60)
        lines = [
            "# HELP http_request_duration_ms Request duration percentiles (5-minute window)",
            "# TYPE http_request_duration_ms gauge",
            f'http_request_duration_ms{{quantile="0.5"}} {p.p50:.1f}',
            f'http_request_duration_ms{{quantile="0.95"}} {p.p95:.1f}',
            f'http_request_duration_ms{{quantile="0.99"}} {p.p99:.1f}',
            "",
            "# HELP http_error_rate Fraction of 4xx/5xx responses (last 60 s)",
            "# TYPE http_error_rate gauge",
            f"http_error_rate {er:.4f}",
            "",
            "# HELP http_requests_per_minute Request throughput (last 60 s)",
            "# TYPE http_requests_per_minute gauge",
            f"http_requests_per_minute {rpm:.1f}",
            "",
            "# HELP execution_failure_rate Workflow execution failure rate (all time)",
            "# TYPE execution_failure_rate gauge",
            f"execution_failure_rate {self.execution_failure_rate():.4f}",
            "",
        ]
        return "\n".join(lines)

    # ── background alert checker ───────────────────────────────────────────────

    async def startup(self) -> None:
        self._background_task = asyncio.create_task(self._alert_loop())
        log.info("MetricsCollector: background alert loop started")

    async def shutdown(self) -> None:
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass

    async def _alert_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(CHECK_INTERVAL_S)
                await self.check_alert_thresholds()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("Metrics alert loop error: %s", exc)

    async def check_alert_thresholds(self) -> None:
        from app.core.alert_service import alert_service

        now = time.time()

        async def _maybe_alert(metric: str, value: float, threshold: float, ctx: str) -> None:
            last = self._last_alert_ts.get(metric, 0)
            if value > threshold and (now - last) > self._alert_cooldown_s:
                self._last_alert_ts[metric] = now
                await alert_service.on_metric_threshold(
                    metric=metric, value=value, threshold=threshold, context=ctx
                )

        er = self.error_rate(60)
        await _maybe_alert("error_rate", er, ERROR_RATE_THRESHOLD,
                           f"{er*100:.1f}% of requests in last 60 s returned 4xx/5xx")

        p = self.percentiles(300)
        await _maybe_alert("p95_latency_ms", p.p95, P95_LATENCY_THRESHOLD,
                           f"p95={p.p95:.0f}ms over {p.sample_count} samples (5-min window)")

        efr = self.execution_failure_rate()
        await _maybe_alert("execution_failure_rate", efr, EXEC_FAIL_THRESHOLD,
                           f"{efr*100:.1f}% of {self._exec_total} workflow executions failed")

    # ── persistence helpers ────────────────────────────────────────────────────

    async def persist_recent(self, db: "AsyncSession", batch_size: int = 100) -> int:
        """
        Write the most recent `batch_size` samples to the request_metrics table.
        Returns number of rows written.  Call from a background task or admin endpoint.
        """
        from app.models.database import RequestMetric

        cutoff = time.time() - 120   # persist samples newer than 2 min
        pending = [s for s in list(self._samples)[-batch_size:] if s.timestamp >= cutoff]
        if not pending:
            return 0

        from datetime import datetime, timezone
        rows = [
            RequestMetric(
                endpoint=s.endpoint,
                method=s.method,
                status_code=s.status_code,
                duration_ms=s.duration_ms,
                timestamp=datetime.fromtimestamp(s.timestamp, tz=timezone.utc),
            )
            for s in pending
        ]
        db.add_all(rows)
        return len(rows)


# ── Utility ────────────────────────────────────────────────────────────────────

def _percentile(sorted_data: list[float], pct: int) -> float:
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    idx = (pct / 100) * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo)


# ── Singleton ──────────────────────────────────────────────────────────────────

metrics_collector = MetricsCollector()
