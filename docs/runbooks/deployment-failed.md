# Runbook: Deployment Failed

**Alert**: Deployment failure / smoke-test failed  
**Severity**: P1  
**Response time**: < 15 minutes

---

## Symptoms

- CI `deploy` or `smoke-test` job failed
- Slack alert: "AUTOMATIC ROLLBACK executed"
- `/health` returning non-200 after deploy
- Error rate spike in Grafana after deploy time

---

## Immediate Actions (< 5 minutes)

### 1. Check automatic rollback status

```bash
# Was the automatic rollback triggered?
# Check GitHub Actions > Latest CI run > rollback job

# Was it successful?
kubectl get pods -n orchestrator -l app=orchestrator-backend
kubectl get deployment orchestrator-backend -n orchestrator \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

If automatic rollback succeeded → go to [Post-Incident](#post-incident-actions).  
If it failed → continue below.

### 2. Manual rollback

```bash
./scripts/rollback.sh
```

### 3. Verify health

```bash
curl https://api.example.com/health
./scripts/post-deploy-verify.sh https://api.example.com
```

---

## Root Cause Diagnosis

### Check pod logs for the failed deploy

```bash
# Current pods
kubectl logs -l app=orchestrator-backend -n orchestrator --tail=100

# Previous container (if restarted)
kubectl logs -l app=orchestrator-backend -n orchestrator --previous --tail=100
```

### Check events

```bash
kubectl describe deployment orchestrator-backend -n orchestrator
kubectl get events -n orchestrator --sort-by='.lastTimestamp' | tail -20
```

### Common causes

#### ImagePullBackOff
```bash
kubectl describe pod <pod-name> -n orchestrator | grep -A5 "Events:"
# Fix: verify image tag was pushed, check registry credentials
kubectl get secret regcred -n orchestrator -o yaml
```

#### OOMKilled (Out of Memory)
```bash
kubectl describe pod <pod-name> -n orchestrator | grep -A5 "Last State:"
# Fix: increase memory limits
kubectl set resources deployment orchestrator-backend \
  --limits=memory=1Gi -n orchestrator
```

#### CrashLoopBackOff (application error)
```bash
kubectl logs <pod-name> -n orchestrator --previous
# Look for: ImportError, syntax errors, database connection errors, missing env vars
```

#### Missing secrets / env vars
```bash
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  python -c "from app.core.config import settings; print(settings.DATABASE_URL[:20])"
```

#### Database migration failure
```bash
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic current
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- alembic history | head -10
# If failed migration: alembic downgrade -1 (after rolling back application)
```

---

## Post-Incident Actions

1. Confirm rollback is healthy for 10 minutes
2. Post status update: "Deployment failed and rolled back. Investigating."
3. Create GitHub issue with label `deployment-failure`:
   - What failed
   - Root cause
   - Fix planned
4. Schedule fix: reproduce in staging, get it passing CI, re-deploy
5. Run post-mortem if P0/P1

---

## Prevention

- Never merge a PR without green CI
- Test Docker image locally before deploy: `docker run --rm <image> python -c "from app.main import app; print('OK')"`
- Run E2E tests on staging before production deploy
- Review migration SQL before applying to production
