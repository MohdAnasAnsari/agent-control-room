# Runbook: High Latency

**Alerts:**
- `HighLatencyP99` — p99 > 5 s on any endpoint for 5 minutes (warning)
- `HighLatencyP95` — global p95 > 2 s for 5 minutes (warning)  
**Severity:** Warning  
**Team:** Backend

---

## Immediate Assessment

```bash
# Open Grafana API Performance dashboard
# Look for: Slowest Endpoints (p95) table, Latency p50/p95/p99 graph

# Which endpoint is slow?
# Use the Prometheus query:
#   histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, endpoint))

# Check for in-flight heavy executions
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  python -c "
from app.core.metrics_collector import metrics_collector
import asyncio, json
print(json.dumps(asyncio.run(metrics_collector.summary().__dict__) if hasattr(metrics_collector.summary(), '__dict__') else vars(metrics_collector.summary()), indent=2))
"
```

## Common Causes & Fixes

### 1. Slow LLM API calls

**Symptoms:** `/api/v1/workflows/{id}/execute` endpoints slow; LLM Latency dashboard elevated

```bash
# Check LLM p95 by model in Grafana
# If Anthropic/OpenAI is slow → check provider status pages

# Enable faster fallback model temporarily
kubectl set env deployment/orchestrator-backend \
  DEFAULT_MODEL=llama-3.3-70b-versatile \
  LLM_FALLBACK_ENABLED=true \
  -n orchestrator
```

### 2. Slow database queries

**Symptoms:** DB-heavy endpoints slow (e.g., executions list, metrics); `db_pool_checked_out` near `db_pool_size`

```bash
# Check for long-running queries in postgres
kubectl exec -it deploy/postgres -n orchestrator -- \
  psql -U orchestrator -c "
    SELECT pid, query_start, state, query
    FROM pg_stat_activity
    WHERE state != 'idle'
    ORDER BY query_start
    LIMIT 20;"

# Check missing indexes
kubectl exec -it deploy/postgres -n orchestrator -- \
  psql -U orchestrator -c "
    SELECT schemaname, tablename, attname, n_distinct, correlation
    FROM pg_stats
    WHERE tablename IN ('executions', 'agents', 'audit_logs')
    ORDER BY tablename, attname;"
```

**Fix slow executions query:**
- Add index on `executions.status`, `executions.started_at` if missing
- Add index on `audit_logs.created_at`, `audit_logs.user_id` if missing

### 3. Connection pool exhausted

**Symptoms:** `db_pool_checked_out >= db_pool_size` sustained; requests queuing for connections

```bash
# Increase pool size temporarily
kubectl set env deployment/orchestrator-backend \
  DATABASE_POOL_SIZE=20 \
  DATABASE_MAX_OVERFLOW=30 \
  -n orchestrator

kubectl rollout restart deployment/orchestrator-backend -n orchestrator
```

### 4. Redis slow / memory pressure

**Symptoms:** Rate limiter checks slow; `/api/v1` endpoints all slow together

```bash
kubectl exec -it deploy/redis -n orchestrator -- redis-cli info memory
kubectl exec -it deploy/redis -n orchestrator -- redis-cli slowlog get 10
```

### 5. High load (traffic spike)

**Symptoms:** Latency rose with request rate; error rate normal; no LLM/DB issue

```bash
# Check requests/min in Grafana Overview dashboard

# Scale up replicas
kubectl scale deployment orchestrator-backend \
  --replicas=5 \
  -n orchestrator

kubectl rollout status deployment/orchestrator-backend -n orchestrator
```

### 6. Memory leak / GC pressure

**Symptoms:** Latency creeping up over hours; restart temporarily fixes it

```bash
# Check per-pod memory usage
kubectl top pods -n orchestrator

# Restart to clear state (short-term)
kubectl rollout restart deployment/orchestrator-backend -n orchestrator
```

## Prompt Optimization (LLM slow)

If LLM latency is consistently elevated with no provider issues:

1. Review system prompts for verbosity — shorter prompts → faster responses
2. Enable streaming responses for long outputs
3. Use a faster/cheaper model tier for non-critical paths
4. Add response caching for deterministic queries

## Escalation

If p95 > 5 s for > 15 minutes and no obvious cause:
1. Capture a Grafana snapshot and post to `#incidents`
2. Run `kubectl exec` profiling if CPU is high
3. Consider scaling to 5+ replicas while investigating
