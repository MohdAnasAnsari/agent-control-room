# Pre-Deployment Checklist — Multi-Agent Orchestrator

Use this checklist before every production deployment. All REQUIRED items must be checked. RECOMMENDED items should be checked for major releases.

---

## How to Use

```bash
# Automated check (prints pass/fail for each item)
./scripts/pre-deploy-check.sh --env production

# Manual review of this checklist
# Check each item, note exceptions, get sign-off
```

---

## A. Code Quality ✓

### A1. Tests (REQUIRED)

- [ ] All backend tests passing: `cd backend && pytest tests/ -v`
- [ ] Test coverage ≥ 80%: `pytest tests/ --cov=app --cov-fail-under=80`
- [ ] All frontend tests passing: `cd frontend && npm run test:ci`
- [ ] E2E tests passing: `cd e2e && npx playwright test`
- [ ] No tests skipped without documented reason

### A2. Linting (REQUIRED)

- [ ] Python lint clean: `cd backend && flake8 app/ --max-line-length=100`
- [ ] Python formatting: `cd backend && black --check app/`
- [ ] TypeScript lint: `cd frontend && npm run lint`
- [ ] No `# noqa` or `// eslint-disable` added without comment

### A3. Code Review (REQUIRED)

- [ ] PR reviewed by at least 1 other developer
- [ ] No unresolved review comments
- [ ] PR description explains what changed and why
- [ ] No large unrelated refactors bundled with the feature

---

## B. Security ✓

### B1. Static Analysis (REQUIRED)

- [ ] bandit scan clean: `cd backend && bandit -r app/ --severity-level medium`
- [ ] npm audit clean: `cd frontend && npm audit --audit-level=high`
- [ ] Trivy container scan clean (run in CI or manually)

### B2. Secrets (REQUIRED)

- [ ] No secrets committed to git: `git log -p | grep -i "sk-ant-\|password\|api_key"`
- [ ] `.env` files are in `.gitignore` and not tracked
- [ ] All production secrets set in AWS Secrets Manager (or Kubernetes secrets)
- [ ] API keys rotated if they were exposed in any previous commit

### B3. Certificates (REQUIRED for domain change)

- [ ] SSL certificate valid for ≥ 30 days: `openssl s_client -connect your-domain:443 | openssl x509 -noout -enddate`
- [ ] Certificate auto-renewal configured (ACM / cert-manager)

---

## C. Database ✓

### C1. Migrations (REQUIRED)

- [ ] All Alembic migrations tested in staging
- [ ] Migrations are backward-compatible (no DROP COLUMN without multi-release plan)
- [ ] `alembic upgrade head` succeeds on staging
- [ ] Rollback migration (`alembic downgrade -1`) tested if applicable

### C2. Backups (REQUIRED)

- [ ] Database backup taken within last 24 hours
- [ ] Backup verified restorable (restore to test environment quarterly)
- [ ] Backup stored in S3 with versioning enabled
- [ ] Automated backup schedule confirmed active

### C3. Schema Changes (REQUIRED for schema migrations)

- [ ] Added columns have DEFAULT values (avoids table lock on large tables)
- [ ] No constraint changes that would fail on existing data
- [ ] Migration estimated duration < 30s (or maintenance window scheduled)
- [ ] DBA / data team notified for migrations on tables > 1M rows

---

## D. Infrastructure ✓

### D1. Cluster Health (REQUIRED)

- [ ] All nodes Ready: `kubectl get nodes`
- [ ] No DiskPressure / MemoryPressure on nodes
- [ ] PodDisruptionBudget allows the deployment: min 1 pod available during update
- [ ] Resource requests/limits set correctly in `k8s/deployment.yaml`

### D2. Capacity (REQUIRED)

- [ ] Database CPU < 70% (check CloudWatch / Grafana)
- [ ] Database connections < 80% of max_connections
- [ ] Redis memory usage < 70%
- [ ] Node CPU/memory headroom for 1 extra pod during rolling update

### D3. Networking (REQUIRED)

- [ ] Load balancer healthy (all targets healthy in target group)
- [ ] Health check endpoint responding: `curl https://api.example.com/health`
- [ ] No VPC/security group changes that block new pod IPs

### D4. Images (REQUIRED)

- [ ] Docker images built and pushed with correct tag (git SHA)
- [ ] Images verified in registry: `docker manifest inspect <image>:<tag>`
- [ ] Multi-architecture builds (linux/amd64, linux/arm64) if using Graviton nodes

---

## E. Communication ✓

### E1. Team Notification (REQUIRED)

- [ ] Post deployment notice in `#deployments` Slack channel:
  ```
  Deploying orchestrator v<sha> to production at <time>
  Changes: <brief summary or PR link>
  Expected duration: ~5 min
  On-call: @<engineer>
  ```
- [ ] On-call engineer aware and available during deployment

### E2. Maintenance Window (REQUIRED for breaking changes)

- [ ] Maintenance window scheduled (if needed)
- [ ] Status page updated: "Maintenance scheduled"
- [ ] Customer notifications sent (if service impact expected)

### E3. Rollback Plan (REQUIRED)

- [ ] Rollback procedure confirmed (previous image tag noted)
- [ ] Previous revision available: `kubectl rollout history deployment/orchestrator-backend -n orchestrator`
- [ ] On-call knows the rollback command: `./scripts/rollback.sh`

---

## F. Post-Deployment Verification (RECOMMENDED) ✓

Complete these within 15 minutes of deployment:

- [ ] Run: `./scripts/post-deploy-verify.sh https://api.example.com`
- [ ] Home page loads (check frontend)
- [ ] Create a test workflow and execute it
- [ ] Check Grafana dashboard — no spike in error rate or latency
- [ ] Check Sentry — no new error groups in first 15 min
- [ ] Post success/failure update in `#deployments`

---

## Sign-Off

| Role | Name | Time |
|------|------|------|
| Deployer | | |
| Reviewer | | |
| On-call | | |

Exceptions (document any unchecked items and why they were skipped):

```
[Exception 1]:
[Exception 2]:
```
