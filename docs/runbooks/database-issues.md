# Runbook: Database Issues

**Alerts**: `HighErrorRate` (DB errors), `/health` DB unhealthy  
**Severity**: P0-P1 (production data at risk)  
**Response time**: Immediate

---

## Symptoms

- `/health` returns `{"database": "unhealthy"}` or 500
- Logs: `OperationalError`, `asyncpg.exceptions`, `connection refused`
- Grafana: `db_pool_available` → 0
- High error rate coincides with DB-related errors

---

## Triage (2 minutes)

```bash
# 1. Can the app reach the database at all?
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  python -c "
import asyncio, asyncpg
async def test():
    conn = await asyncpg.connect(process.env.get('DATABASE_URL'))
    print('OK:', await conn.fetchval('SELECT 1'))
    await conn.close()
asyncio.run(test())
"

# 2. What is the RDS instance status?
aws rds describe-db-instances \
  --db-instance-identifier orchestrator-prod \
  --query 'DBInstances[0].{Status:DBInstanceStatus,Connections:DBInstanceClass}' \
  --output table

# 3. Are there active connections?
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_stat_activity;"
```

---

## Scenario A: Connection Pool Exhausted

**Symptom**: `db_pool_available=0`, connection timeout errors

```bash
# Check active connections vs. max
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "
    SELECT count(*), state, wait_event_type
    FROM pg_stat_activity
    GROUP BY state, wait_event_type
    ORDER BY count DESC;"

# Kill idle connections
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE state = 'idle'
    AND state_change < NOW() - INTERVAL '5 minutes';"

# Temporarily restart pods to reset pool
kubectl rollout restart deployment/orchestrator-backend -n orchestrator
```

**Permanent fix**: Tune `pool_size` in `app/models/db_session.py` or scale horizontally.

---

## Scenario B: RDS Instance Unavailable

**Symptom**: All DB calls fail, RDS console shows "rebooting" or "failing-over"

```bash
# Check RDS status
aws rds describe-db-instances \
  --db-instance-identifier orchestrator-prod \
  --query 'DBInstances[0].DBInstanceStatus' --output text

# Check recent events
aws rds describe-events \
  --source-identifier orchestrator-prod \
  --source-type db-instance \
  --duration 60
```

**If Multi-AZ failover in progress** (60-120s auto-recovery):
- Wait. No action needed.
- Watch `aws rds describe-db-instances` until status is `available`.

**If no Multi-AZ** (single instance down):
- Manually reboot: `aws rds reboot-db-instance --db-instance-identifier orchestrator-prod`
- If reboot fails: restore from snapshot (see [disaster-recovery.md](../disaster-recovery.md))

---

## Scenario C: Slow Queries / High CPU

**Symptom**: DB CPU > 80% in CloudWatch, slow API responses, p95 latency spike

```bash
# Find slow queries
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "
    SELECT pid, now() - pg_stat_activity.query_start AS duration, query, state
    FROM pg_stat_activity
    WHERE state != 'idle' AND now() - pg_stat_activity.query_start > INTERVAL '5 seconds'
    ORDER BY duration DESC;"

# Kill a specific slow query
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "SELECT pg_cancel_backend(<pid>);"

# Check for missing indexes
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "
    SELECT schemaname, tablename, attname, n_distinct, correlation
    FROM pg_stats
    WHERE tablename IN ('agents', 'workflows', 'executions', 'audit_logs')
    ORDER BY tablename, attname;"

# Run ANALYZE to update statistics
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "ANALYZE VERBOSE;"
```

---

## Scenario D: Disk Full

**Symptom**: RDS `FreeStorageSpace` CloudWatch alarm fires

```bash
# Check disk usage (CloudWatch)
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name FreeStorageSpace \
  --dimensions Name=DBInstanceIdentifier,Value=orchestrator-prod \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 --statistics Average

# Identify large tables
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  psql "$DATABASE_URL" -c "
    SELECT relname AS table, pg_size_pretty(pg_total_relation_size(oid)) AS size
    FROM pg_class
    WHERE relkind = 'r'
    ORDER BY pg_total_relation_size(oid) DESC
    LIMIT 10;"

# Run retention cleanup (removes old audit logs, metrics, executions per config)
curl -X POST https://api.example.com/api/v1/admin/retention/cleanup \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# If critical: expand storage immediately
aws rds modify-db-instance \
  --db-instance-identifier orchestrator-prod \
  --allocated-storage 200 \
  --apply-immediately
```

---

## Scenario E: Failed Migration

**Symptom**: App starts with migration error, pods crash immediately

```bash
# Check current migration state
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic current
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic history | head -5

# Roll back last migration
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic downgrade -1

# Verify
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic current

# Then roll back the application image
./scripts/rollback.sh
```

---

## Escalation

If none of the above resolves the issue within 30 minutes:

1. Escalate to DBA / infrastructure team via `#ops-alerts`
2. Consider full DR procedure: [disaster-recovery.md](../disaster-recovery.md)
3. Open AWS Support ticket if RDS is unresponsive
4. Restore from backup as last resort

---

## Post-Incident

1. Confirm DB is healthy: `/health` returns `{"database": "healthy"}`
2. Run data integrity checks if data loss was suspected:
   ```bash
   kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
     psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM agents; SELECT COUNT(*) FROM workflows;"
   ```
3. Document incident and root cause
4. Add monitoring/alert if this gap was not covered before
