# Monitoring Guide — Multi-Agent Orchestrator

## Table of Contents
1. [Stack Overview](#stack-overview)
2. [Starting the Monitoring Stack](#starting-the-monitoring-stack)
3. [Dashboards](#dashboards)
4. [Alerts](#alerts)
5. [Error Tracking (Sentry)](#error-tracking-sentry)
6. [Load Testing](#load-testing)
7. [Adding New Metrics](#adding-new-metrics)
8. [Alert Response Quick Reference](#alert-response-quick-reference)

---

## Stack Overview

| Component | URL (local) | Purpose |
|-----------|-------------|---------|
| Prometheus | http://localhost:9090 | Metrics storage and alerting rules |
| Grafana | http://localhost:3001 | Dashboards and visualization |
| AlertManager | http://localhost:9093 | Alert routing → Slack / PagerDuty |
| Sentry | https://sentry.io | Exception tracking + stack traces |

### Architecture

```
Backend (/metrics endpoint)
    │  prometheus-client (Histogram, Counter, Gauge)
    ▼
Prometheus (scrapes every 15s)
    │  Evaluates alert_rules.yml every 15s
    ├──► AlertManager ──► Slack #ops-alerts
    │                 └──► PagerDuty (critical only)
    │
    ▼
Grafana (reads Prometheus via datasource)
    ├── Overview dashboard
    ├── API Performance dashboard
    └── LLM Usage & Cost dashboard

Frontend (Sentry SDK)
    │  Captures JS exceptions + breadcrumbs
    ▼
Sentry Project (orchestrator-frontend)
    └── Issue tracker + stack traces + session replay
```

---

## Starting the Monitoring Stack

### Local development

```bash
# Start the full stack + monitoring
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

# Services:
#   Prometheus   → http://localhost:9090
#   Grafana      → http://localhost:3001  (admin / admin)
#   AlertManager → http://localhost:9093
```

### Grafana default credentials

| Setting | Value |
|---------|-------|
| Username | `admin` |
| Password | `admin` (change immediately) |

Dashboards are auto-provisioned from `monitoring/grafana/dashboards/`.

---

## Dashboards

### Overview Dashboard (`orchestrator-overview`)

**Who uses it:** On-call engineer during an incident  
**Refresh:** 30 seconds

Key panels:

| Panel | What it shows | Thresholds |
|-------|---------------|-----------|
| Service Health | Up/Down indicator | Green = up |
| Error Rate (5m) | % of 5xx responses | Yellow > 1%, Red > 5% |
| Latency p95 (5m) | p95 response time | Yellow > 1s, Red > 2s |
| Requests/min | Throughput | Informational |
| Execution Success Rate | % of workflows succeeding | Red < 99% |
| Active Executions | In-flight executions | Informational |

**How to use during an incident:**
1. Start with "Service Health" — is the backend reachable?
2. Check "Error Rate" — is it actually elevated?
3. Check "Latency" — slow or fast errors?
4. Check "Execution Success Rate" — LLM or business logic issue?
5. Zoom in on the time range to correlate with the deploy time

### API Performance Dashboard (`orchestrator-api-perf`)

**Who uses it:** Engineering, debugging slow endpoints  
**Template variables:** `endpoint` — filter to specific paths

Key panels:

| Panel | Purpose |
|-------|---------|
| Top Endpoints by Request Rate | Find busiest endpoints |
| Slowest Endpoints (p95) | Find bottlenecks |
| Latency p50/p95/p99 per endpoint | Latency distribution over time |
| Error Rate by Endpoint | Which endpoints are erroring |
| Request Volume by Endpoint | Traffic distribution |

### LLM Usage & Cost Dashboard (`orchestrator-llm`)

**Who uses it:** Product, engineering (cost monitoring), on-call  
**Template variables:** `provider`, `model`

Key panels:

| Panel | Purpose |
|-------|---------|
| Total Requests (24h) | Volume of LLM calls |
| Total Tokens (24h) | Token consumption |
| Estimated Cost (24h) | $ spend |
| Token Usage Over Time | Input vs output trends |
| LLM Latency p50/p95 by Model | Which model is slowest |
| Cumulative Cost by Model | Running cost counter |

**Cost alerting:** `HighTokenSpend` fires when > 1M tokens/hour on any model. Investigate for runaway loops or automated abuse.

---

## Alerts

All alert rules are defined in `monitoring/alert_rules.yml`.

### Alert Severities

| Severity | Response time | Routing |
|----------|--------------|---------|
| `critical` | Immediate (page on-call) | PagerDuty + Slack |
| `warning` | Within 30 minutes | Slack only |

### Alert Reference

| Alert | Threshold | Runbook |
|-------|-----------|---------|
| `HighErrorRate` | 5xx rate > 5% for 2 min | [high-error-rate.md](runbooks/high-error-rate.md) |
| `HighLatencyP99` | p99 > 5 s for 5 min | [high-latency.md](runbooks/high-latency.md) |
| `HighLatencyP95` | global p95 > 2 s for 5 min | [high-latency.md](runbooks/high-latency.md) |
| `ServiceDown` | backend unreachable for 1 min | [service-down.md](runbooks/service-down.md) |
| `HighExecutionFailureRate` | > 20% failures for 5 min | [high-error-rate.md](runbooks/high-error-rate.md) |
| `LLMProviderErrors` | > 0.1 LLM errors/s for 3 min | [high-error-rate.md](runbooks/high-error-rate.md) |
| `LLMHighLatency` | LLM p95 > 30 s for 5 min | [high-latency.md](runbooks/high-latency.md) |
| `HighTokenSpend` | > 1M tokens/hour | Manual review |

### Configuring AlertManager

Before deploying, edit `monitoring/alertmanager.yml` and replace:

| Placeholder | Replace with |
|-------------|-------------|
| `<SLACK_WEBHOOK_URL>` | Your Slack Incoming Webhook URL |
| `<PAGERDUTY_INTEGRATION_KEY>` | PagerDuty Events API v2 key |

---

## Error Tracking (Sentry)

### Setup

1. Create a project at https://sentry.io (or self-host)
2. Get two DSNs — one for backend, one for frontend
3. Add to your `.env` files:

```bash
# Backend (.env.development or .env.production)
SENTRY_DSN=https://your-key@o123.ingest.sentry.io/456

# Frontend (.env or .env.production)
VITE_SENTRY_DSN=https://your-key@o123.ingest.sentry.io/789
VITE_APP_VERSION=1.0.0
```

### What gets tracked

**Backend (FastAPI):**
- All unhandled exceptions (5xx responses)
- Slow database queries (via SQLAlchemy integration)
- `logging.error()` and `logging.critical()` calls
- Performance traces (10% sample rate in production)

**Frontend (React):**
- JavaScript runtime exceptions
- React render errors (via `ErrorBoundary`)
- User breadcrumbs (clicks, navigation, console errors)
- Session replay for error sessions (100%)

### Triage an error in Sentry

1. Open the issue — check the **stack trace** for the exact line
2. Check **breadcrumbs** — what did the user do before the error?
3. Check **tags** → `user_id`, `workflow_id`, `endpoint` for context
4. Check **similar issues** — is this a regression or new?
5. Mark `Assigned` and create a ticket; resolve after deploy

### Release tracking

Deploy marks a new release in Sentry by setting `SENTRY_RELEASE` (or `APP_VERSION`). This lets you see "which version introduced this error" on the issue page.

---

## Load Testing

### Prerequisites

```bash
# Install k6
brew install k6         # macOS
# or: https://k6.io/docs/getting-started/installation/
```

### Run a load test

```bash
# Run against local stack
docker compose up -d
k6 run load-tests/k6.js -e BASE_URL=http://localhost:8000

# Run against staging
k6 run load-tests/k6.js -e BASE_URL=https://staging.example.com

# Run with custom VUs and duration
k6 run load-tests/k6.js --vus 50 --duration 5m -e BASE_URL=http://localhost:8000
```

### Reading results

The load test prints a summary table and writes `load-tests/results.json`. Key thresholds:

| Metric | Threshold | Why |
|--------|-----------|-----|
| `http_req_duration p(95)` | < 2000 ms | p95 SLO |
| `custom_error_rate` | < 1% | Reliability SLO |

If thresholds fail, k6 exits with code 1 (CI-friendly).

### Pre-deploy load test

Run before any production deployment to catch performance regressions:

```bash
# Start staging stack
docker compose up -d

# Run load test
k6 run load-tests/k6.js -e BASE_URL=http://localhost:8000

# Check results
cat load-tests/results.json | python -m json.tool
```

---

## Adding New Metrics

### Backend (Python)

```python
# In app/core/prometheus_metrics.py, add your metric:
from prometheus_client import Counter, Histogram

MY_OPERATION_COUNT = Counter(
    "my_operation_total",
    "Description of what this counts",
    ["label1", "label2"],
)

# In your service/handler:
from app.core.prometheus_metrics import MY_OPERATION_COUNT
MY_OPERATION_COUNT.labels(label1="value1", label2="value2").inc()
```

### Add to Grafana dashboard

1. Open the relevant dashboard in Grafana
2. Click **+ Add panel**
3. Set datasource to **Prometheus**
4. Enter your PromQL query
5. Click the **Save dashboard** button
6. Export the updated JSON: **Dashboard settings → JSON Model → Copy**
7. Update the corresponding `.json` file in `monitoring/grafana/dashboards/`

---

## Alert Response Quick Reference

| Alert fires | First action | Common fix |
|-------------|-------------|-----------|
| `HighErrorRate` | `make k8s-logs \| grep ERROR` | Rollback if post-deploy |
| `HighLatencyP95` | Open API Performance dashboard | Scale up or fix slow query |
| `ServiceDown` | `kubectl get pods -n orchestrator` | Rollback or fix secret |
| `LLMProviderErrors` | Check provider status page | Enable fallback model |
| `HighExecutionFailureRate` | Check execution logs | Fix LLM prompt or DAG config |
