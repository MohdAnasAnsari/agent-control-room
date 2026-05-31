# Disaster Recovery Plan — Multi-Agent Orchestrator

## Recovery Objectives

| Metric | Target | Notes |
|--------|--------|-------|
| RTO (Recovery Time Objective) | < 30 minutes | Time from incident detection to service restored |
| RPO (Recovery Point Objective) | < 1 hour | Maximum data loss acceptable |
| Backup retention | 7 days (RDS) / 30 days (S3) | Automated |
| DR drill frequency | Quarterly | See `docs/dr-test-log.md` |

---

## Failure Scenarios & Playbooks

### Scenario 1: Pod Crash / Application Error

**Symptoms**: Health check fails, pods in CrashLoopBackOff  
**Auto-recovery**: Kubernetes restarts the container automatically  
**Manual steps if auto-recovery fails**:

```bash
# Check what's happening
kubectl describe pod -l app=orchestrator-backend -n orchestrator
kubectl logs -l app=orchestrator-backend -n orchestrator --previous --tail=100

# If bad deploy: rollback
./scripts/rollback.sh

# If OOM kill: increase memory limits
kubectl set resources deployment orchestrator-backend \
  --limits=memory=1Gi -n orchestrator
```

**Runbook**: [service-down.md](runbooks/service-down.md)

---

### Scenario 2: Bad Deployment

**Symptoms**: New deploy causes errors, latency spikes, or crashes  
**Auto-recovery**: CI smoke-test detects it and triggers `kubectl rollout undo`  
**Manual rollback**:

```bash
./scripts/rollback.sh
```

**Recovery time**: 3-10 minutes  
**Runbook**: [deployment-failed.md](runbooks/deployment-failed.md)

---

### Scenario 3: Database Failure

**Symptoms**: 500 errors with "database" in message, `/health` shows DB unhealthy

#### 3a. RDS Instance Crash (auto-recovery)

RDS Multi-AZ automatically fails over to standby within 60-120 seconds.  
No action required unless failover doesn't complete.

```bash
# Check RDS event log
aws rds describe-events \
  --source-identifier orchestrator-prod \
  --source-type db-instance \
  --duration 60
```

#### 3b. Database Corruption / Manual Recovery

```bash
# 1. Identify latest clean backup
aws rds describe-db-snapshots \
  --db-instance-identifier orchestrator-prod \
  --snapshot-type automated \
  --query 'DBSnapshots | sort_by(@, &SnapshotCreateTime) | [-1]' \
  --output json

# 2. Restore to new instance
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier orchestrator-prod-restored \
  --db-snapshot-identifier <snapshot-id> \
  --db-instance-class db.t3.medium \
  --no-multi-az

# 3. Wait for instance availability
aws rds wait db-instance-available \
  --db-instance-identifier orchestrator-prod-restored

# 4. Get endpoint
NEW_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier orchestrator-prod-restored \
  --query 'DBInstances[0].Endpoint.Address' --output text)

# 5. Update secret
kubectl create secret generic orchestrator-secrets \
  --from-literal=DATABASE_URL="postgresql+asyncpg://user:pass@${NEW_ENDPOINT}:5432/orchestrator" \
  -n orchestrator --dry-run=client -o yaml | kubectl apply -f -

# 6. Restart pods
kubectl rollout restart deployment/orchestrator-backend -n orchestrator
kubectl rollout status deployment/orchestrator-backend -n orchestrator
```

**Recovery time**: 20-45 minutes  
**Data loss**: Up to 5 minutes (RDS automated backup interval)

---

### Scenario 4: Redis Failure

**Symptoms**: Rate limiting disabled, session issues, but core API still works  
**Impact**: Low — Redis failure triggers in-memory fallback automatically  
**Recovery**:

```bash
# ElastiCache failover (if multi-AZ)
aws elasticache failover-replication-group \
  --replication-group-id orchestrator-cache \
  --node-group-id 0001

# Or restart pods to reconnect
kubectl rollout restart deployment/orchestrator-backend -n orchestrator
```

**Recovery time**: 2-5 minutes

---

### Scenario 5: Kubernetes Node Failure

**Symptoms**: Some pods are "Pending" or "Terminating", node shows "NotReady"  
**Auto-recovery**: Kubernetes reschedules pods to healthy nodes  
**If not auto-recovered**:

```bash
# Cordon the bad node
kubectl cordon <node-name>

# Drain (evict pods)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# Check remaining nodes
kubectl get nodes

# Scale up if capacity is insufficient
# (EKS auto-scaling should handle this automatically)
```

**Recovery time**: 2-5 minutes (with 3 replicas)

---

### Scenario 6: Full Region Outage

**Symptoms**: AWS us-east-1 unavailable, all services down  
**Recovery** (cross-region failover to DR region):

```bash
# 1. Switch to DR region
export AWS_REGION=us-west-2

# 2. Update kubeconfig to DR cluster
aws eks update-kubeconfig \
  --name orchestrator-dr \
  --region us-west-2

# 3. Verify DR cluster is ready
kubectl get nodes
kubectl get pods -n orchestrator

# 4. Restore latest RDS snapshot in DR region
# (cross-region snapshot copy should be pre-configured)
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier orchestrator-prod \
  --db-snapshot-identifier <cross-region-snapshot-id> \
  --region us-west-2

# 5. Update secrets in DR cluster
kubectl create secret generic orchestrator-secrets \
  --from-literal=DATABASE_URL="postgresql+asyncpg://..." \
  -n orchestrator --dry-run=client -o yaml | kubectl apply -f -

# 6. Update DNS to point to DR region
# (Route 53 failover routing policy should handle this automatically)
aws route53 change-resource-record-sets \
  --hosted-zone-id <zone-id> \
  --change-batch file://dr-dns-failover.json

# 7. Verify
curl https://api.example.com/health
./scripts/post-deploy-verify.sh https://api.example.com
```

**Recovery time**: 15-30 minutes  
**Data loss**: Up to 1 hour (cross-region replication lag)

---

## Communication Protocol

### Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|---------|
| P0 | Complete outage | Immediate (< 5 min) | All pods down, database gone |
| P1 | Partial outage / data at risk | < 15 min | >50% errors, DB corruption |
| P2 | Degraded performance | < 30 min | High latency, intermittent errors |
| P3 | Minor issue | Next business day | Single pod crash (auto-recovered) |

### Incident Response

1. **Page on-call** (P0/P1): PagerDuty alert fires automatically via Alertmanager
2. **Post in `#ops-alerts`**: "Investigating [issue]. On-call: @<name>. Next update in 15 min."
3. **Update status page** (statuspage.io or similar): Set to "Investigating"
4. **Create incident** in GitHub Issues with label `incident`
5. **Every 15 minutes**: Post update in Slack with current status
6. **On resolution**: Close incident, post final update, schedule post-mortem

### Status Page Update Templates

**Investigating**:
```
We are investigating reports of [issue]. Our team is actively working on a resolution.
```

**Identified**:
```
We have identified the issue: [root cause]. We are implementing a fix.
Expected resolution: [time].
```

**Resolved**:
```
This incident has been resolved. [Brief description of fix].
We will publish a post-mortem within 48 hours.
```

---

## Backup Schedule

| Backup Type | Frequency | Retention | Location |
|-------------|-----------|-----------|----------|
| RDS automated snapshots | Daily | 7 days | Same region (RDS) |
| RDS manual snapshots | Pre-deploy | 30 days | Same region (RDS) |
| Cross-region backup | Daily | 14 days | DR region (S3) |
| Database dump (pg_dump) | Daily | 30 days | S3 with versioning |

### Take a Manual Backup (pre-deployment)

```bash
# RDS snapshot (AWS managed)
aws rds create-db-snapshot \
  --db-instance-identifier orchestrator-prod \
  --db-snapshot-identifier "pre-deploy-$(date +%Y%m%d-%H%M)" \
  --region us-east-1

# Or pg_dump to S3
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  pg_dump "$DATABASE_URL" | gzip | \
  aws s3 cp - "s3://your-orchestrator-backups/manual/backup-$(date +%Y%m%d-%H%M).sql.gz"
```

### Verify Backup Integrity (monthly)

```bash
# Restore to a test instance and run migrations
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier orchestrator-backup-verify \
  --db-snapshot-identifier <snapshot-id>

# Wait and connect
aws rds wait db-instance-available --db-instance-identifier orchestrator-backup-verify
ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier orchestrator-backup-verify \
  --query 'DBInstances[0].Endpoint.Address' --output text)

# Verify tables exist and have data
psql "postgresql://user:pass@${ENDPOINT}:5432/orchestrator" \
  -c "SELECT COUNT(*) FROM agents; SELECT COUNT(*) FROM workflows;"

# Clean up
aws rds delete-db-instance \
  --db-instance-identifier orchestrator-backup-verify \
  --skip-final-snapshot
```

---

## DR Testing

Run quarterly. Script: `./scripts/disaster-recovery.sh test`

Document results in `docs/dr-test-log.md`.

### DR Test Checklist

- [ ] Verify backup exists and is recent
- [ ] Test backup restoration to a non-production instance
- [ ] Verify rollback works: `./scripts/rollback.sh --dry-run`
- [ ] Test Kubernetes node drain and pod reschedule
- [ ] Verify Alertmanager → PagerDuty → Slack chain
- [ ] Verify status page can be updated
- [ ] Confirm on-call runbooks are current
- [ ] Estimate and document RTO for each scenario
- [ ] Update `docs/dr-test-log.md` with results

---

## DR Test Log

See [dr-test-log.md](dr-test-log.md) for drill history.

---

## Key Contacts

| Role | Contact | How to Reach |
|------|---------|--------------|
| On-call Engineer | Rotation | PagerDuty: /project/orchestrator |
| Database Admin | [Name] | Slack: @db-team |
| Infrastructure | [Name] | Slack: #infrastructure |
| Security | [Name] | Slack: #security |
| AWS Support | Enterprise Support | console.aws.amazon.com/support |
