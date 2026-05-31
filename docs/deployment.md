# Deployment Guide — Multi-Agent Orchestrator

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Local Development](#local-development)
3. [CI/CD Pipeline](#cicd-pipeline)
4. [First-time Production Setup](#first-time-production-setup)
5. [How to Deploy](#how-to-deploy)
6. [How to Rollback](#how-to-rollback)
7. [Monitoring Post-Deploy](#monitoring-post-deploy)
8. [Secrets Management](#secrets-management)
9. [Common Troubleshooting](#common-troubleshooting)

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker | 24+ | Container runtime |
| Docker Compose | v2+ | Local dev stack |
| kubectl | 1.28+ | Kubernetes CLI |
| AWS CLI | 2.x | EKS auth + ECR login |
| make | any | Developer convenience commands |
| Python | 3.11 | Backend development |
| Node.js | 20 | Frontend development |

---

## Local Development

### Start the full stack

```bash
# Copy the dev env template and fill in your API keys
cp .env.development .env.development.local
# edit .env.development.local with real ANTHROPIC_API_KEY etc.

# Start all services (postgres, redis, backend, frontend, adminer)
make up

# or with image rebuild
make up-build
```

Services once running:

| Service | URL |
|---------|-----|
| Frontend (React) | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Adminer (DB UI) | http://localhost:8080 |

### Run tests locally

```bash
make test              # all tests (backend + frontend)
make test-backend      # pytest with coverage
make test-frontend     # vitest
make lint              # flake8 + black + eslint
make security          # bandit + npm audit
```

### Database migrations

```bash
make migrate                       # apply pending migrations
make migrate-rollback              # undo last migration
make migrate-status                # show current revision
make migrate-new msg="add table"   # generate a new migration
```

---

## CI/CD Pipeline

### Overview

```
push → main ──────────────────────────────────────────────────────────┐
                                                                        │
  ┌─ test-backend ─┐                                                    │
  ├─ test-frontend ─┤                                                   │
  ├─ lint ──────────┼──► build-and-push ──► (manual approval) ──► deploy
  └─ security-scan ─┘                                       │
                                                            │  smoke-test (10 min)
pull_request ──► test-backend + test-frontend                │
               + lint + security (no build/push)            └──► rollback (if fail)
```

### Workflow files

| File | Trigger | Purpose |
|------|---------|---------|
| `.github/workflows/deploy.yml` | push to `main` | Full CI/CD: test → build → deploy |
| `.github/workflows/test.yml` | pull_request | Lightweight PR gate (no deploy) |

### Required GitHub Secrets

Configure these in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `DOCKER_REGISTRY_URL` | ECR URL: `123456789.dkr.ecr.us-east-1.amazonaws.com` |
| `DOCKER_USERNAME` | Registry username (or use OIDC for ECR) |
| `DOCKER_PASSWORD` | Registry password / token |
| `AWS_ACCESS_KEY_ID` | IAM key with ECR + EKS permissions |
| `AWS_SECRET_ACCESS_KEY` | Corresponding secret key |
| `AWS_REGION` | e.g. `us-east-1` |
| `EKS_CLUSTER_NAME` | Name of your EKS cluster |
| `SLACK_WEBHOOK_URL` | Incoming webhook for deploy notifications |

### Branch protection rules (recommended)

In **Settings → Branches → main**:
- Require status checks: `All PR Checks Passed` (from `test.yml`)
- Require pull request reviews: 1 approver
- Restrict direct pushes

### Manual approval gate

The `deploy` job runs in the `production` GitHub environment. Configure that environment (**Settings → Environments → production**) with:
- Required reviewers (e.g., yourself or your team lead)
- Deployment branches: `main` only

Anyone pushing to main must then explicitly approve the deploy step before it runs.

---

## First-time Production Setup

### 1. Create the Kubernetes namespace

```bash
kubectl create namespace orchestrator
```

### 2. Apply the secret (fill in real values first)

```bash
# Copy the template, fill in real values
cp k8s/secret.yaml k8s/secret.local.yaml
# Edit k8s/secret.local.yaml with real DATABASE_URL, SECRET_KEY, etc.

# Apply (never commit secret.local.yaml)
kubectl apply -f k8s/secret.local.yaml
```

Or use `kubectl create secret` directly:

```bash
kubectl create secret generic orchestrator-secrets \
  --from-literal=SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=ENCRYPTION_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://user:pass@your-rds:5432/orchestrator" \
  --from-literal=REDIS_URL="rediss://your-elasticache:6379/0" \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-..." \
  --from-literal=OPENAI_API_KEY="sk-..." \
  --from-literal=GROQ_API_KEY="gsk_..." \
  -n orchestrator
```

### 3. Run initial database migrations

```bash
# From inside the cluster or via a one-off pod
kubectl run migrate --rm -it \
  --image=your-registry/orchestrator-backend:latest \
  --restart=Never \
  --env-from=secret/orchestrator-secrets \
  --env-from=configmap/orchestrator-config \
  -n orchestrator \
  -- alembic upgrade head
```

### 4. Deploy for the first time

```bash
make deploy
```

---

## How to Deploy

### Automated (recommended)

1. Merge a PR into `main`.
2. The `deploy.yml` workflow starts automatically.
3. Tests, lint, security scan, and Docker build run in parallel.
4. A GitHub environment approval prompt appears (if reviewers are configured).
5. Approve the deploy step.
6. The rolling update applies; smoke-test monitors for 10 minutes.
7. Slack receives a success or failure notification.

### Manual (emergency)

```bash
# 1. Build and push a specific image
make build push GIT_SHA=abc1234

# 2. Update the deployment with the new tag
kubectl set image deployment/orchestrator-backend \
  backend=your-registry/orchestrator-backend:abc1234 \
  -n orchestrator

# 3. Watch the rollout
kubectl rollout status deployment/orchestrator-backend -n orchestrator

# 4. Run a smoke test
make smoke-test
```

### Updating non-secret config

```bash
# Edit k8s/configmap.yaml then apply
kubectl apply -f k8s/configmap.yaml

# Restart pods to pick up the new config
kubectl rollout restart deployment/orchestrator-backend -n orchestrator
```

---

## How to Rollback

### Automatic rollback (CI/CD)

If the `smoke-test` job fails, the `rollback` job fires automatically:
1. Runs `kubectl rollout undo`.
2. Waits for the previous version to be healthy.
3. Posts a Slack alert with the details.

No manual intervention needed.

### Manual rollback

```bash
# Roll back to the previous revision
make rollback

# Verify health immediately
make smoke-test
```

### Roll back to a specific revision

```bash
# List all revisions
kubectl rollout history deployment/orchestrator-backend -n orchestrator

# Roll back to revision 5
kubectl rollout undo deployment/orchestrator-backend \
  --to-revision=5 \
  -n orchestrator

kubectl rollout status deployment/orchestrator-backend -n orchestrator
make smoke-test
```

### Roll back to a specific image tag

```bash
kubectl set image deployment/orchestrator-backend \
  backend=your-registry/orchestrator-backend:PREVIOUS_SHA \
  -n orchestrator

kubectl rollout status deployment/orchestrator-backend -n orchestrator
```

---

## Monitoring Post-Deploy

### What the smoke-test job checks

The `smoke-test` CI job polls `/health` every 30 seconds for **10 minutes**:
- Error rate < 1% (fails build if exceeded)
- 3 consecutive 5xx / timeouts trigger immediate rollback

### Check logs after a deploy

```bash
# Stream live logs
make k8s-logs

# Check recent events
kubectl describe deployment orchestrator-backend -n orchestrator

# Check individual pods
kubectl get pods -n orchestrator
kubectl logs <pod-name> -n orchestrator --previous  # previous container logs
```

### Metrics

The backend exposes Prometheus-format metrics at `/api/v1/admin/metrics/prometheus` (admin role required). Key metrics to watch:
- `request_error_rate` < 1%
- `request_p95_latency_ms` < 2000
- `execution_failure_rate` < 1%
- `db_pool_available` > 0

---

## Secrets Management

### Development

Store secrets in `.env.development.local` (gitignored). Never commit real keys.

### Production

**Recommended:** Use [AWS Secrets Manager + External Secrets Operator](https://external-secrets.io/):

```yaml
# k8s/external-secret.yaml (example)
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: orchestrator-secrets
  namespace: orchestrator
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager
  target:
    name: orchestrator-secrets
  data:
    - secretKey: SECRET_KEY
      remoteRef:
        key: /orchestrator/production/SECRET_KEY
```

**Alternative (simpler):** Store in GitHub Secrets and inject at deploy time.

### Rotate a secret

1. Update the value in AWS Secrets Manager (or GitHub Secrets).
2. Run: `kubectl rollout restart deployment/orchestrator-backend -n orchestrator`
3. Pods restart and pick up the new secret.

---

## Common Troubleshooting

### Deployment stuck on `Pending`

```bash
kubectl describe pod -l app=orchestrator-backend -n orchestrator
# Look for: Insufficient CPU/memory, image pull errors, missing secrets
```

### ImagePullBackOff

```bash
# Verify registry credentials
kubectl get secret regcred -n orchestrator -o yaml
# Re-create if needed:
kubectl create secret docker-registry regcred \
  --docker-server=your-registry \
  --docker-username=... \
  --docker-password=... \
  -n orchestrator
```

### Database connection errors

```bash
# Check the DATABASE_URL in the secret
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  python -c "from app.core.config import settings; print(settings.DATABASE_URL[:30])"

# Verify migrations are current
kubectl exec -it deploy/orchestrator-backend -n orchestrator -- \
  alembic current
```

### High error rate after deploy

```bash
# Check application logs for tracebacks
make k8s-logs | grep -i "error\|exception\|traceback"

# Rollback immediately if needed
make rollback
```

### Rollback fails (both versions unhealthy)

1. Check if the database migration introduced a breaking schema change.
2. If so, manually run `alembic downgrade -1` from inside a pod.
3. Then run `make rollback` again.
4. Alert the ops team via the Slack channel.
