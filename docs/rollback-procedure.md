# Rollback Procedure — Multi-Agent Orchestrator

## Decision Tree

```
Deployment went wrong?
         │
         ▼
    Smoke tests fail in CI?
    ├── YES → Automatic rollback fires (CI job 8)
    │          No action needed — monitor Slack
    └── NO (issue noticed post-deploy)
              │
              ▼
         Is it a database migration issue?
         ├── YES → See: Database Migration Rollback
         └── NO
                   │
                   ▼
              Manual rollback: ./scripts/rollback.sh
```

---

## 1. Automatic Rollback (CI/CD)

The CI pipeline monitors `/health` for 10 minutes post-deploy. If it detects:
- 3 consecutive health-check failures, OR
- Error rate > 1%

It automatically runs `kubectl rollout undo` and posts a Slack alert.

**You don't need to do anything.** Just watch the Slack `#deployments` channel.

If the automatic rollback also fails, see [Manual Rollback](#2-manual-rollback).

---

## 2. Manual Rollback

### Quick rollback (one command)

```bash
./scripts/rollback.sh
```

This rolls back to the previous Kubernetes revision, waits for health, and runs verification.

### Roll back to a specific revision

```bash
# See all revisions
kubectl rollout history deployment/orchestrator-backend -n orchestrator

# Roll back to revision 5
./scripts/rollback.sh --revision 5

# Or directly:
kubectl rollout undo deployment/orchestrator-backend --to-revision=5 -n orchestrator
kubectl rollout status deployment/orchestrator-backend -n orchestrator --timeout=180s
```

### Roll back to a specific image tag

```bash
./scripts/rollback.sh --image-tag abc1234

# Or directly:
kubectl set image deployment/orchestrator-backend \
  backend=your-registry/orchestrator-backend:abc1234 \
  -n orchestrator
kubectl rollout status deployment/orchestrator-backend -n orchestrator
```

### Verify after rollback

```bash
# Health check
curl https://api.example.com/health

# Run full verification
./scripts/post-deploy-verify.sh https://api.example.com

# Check logs
kubectl logs -l app=orchestrator-backend -n orchestrator --tail=50
```

---

## 3. Database Migration Rollback

This is the most dangerous scenario. Database migrations are often irreversible.

### Assessment first

```bash
# Connect to a pod and check current migration state
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic current

# Compare with last known-good revision from git
git log --oneline alembic/versions/
```

### Option A: Downgrade migration (if data allows)

```bash
# Dry-run: show what would be undone
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic downgrade -1 --sql

# If safe to proceed:
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic downgrade -1

# Then roll back the application
./scripts/rollback.sh --no-verify
kubectl rollout status deployment/orchestrator-backend -n orchestrator
```

### Option B: Restore database from backup (data loss possible)

**Only if migration downgrade is impossible (e.g., data was deleted).**

```bash
# 1. Get latest backup snapshot identifier
aws rds describe-db-snapshots \
  --db-instance-identifier orchestrator-prod \
  --snapshot-type automated \
  --region us-east-1 \
  --query 'DBSnapshots | sort_by(@, &SnapshotCreateTime) | [-1].DBSnapshotIdentifier' \
  --output text

# 2. Restore to a new instance
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier orchestrator-restored \
  --db-snapshot-identifier <snapshot-id> \
  --region us-east-1

# 3. Wait for instance to be available (~10-20 min)
aws rds wait db-instance-available --db-instance-identifier orchestrator-restored

# 4. Get the new endpoint
aws rds describe-db-instances \
  --db-instance-identifier orchestrator-restored \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text

# 5. Update the Kubernetes secret with the new DATABASE_URL
kubectl create secret generic orchestrator-secrets \
  --from-literal=DATABASE_URL="postgresql+asyncpg://user:pass@<new-endpoint>:5432/orchestrator" \
  -n orchestrator \
  --dry-run=client -o yaml | kubectl apply -f -

# 6. Restart pods to pick up new secret
kubectl rollout restart deployment/orchestrator-backend -n orchestrator
kubectl rollout status deployment/orchestrator-backend -n orchestrator

# 7. Roll back application image
./scripts/rollback.sh --no-verify
```

---

## 4. Blue/Green Rollback

If using blue/green deployment, rollback is instant:

```bash
# Switch load balancer back to previous slot (e.g., blue)
kubectl patch service orchestrator-backend -n orchestrator \
  --type=json \
  -p='[{"op": "replace", "path": "/spec/selector/slot", "value": "blue"}]'

# Verify
curl https://api.example.com/health
```

---

## 5. Rollback Fails — Escalation Path

If both the new and old versions are unhealthy:

1. **Page on-call**: `#ops-alerts` + PagerDuty
2. **Scale down to 0** to stop serving errors: `kubectl scale deployment orchestrator-backend --replicas=0 -n orchestrator`
3. **Update status page**: Set to "Investigating"
4. **Diagnose root cause**:
   - Check pod logs: `kubectl logs -l app=orchestrator-backend -n orchestrator --tail=100 --previous`
   - Check events: `kubectl describe deployment orchestrator-backend -n orchestrator`
   - Check database connectivity and migration state
5. **If database is corrupted**: Follow [Option B (Restore from Backup)](#option-b-restore-database-from-backup-data-loss-possible)
6. **Contact infrastructure team** if cluster-level issue suspected

---

## 6. Post-Rollback Actions (within 1 hour)

1. Confirm `/health` returns 200 and all verification checks pass
2. Post in `#deployments`: "Rolled back to <previous-tag>. Investigating root cause."
3. Open a post-mortem issue in GitHub
4. Annotate the deploy-history log: `docs/deploy-history.log`
5. Schedule post-mortem within 48 hours

---

## Reference

| Command | Purpose |
|---------|---------|
| `./scripts/rollback.sh` | One-click rollback to previous revision |
| `./scripts/rollback.sh --revision N` | Rollback to specific revision |
| `./scripts/rollback.sh --image-tag SHA` | Rollback to specific image |
| `./scripts/post-deploy-verify.sh` | Full health verification |
| `kubectl rollout history deployment/orchestrator-backend -n orchestrator` | List available revisions |
| `kubectl rollout undo deployment/orchestrator-backend -n orchestrator` | Direct kubectl rollback |
| `make rollback` | Makefile shortcut |
| `make smoke-test` | Run smoke tests manually |
