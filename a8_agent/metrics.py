"""
Prometheus-style metrics for a8_agent

Tracks:
- Draft generation count and latency
- Error rates and failure modes
- CRM API call counts and latency
- Cadence trigger success rate
- HTTP endpoint metrics

Metrics are collected in-memory and exposed via HTTP endpoint for scraping.

Usage:
  from a8_agent.metrics import metrics_collector, setup_metrics_routes
  
  # In FastAPI app:
  setup_metrics_routes(app)
  
  # Record metrics:
  metrics_collector.record_draft_generated()
  metrics_collector.record_crm_call(duration_ms=42, success=True)
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class MetricSnapshot:
    """Snapshot of a single metric value."""
    name: str
    type: MetricType
    value: float
    timestamp: str
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class HistogramBucket:
    """Histogram bucket for latency tracking."""
    le: float  # less than or equal
    count: int


class MetricsCollector:
    """In-memory metrics collector for a8_agent."""
    
    def __init__(self, retention_seconds: int = 3600):
        self.retention_seconds = retention_seconds
        
        # Counters
        self.drafts_generated_total = 0
        self.drafts_failed_total = 0
        self.cadence_enrollments_total = 0
        self.crm_api_calls_total = 0
        self.crm_api_errors_total = 0
        
        # Gauges
        self.active_draft_generation_jobs = 0
        self.current_error_rate = 0.0
        
        # Histograms (latencies in milliseconds)
        self.draft_generation_latencies: List[float] = []
        self.crm_api_latencies: List[float] = []
        
        # Error tracking
        self.error_counts: Dict[str, int] = {}
        
        # Timestamps
        self._start_time = time.time()
        self._last_reset = time.time()
    
    def record_draft_generated(self, latency_ms: Optional[float] = None, error: bool = False):
        """
        Record a draft generation event.
        
        Args:
            latency_ms: Time taken to generate draft
            error: Whether generation failed
        """
        if error:
            self.drafts_failed_total += 1
        else:
            self.drafts_generated_total += 1
            if latency_ms is not None:
                self.draft_generation_latencies.append(latency_ms)
                self._trim_histograms()
    
    def record_cadence_enrollment(self):
        """Record a cadence enrollment."""
        self.cadence_enrollments_total += 1
    
    def record_crm_call(self, latency_ms: float, success: bool = True, operation: str = "unknown"):
        """
        Record a CRM API call.
        
        Args:
            latency_ms: Call duration in milliseconds
            success: Whether call succeeded
            operation: Type of operation (read, write, update, delete)
        """
        self.crm_api_calls_total += 1
        
        if success:
            self.crm_api_latencies.append(latency_ms)
            self._trim_histograms()
        else:
            self.crm_api_errors_total += 1
            self.error_counts[operation] = self.error_counts.get(operation, 0) + 1
    
    def record_error(self, error_type: str):
        """Record an error."""
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        self.drafts_failed_total += 1
    
    def set_active_jobs(self, count: int):
        """Set the current number of active draft generation jobs."""
        self.active_draft_generation_jobs = count
    
    def _trim_histograms(self):
        """Remove old entries from histograms to respect retention."""
        max_size = 10000
        
        if len(self.draft_generation_latencies) > max_size:
            self.draft_generation_latencies = self.draft_generation_latencies[-max_size:]
        
        if len(self.crm_api_latencies) > max_size:
            self.crm_api_latencies = self.crm_api_latencies[-max_size:]
    
    def update_error_rate(self):
        """Update current error rate based on recent failures."""
        total = self.drafts_generated_total + self.drafts_failed_total
        if total > 0:
            self.current_error_rate = self.drafts_failed_total / total
        else:
            self.current_error_rate = 0.0
    
    def get_uptime_seconds(self) -> int:
        """Get service uptime in seconds."""
        return int(time.time() - self._start_time)
    
    def get_percentile(self, data: List[float], percentile: float) -> Optional[float]:
        """Calculate percentile from list of values."""
        if not data:
            return None
        
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current metrics snapshot for export."""
        self.update_error_rate()
        
        draft_latencies = self.draft_generation_latencies
        crm_latencies = self.crm_api_latencies
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": self.get_uptime_seconds(),
            "drafts": {
                "generated_total": self.drafts_generated_total,
                "failed_total": self.drafts_failed_total,
                "success_rate": (
                    self.drafts_generated_total / (self.drafts_generated_total + self.drafts_failed_total)
                    if (self.drafts_generated_total + self.drafts_failed_total) > 0
                    else 0.0
                ),
                "latency": {
                    "count": len(draft_latencies),
                    "mean_ms": sum(draft_latencies) / len(draft_latencies) if draft_latencies else 0.0,
                    "median_ms": self.get_percentile(draft_latencies, 50),
                    "p95_ms": self.get_percentile(draft_latencies, 95),
                    "p99_ms": self.get_percentile(draft_latencies, 99),
                    "min_ms": min(draft_latencies) if draft_latencies else 0.0,
                    "max_ms": max(draft_latencies) if draft_latencies else 0.0,
                },
            },
            "cadence": {
                "enrollments_total": self.cadence_enrollments_total,
            },
            "crm_api": {
                "calls_total": self.crm_api_calls_total,
                "errors_total": self.crm_api_errors_total,
                "error_rate": (
                    self.crm_api_errors_total / self.crm_api_calls_total
                    if self.crm_api_calls_total > 0
                    else 0.0
                ),
                "latency": {
                    "count": len(crm_latencies),
                    "mean_ms": sum(crm_latencies) / len(crm_latencies) if crm_latencies else 0.0,
                    "median_ms": self.get_percentile(crm_latencies, 50),
                    "p95_ms": self.get_percentile(crm_latencies, 95),
                    "p99_ms": self.get_percentile(crm_latencies, 99),
                    "min_ms": min(crm_latencies) if crm_latencies else 0.0,
                    "max_ms": max(crm_latencies) if crm_latencies else 0.0,
                },
            },
            "errors": {
                "by_type": self.error_counts,
                "error_rate": self.current_error_rate,
            },
            "jobs": {
                "active": self.active_draft_generation_jobs,
            },
        }
    
    def get_prometheus_text(self) -> str:
        """Export metrics in Prometheus text format."""
        snapshot = self.get_snapshot()
        
        lines = [
            "# HELP a8_drafts_generated_total Total number of drafts generated",
            "# TYPE a8_drafts_generated_total counter",
            f"a8_drafts_generated_total {self.drafts_generated_total}",
            "",
            "# HELP a8_drafts_failed_total Total number of failed draft generations",
            "# TYPE a8_drafts_failed_total counter",
            f"a8_drafts_failed_total {self.drafts_failed_total}",
            "",
            "# HELP a8_cadence_enrollments_total Total number of cadence enrollments",
            "# TYPE a8_cadence_enrollments_total counter",
            f"a8_cadence_enrollments_total {self.cadence_enrollments_total}",
            "",
            "# HELP a8_crm_api_calls_total Total number of CRM API calls",
            "# TYPE a8_crm_api_calls_total counter",
            f"a8_crm_api_calls_total {self.crm_api_calls_total}",
            "",
            "# HELP a8_crm_api_errors_total Total number of CRM API errors",
            "# TYPE a8_crm_api_errors_total counter",
            f"a8_crm_api_errors_total {self.crm_api_errors_total}",
            "",
            "# HELP a8_draft_generation_latency_ms Draft generation latency in milliseconds",
            "# TYPE a8_draft_generation_latency_ms summary",
            f"a8_draft_generation_latency_ms_sum {sum(self.draft_generation_latencies):.2f}",
            f"a8_draft_generation_latency_ms_count {len(self.draft_generation_latencies)}",
            "",
            "# HELP a8_crm_api_latency_ms CRM API call latency in milliseconds",
            "# TYPE a8_crm_api_latency_ms summary",
            f"a8_crm_api_latency_ms_sum {sum(self.crm_api_latencies):.2f}",
            f"a8_crm_api_latency_ms_count {len(self.crm_api_latencies)}",
            "",
            "# HELP a8_active_jobs Number of active draft generation jobs",
            "# TYPE a8_active_jobs gauge",
            f"a8_active_jobs {self.active_draft_generation_jobs}",
            "",
            "# HELP a8_error_rate Current error rate (0-1)",
            "# TYPE a8_error_rate gauge",
            f"a8_error_rate {self.current_error_rate:.4f}",
            "",
        ]
        
        return "\n".join(lines)
    
    def reset(self):
        """Reset all metrics."""
        self.drafts_generated_total = 0
        self.drafts_failed_total = 0
        self.cadence_enrollments_total = 0
        self.crm_api_calls_total = 0
        self.crm_api_errors_total = 0
        self.active_draft_generation_jobs = 0
        self.current_error_rate = 0.0
        self.draft_generation_latencies.clear()
        self.crm_api_latencies.clear()
        self.error_counts.clear()
        self._last_reset = time.time()


# Global collector instance
metrics_collector = MetricsCollector()


def setup_metrics_routes(app):
    """
    Setup metrics endpoints on a FastAPI app.
    
    Adds:
    - GET /metrics/json - JSON metrics snapshot
    - GET /metrics/prometheus - Prometheus text format
    """
    
    @app.get("/metrics/json")
    async def metrics_json():
        """Return metrics as JSON."""
        return metrics_collector.get_snapshot()
    
    @app.get("/metrics/prometheus")
    async def metrics_prometheus():
        """Return metrics in Prometheus text format."""
        return metrics_collector.get_prometheus_text()
    
    @app.get("/metrics/health")
    async def metrics_health():
        """Quick health summary from metrics."""
        snapshot = metrics_collector.get_snapshot()
        
        return {
            "healthy": snapshot["drafts"]["success_rate"] > 0.95,
            "success_rate": snapshot["drafts"]["success_rate"],
            "error_rate": snapshot["errors"]["error_rate"],
            "uptime_seconds": snapshot["uptime_seconds"],
            "active_jobs": snapshot["jobs"]["active"],
        }
