#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# pre-deploy-check.sh — Pre-Deployment Checklist Runner
# Multi-Agent Orchestrator
#
# Runs all pre-deployment checks and prints a pass/fail summary.
# Exit code 0 = all checks passed. Non-zero = at least one failed.
#
# Usage:
#   ./scripts/pre-deploy-check.sh [--env production|staging]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV="${1:---env}"; ENV="${2:-production}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

PASS=0; FAIL=0; WARN=0

check_pass() { echo -e "${GREEN}  [PASS]${NC} $*"; PASS=$((PASS+1)); }
check_fail() { echo -e "${RED}  [FAIL]${NC} $*"; FAIL=$((FAIL+1)); }
check_warn() { echo -e "${YELLOW}  [WARN]${NC} $*"; WARN=$((WARN+1)); }
section()    { echo -e "\n${BOLD}${BLUE}▶ $*${NC}"; }

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Pre-Deployment Checklist — Multi-Agent Orchestrator"
echo "  Environment: $ENV"
echo "  Date: $(date -u)"
echo "═══════════════════════════════════════════════════════════"

# ─────────────────────────────────────────────────────────────────────────────
# A. CODE QUALITY
# ─────────────────────────────────────────────────────────────────────────────
section "A. Code Quality"

# A1: Backend tests
if command -v pytest &>/dev/null && [[ -d "$ROOT_DIR/backend" ]]; then
  cd "$ROOT_DIR/backend"
  if pytest tests/ --co -q &>/dev/null 2>&1; then
    TEST_COUNT=$(pytest tests/ --co -q 2>/dev/null | tail -1 | grep -oP '\d+' | head -1 || echo "?")
    check_pass "Backend tests discovered ($TEST_COUNT tests found)"
  else
    check_fail "Backend tests not runnable — check pytest config"
  fi

  # Run tests with coverage check
  if pytest tests/ --cov=app --cov-fail-under=80 -q --tb=no &>/dev/null 2>&1; then
    COVERAGE=$(pytest tests/ --cov=app -q --tb=no 2>/dev/null | grep "TOTAL" | awk '{print $4}' || echo "?")
    check_pass "Backend tests pass (coverage: $COVERAGE)"
  else
    check_fail "Backend tests fail or coverage < 80%"
  fi
  cd "$ROOT_DIR"
else
  check_warn "pytest not found — skipping backend test check"
fi

# A2: Frontend tests
if [[ -d "$ROOT_DIR/frontend" ]] && command -v npm &>/dev/null; then
  cd "$ROOT_DIR/frontend"
  if npm run test:ci --silent &>/dev/null 2>&1; then
    check_pass "Frontend tests pass"
  else
    check_fail "Frontend tests fail — run: cd frontend && npm run test:ci"
  fi
  cd "$ROOT_DIR"
else
  check_warn "npm not found or frontend dir missing — skipping"
fi

# A3: Python lint
if command -v flake8 &>/dev/null && [[ -d "$ROOT_DIR/backend" ]]; then
  if flake8 "$ROOT_DIR/backend/app/" --max-line-length=100 --extend-ignore=E203,W503 -q &>/dev/null 2>&1; then
    check_pass "flake8 lint passes"
  else
    check_fail "flake8 lint fails — run: cd backend && flake8 app/"
  fi
else
  check_warn "flake8 not found — skipping Python lint"
fi

# A4: Python formatting
if command -v black &>/dev/null && [[ -d "$ROOT_DIR/backend" ]]; then
  if black --check "$ROOT_DIR/backend/app/" &>/dev/null 2>&1; then
    check_pass "black formatting check passes"
  else
    check_fail "black formatting fails — run: cd backend && black app/"
  fi
else
  check_warn "black not found — skipping formatting check"
fi

# A5: Frontend lint
if [[ -d "$ROOT_DIR/frontend" ]] && command -v npm &>/dev/null; then
  cd "$ROOT_DIR/frontend"
  if npm run lint --silent &>/dev/null 2>&1; then
    check_pass "ESLint passes"
  else
    check_fail "ESLint fails — run: cd frontend && npm run lint"
  fi
  cd "$ROOT_DIR"
fi

# ─────────────────────────────────────────────────────────────────────────────
# B. SECURITY CHECKS
# ─────────────────────────────────────────────────────────────────────────────
section "B. Security"

# B1: bandit
if command -v bandit &>/dev/null && [[ -d "$ROOT_DIR/backend/app" ]]; then
  if bandit -r "$ROOT_DIR/backend/app/" --severity-level medium --confidence-level medium -q &>/dev/null 2>&1; then
    check_pass "bandit security scan clean"
  else
    check_fail "bandit found security issues — run: bandit -r backend/app/"
  fi
else
  check_warn "bandit not installed — skipping Python security scan"
fi

# B2: npm audit
if [[ -d "$ROOT_DIR/frontend" ]] && command -v npm &>/dev/null; then
  cd "$ROOT_DIR/frontend"
  if npm audit --audit-level=high &>/dev/null 2>&1; then
    check_pass "npm audit clean (no high/critical vulnerabilities)"
  else
    check_fail "npm audit found high/critical vulnerabilities — run: cd frontend && npm audit"
  fi
  cd "$ROOT_DIR"
fi

# B3: .env files not committed
if git -C "$ROOT_DIR" ls-files --error-unmatch .env &>/dev/null 2>&1; then
  check_fail ".env is tracked in git — add to .gitignore and remove from index"
elif git -C "$ROOT_DIR" ls-files --error-unmatch .env.production &>/dev/null 2>&1; then
  check_fail ".env.production is tracked in git — SECURITY RISK"
else
  check_pass "No .env files tracked in git"
fi

# B4: No hardcoded secrets (basic check)
if command -v grep &>/dev/null; then
  SECRET_PATTERNS='(sk-ant-|sk_live_|AKIA[A-Z0-9]{16}|password\s*=\s*["\x27][^"\x27]{8,})'
  if git -C "$ROOT_DIR" diff HEAD~1 --unified=0 2>/dev/null | grep -qiP "$SECRET_PATTERNS" 2>/dev/null; then
    check_fail "Possible hardcoded secrets detected in recent diff — audit before deploying"
  else
    check_pass "No obvious hardcoded secrets in recent diff"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# C. DATABASE
# ─────────────────────────────────────────────────────────────────────────────
section "C. Database"

# C1: Pending migrations check
if command -v alembic &>/dev/null && [[ -d "$ROOT_DIR/backend" ]]; then
  cd "$ROOT_DIR/backend"
  PENDING=$(alembic history --indicate-current 2>/dev/null | grep -c "^>" || echo "0")
  TOTAL=$(alembic history 2>/dev/null | wc -l || echo "0")
  if [[ "$PENDING" -gt 0 ]]; then
    check_pass "Alembic migrations: $TOTAL total, current head detected"
  else
    check_warn "Could not determine migration status — verify manually"
  fi
  cd "$ROOT_DIR"
else
  check_warn "alembic not found — skipping migration check"
fi

# C2: Backup verification (check for recent backup file)
if [[ "${DATABASE_URL:-}" ]]; then
  check_warn "Verify a database backup exists before proceeding"
  check_warn "Run: pg_dump \$DATABASE_URL > backup-$(date +%Y%m%d).sql"
else
  check_warn "DATABASE_URL not set — confirm database backup was taken"
fi

# ─────────────────────────────────────────────────────────────────────────────
# D. SECRETS & CERTIFICATES
# ─────────────────────────────────────────────────────────────────────────────
section "D. Secrets & Certificates"

# D1: Required env vars
REQUIRED_SECRETS=(
  AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION
  EKS_CLUSTER_NAME DOCKER_REGISTRY_URL SLACK_WEBHOOK_URL
)
for secret in "${REQUIRED_SECRETS[@]}"; do
  if [[ -z "${!secret:-}" ]]; then
    check_fail "Required env var not set: $secret"
  else
    check_pass "$secret is set"
  fi
done

# D2: SSL certificate expiry
if command -v openssl &>/dev/null && [[ "${DOMAIN:-}" ]]; then
  EXPIRY=$(echo | openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || echo "")
  if [[ -n "$EXPIRY" ]]; then
    EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || echo 0)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    if [[ $DAYS_LEFT -lt 14 ]]; then
      check_fail "SSL certificate expires in $DAYS_LEFT days! Renew before deploying."
    elif [[ $DAYS_LEFT -lt 30 ]]; then
      check_warn "SSL certificate expires in $DAYS_LEFT days — plan renewal"
    else
      check_pass "SSL certificate valid for $DAYS_LEFT days"
    fi
  else
    check_warn "Could not check SSL certificate (DOMAIN not set or not reachable)"
  fi
else
  check_warn "Set DOMAIN env var to check SSL certificate expiry"
fi

# ─────────────────────────────────────────────────────────────────────────────
# E. INFRASTRUCTURE
# ─────────────────────────────────────────────────────────────────────────────
section "E. Infrastructure"

# E1: kubectl connectivity
if command -v kubectl &>/dev/null; then
  if kubectl cluster-info &>/dev/null; then
    SERVER=$(kubectl cluster-info 2>/dev/null | head -1 | grep -oP 'https://[^ ]+' || echo "connected")
    check_pass "Kubernetes cluster reachable ($SERVER)"
  else
    check_fail "Cannot reach Kubernetes cluster — check kubeconfig"
  fi

  # E2: Node health
  NODES_READY=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo "0")
  NODES_TOTAL=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo "0")
  if [[ "$NODES_READY" -eq "$NODES_TOTAL" ]] && [[ "$NODES_TOTAL" -gt 0 ]]; then
    check_pass "All $NODES_TOTAL nodes are Ready"
  else
    check_fail "Only ${NODES_READY}/${NODES_TOTAL} nodes Ready — cluster may be degraded"
  fi

  # E3: Namespace and secrets exist
  if kubectl get secret orchestrator-secrets -n orchestrator &>/dev/null; then
    check_pass "Secret 'orchestrator-secrets' exists in namespace"
  else
    check_fail "Secret 'orchestrator-secrets' missing — create it before deploying"
  fi
else
  check_warn "kubectl not found — skipping Kubernetes checks"
fi

# E4: Docker registry accessible
if command -v docker &>/dev/null && [[ "${DOCKER_REGISTRY_URL:-}" ]]; then
  if docker login "${DOCKER_REGISTRY_URL}" &>/dev/null 2>&1 || \
     aws ecr get-login-password --region "${AWS_REGION:-us-east-1}" &>/dev/null 2>&1; then
    check_pass "Docker registry accessible"
  else
    check_warn "Could not verify Docker registry access — check credentials"
  fi
fi

# E5: Disk space (node check via kubectl)
if command -v kubectl &>/dev/null; then
  # Check for nodes with pressure conditions
  DISK_PRESSURE=$(kubectl get nodes -o json 2>/dev/null \
    | grep -c '"DiskPressure","status":"True"' || echo "0")
  if [[ "$DISK_PRESSURE" -gt 0 ]]; then
    check_fail "$DISK_PRESSURE node(s) reporting DiskPressure"
  else
    check_pass "No DiskPressure on any nodes"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# F. GIT STATE
# ─────────────────────────────────────────────────────────────────────────────
section "F. Git State"

# F1: Clean working directory
if command -v git &>/dev/null; then
  UNCOMMITTED=$(git -C "$ROOT_DIR" status --porcelain 2>/dev/null | wc -l || echo "0")
  if [[ "$UNCOMMITTED" -eq 0 ]]; then
    check_pass "Working directory is clean"
  else
    check_warn "${UNCOMMITTED} uncommitted change(s) — ensure you're deploying the right code"
  fi

  # F2: On main branch
  BRANCH=$(git -C "$ROOT_DIR" branch --show-current 2>/dev/null || echo "unknown")
  if [[ "$BRANCH" == "main" ]] || [[ "$BRANCH" == "master" ]]; then
    check_pass "On main branch ($BRANCH)"
  else
    check_warn "Not on main branch (current: $BRANCH) — ensure this is intentional"
  fi

  # F3: Up to date with remote
  git -C "$ROOT_DIR" fetch --quiet 2>/dev/null || true
  BEHIND=$(git -C "$ROOT_DIR" rev-list --count HEAD..origin/main 2>/dev/null || echo "0")
  if [[ "$BEHIND" -eq 0 ]]; then
    check_pass "Branch is up to date with origin/main"
  else
    check_warn "Branch is $BEHIND commit(s) behind origin/main"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Pre-Deployment Checklist Summary"
echo "─────────────────────────────────────────────────────────"
echo -e "  ${GREEN}PASS${NC}: $PASS"
echo -e "  ${YELLOW}WARN${NC}: $WARN"
echo -e "  ${RED}FAIL${NC}: $FAIL"
echo "═══════════════════════════════════════════════════════════"

if [[ "$FAIL" -gt 0 ]]; then
  echo -e "\n${RED}${BOLD}DEPLOYMENT BLOCKED: $FAIL check(s) failed.${NC}"
  echo "Resolve all FAIL items before deploying to production."
  exit 1
elif [[ "$WARN" -gt 0 ]]; then
  echo -e "\n${YELLOW}${BOLD}DEPLOYMENT ALLOWED with $WARN warning(s).${NC}"
  echo "Review warnings before proceeding."
  exit 0
else
  echo -e "\n${GREEN}${BOLD}ALL CHECKS PASSED — Safe to deploy.${NC}"
  exit 0
fi
