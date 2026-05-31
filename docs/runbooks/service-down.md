# Runbook: Service Down

**Alert:** `ServiceDown` — `up{job="orchestrator-backend"} == 0` for 1 minute  
**Severity:** Critical  
**Team:** Backend

---

## Immediate Triage (first 5 minutes)

```bash
# 1. Check pod status
kubectl get pods -n orchestrator -o wide
# Expected: 3 pods Running 1/1

# 2. Check events for clues
kubectl get events -n orchestrator --sort-by='.lastTimestamp' | tail -20

# 3. Check if the LoadBalancer is healthy
kubectl get svc orchestrator-backend -n orchestrator
# Check EXTERNAL-IP is assigned

# 4. Try reaching /health directly via port-forward (bypass LB)
kubectl port-forward deploy/orchestrator-backend 8001:8000 -n orchestrator &
curl http://localhost:8001/health
```

## Common Causes & Fixes

### 1. All pods in CrashLoopBackOff

```bash
kubectl get pods -n orchestrator
# STATUS: CrashLoopBackOff, RESTARTS > 2

# Get crash logs
kubectl logs -l app=orchestrator-backend -n orchestrator --previous

# Common causes:
#   a) Bad env var / missing secret → check startup logs
#   b) Database migration failed   → see section below
#   c) Port conflict               → check logs for "Address already in use"
#   d) Bad image                   → see "Bad deploy" section
```

**If migration failed at startup:**

```bash
kubectl run migration-fix --rm -it \
  --image=your-registry/orchestrator-backend:previous-sha \
  --restart=Never \
  --env-from=secret/orchestrator-secrets \
  --env-from=configmap/orchestrator-config \
  -n orchestrator \
  -- alembic downgrade -1

# Then rollback the deployment
make rollback
```

### 2. ImagePullBackOff

```bash
kubectl describe pod -l app=orchestrator-backend -n orchestrator
# Look for: "Failed to pull image"

# Check ECR credentials
kubectl get secret regcred -n orchestrator -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d

# Renew ECR token (expires every 12 h)
aws ecr get-login-password --region us-east-1 | \
  kubectl create secret docker-registry regcred \
    --docker-server=your-registry \
    --docker-username=AWS \
    --docker-password-stdin \
    -n orchestrator \
    --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/orchestrator-backend -n orchestrator
```

### 3. Secret / ConfigMap missing

```bash
kubectl get secret orchestrator-secrets -n orchestrator
kubectl get configmap orchestrator-config -n orchestrator

# If missing, re-apply (see First-time Setup in deployment.md)
```

### 4. Node pressure (disk / memory)

```bash
kubectl get nodes
# Look for: STATUS=MemoryPressure, DiskPressure, or NotReady

kubectl describe node <node-name>
# Check: Conditions, Allocated resources

# Drain the unhealthy node and let K8s reschedule
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

### 5. Bad deploy

```bash
# If service was just deployed and went down immediately
make rollback

# Verify
make smoke-test
```

### 6. Network policy blocking Prometheus scrape

```bash
# This won't affect service availability but will trigger ServiceDown alert
kubectl exec -it prometheus-pod -n monitoring -- \
  wget -qO- http://orchestrator-backend.orchestrator:8000/metrics | head -5

# If connection refused: check NetworkPolicy in the orchestrator namespace
```

## Manual Recovery Procedure

If automated rollback failed:

```bash
# Step 1: get a list of available image versions
kubectl rollout history deployment/orchestrator-backend -n orchestrator

# Step 2: roll back to a specific known-good revision
kubectl rollout undo deployment/orchestrator-backend \
  --to-revision=<LAST_GOOD_REVISION> \
  -n orchestrator

# Step 3: monitor rollout
kubectl rollout status deployment/orchestrator-backend -n orchestrator

# Step 4: verify health
make smoke-test
```

## Escalation

If service is not recovered within 10 minutes:
1. Declare an incident in `#incidents`
2. Page secondary on-call
3. Check cloud provider status (AWS/GCP) for regional issues
4. If database is also affected, follow `database-issues.md`

## Uptime SLO Impact

| Downtime | SLO Impact |
|----------|-----------|
| < 5 min | No impact (within error budget) |
| 5–30 min | Yellow — investigate root cause |
| > 30 min | Red — post-mortem required |
| > 1 hour | SLO breach — executive escalation |
