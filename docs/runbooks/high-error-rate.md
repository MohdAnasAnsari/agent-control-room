# Runbook: High Error Rate

**Alert:** `HighErrorRate` — error rate > 5% for 2 minutes  
**Severity:** Critical  
**Team:** Backend

---

## Immediate Assessment (first 2 minutes)

```bash
# 1. Check if the service is up
make smoke-test
# or:
curl http://<SERVICE_URL>/health

# 2. Check recent error logs
make k8s-logs | grep -i "error\|exception\|500" | tail -50

# 3. Check pod health
kubectl get pods -n orchestrator
kubectl describe pod -l app=orchestrator-backend -n orchestrator
```

## Common Causes & Fixes

### 1. Database connectivity failure

**Symptoms:** Logs show `asyncpg.exceptions.ConnectionError` or `pool timeout`

```bash
# Check DB pod
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  python -c "from app.models.db_session import engine; print('DB OK')"

# Check pool metrics in Grafana: db_pool_checked_out vs db_pool_size
# If pool exhausted: restart backend to reset connections
kubectl rollout restart deployment/orchestrator-backend -n orchestrator
```

### 2. Redis unavailable

**Symptoms:** Logs show `redis.exceptions.ConnectionError`; rate limiter falls back to in-memory

```bash
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  python -c "import redis, os; r = redis.from_url(os.environ['REDIS_URL']); print(r.ping())"
```
Redis failure is non-fatal (rate limiter degrades gracefully), but investigate.

### 3. LLM provider API errors

**Symptoms:** `anthropic.APIError`, `openai.OpenAIError` in logs; `llm_requests_total{status="error"}` spiking

```bash
# Check Grafana: LLM Usage dashboard → LLM Requests/min by Status
# Check Anthropic status: https://status.anthropic.com
# Check OpenAI status:    https://status.openai.com

# Temporary mitigation: enable fallback model
kubectl set env deployment/orchestrator-backend \
  LLM_FALLBACK_ENABLED=true \
  -n orchestrator
```

### 4. Bad deploy introduced a regression

```bash
# Compare error rate timeline with deployment time in Grafana
# If error rate started at deploy time → rollback

make rollback
```

### 5. Memory pressure / OOM kills

**Symptoms:** Pods in `OOMKilled` state

```bash
kubectl get pods -n orchestrator
# Look for: STATUS=OOMKilled or RESTARTS > 0

# Check memory usage
kubectl top pods -n orchestrator

# Short-term: increase memory limit
kubectl patch deployment orchestrator-backend -n orchestrator \
  --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"1Gi"}]'
```

## Escalation

If not resolved within 15 minutes:
1. Post in `#incidents` with: alert link, Grafana snapshot, relevant log lines
2. Ping on-call backend engineer
3. Consider full rollback if error rate remains > 10%

## Post-Incident

After resolution, file a post-mortem within 24 hours covering:
- Root cause
- Timeline
- Detection gap (how long before alert fired)
- Prevention: add test / circuit breaker / monitoring
