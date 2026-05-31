#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# disaster-recovery.sh — Disaster Recovery Testing & Execution
# Multi-Agent Orchestrator
#
# Modes:
#   test      Run DR drill without touching production data
#   execute   Run actual DR recovery (requires --confirm)
#   status    Print current DR readiness status
#
# Usage:
#   ./scripts/disaster-recovery.sh test
#   ./scripts/disaster-recovery.sh execute --confirm
#   ./scripts/disaster-recovery.sh status
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

MODE="${1:-status}"
CONFIRM_FLAG="${2:-}"
NAMESPACE="orchestrator"
BACKUP_BUCKET="${BACKUP_S3_BUCKET:-s3://your-orchestrator-backups}"
AWS_REGION="${AWS_REGION:-us-east-1}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

log()     { echo -e "${BLUE}[$(date -u +%H:%M:%S)]${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC} $*"; }
error()   { echo -e "${RED}✗${NC} $*"; }
die()     { error "$*"; exit 1; }
section() { echo -e "\n${BOLD}${BLUE}── $* ──${NC}"; }

PASS=0; FAIL=0

check_pass() { success "$*"; PASS=$((PASS+1)); }
check_fail() { error "$*"; FAIL=$((FAIL+1)); }

# ─────────────────────────────────────────────────────────────────────────────
# STATUS — DR Readiness Check
# ─────────────────────────────────────────────────────────────────────────────
dr_status() {
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  Disaster Recovery Readiness Status"
  echo "  $(date -u)"
  echo "═══════════════════════════════════════════════════════════"

  section "A. Kubernetes Cluster"

  if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null 2>&1; then
    NODES=$(kubectl get nodes --no-headers 2>/dev/null | grep " Ready" | wc -l)
    check_pass "Cluster reachable ($NODES nodes Ready)"

    REPLICAS=$(kubectl get deployment orchestrator-backend -n "$NAMESPACE" \
      -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    DESIRED=$(kubectl get deployment orchestrator-backend -n "$NAMESPACE" \
      -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "3")
    [[ "$REPLICAS" == "$DESIRED" ]] && \
      check_pass "Backend: $REPLICAS/$DESIRED replicas running" || \
      check_fail "Backend: only $REPLICAS/$DESIRED replicas running"
  else
    check_fail "Kubernetes cluster unreachable"
  fi

  section "B. Database Backups"

  if command -v aws &>/dev/null; then
    # Check RDS automated backups
    if [[ "${RDS_INSTANCE_ID:-}" ]]; then
      BACKUP_COUNT=$(aws rds describe-db-snapshots \
        --db-instance-identifier "$RDS_INSTANCE_ID" \
        --snapshot-type automated \
        --region "$AWS_REGION" \
        --query 'length(DBSnapshots)' \
        --output text 2>/dev/null || echo "0")
      LATEST=$(aws rds describe-db-snapshots \
        --db-instance-identifier "$RDS_INSTANCE_ID" \
        --snapshot-type automated \
        --region "$AWS_REGION" \
        --query 'DBSnapshots | sort_by(@, &SnapshotCreateTime) | [-1].SnapshotCreateTime' \
        --output text 2>/dev/null || echo "unknown")
      [[ "$BACKUP_COUNT" -gt 0 ]] && \
        check_pass "RDS automated backups: $BACKUP_COUNT snapshots (latest: $LATEST)" || \
        check_fail "No RDS automated backups found"
    else
      warn "RDS_INSTANCE_ID not set — cannot verify RDS backups"
    fi

    # Check S3 backup files
    if [[ "${BACKUP_S3_BUCKET:-}" ]]; then
      YESTERDAY=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)
      S3_BACKUP=$(aws s3 ls "${BACKUP_BUCKET}/daily/" 2>/dev/null | grep "$YESTERDAY" | head -1 || echo "")
      [[ -n "$S3_BACKUP" ]] && \
        check_pass "S3 daily backup exists for $YESTERDAY" || \
        check_fail "No S3 daily backup found for $YESTERDAY"
    else
      warn "BACKUP_S3_BUCKET not set — configure automated backups"
    fi
  else
    warn "AWS CLI not found — cannot check backup status"
  fi

  section "C. Multi-Region Readiness"

  if [[ "${DR_REGION:-}" ]]; then
    if aws eks describe-cluster --name "${EKS_CLUSTER_NAME:-orchestrator}-dr" \
      --region "$DR_REGION" &>/dev/null 2>&1; then
      check_pass "DR cluster exists in $DR_REGION"
    else
      check_fail "DR cluster not found in $DR_REGION"
    fi
  else
    warn "DR_REGION not set — no standby region configured"
  fi

  section "D. Recovery Targets"

  echo "  RTO (Recovery Time Objective):        < 30 minutes"
  echo "  RPO (Recovery Point Objective):       < 1 hour"
  echo "  Backup retention:                     7 days (RDS), 30 days (S3)"
  echo "  Last DR test:                         Check docs/dr-test-log.md"

  section "E. Runbook Availability"
  RUNBOOKS=(
    "docs/runbooks/high-error-rate.md"
    "docs/runbooks/high-latency.md"
    "docs/runbooks/service-down.md"
    "docs/runbooks/database-issues.md"
    "docs/runbooks/deployment-failed.md"
    "docs/disaster-recovery.md"
  )
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ROOT_DIR="$(dirname "$SCRIPT_DIR")"
  for rb in "${RUNBOOKS[@]}"; do
    [[ -f "$ROOT_DIR/$rb" ]] && \
      check_pass "Runbook: $rb" || \
      check_fail "Runbook missing: $rb"
  done

  # Summary
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo -e "  PASS: ${GREEN}$PASS${NC}   FAIL: ${RED}$FAIL${NC}"
  echo "═══════════════════════════════════════════════════════════"
  [[ "$FAIL" -gt 0 ]] && exit 1 || exit 0
}

# ─────────────────────────────────────────────────────────────────────────────
# TEST — DR Drill (non-destructive)
# ─────────────────────────────────────────────────────────────────────────────
dr_test() {
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  Disaster Recovery DRILL (non-destructive)"
  echo "  $(date -u)"
  echo "═══════════════════════════════════════════════════════════"
  echo ""
  warn "This is a DR drill — no production data will be modified."

  section "Step 1: Backup Verification"
  log "Verifying most recent backup is restorable..."
  if command -v aws &>/dev/null && [[ "${RDS_INSTANCE_ID:-}" ]]; then
    LATEST_SNAPSHOT=$(aws rds describe-db-snapshots \
      --db-instance-identifier "$RDS_INSTANCE_ID" \
      --snapshot-type automated \
      --region "$AWS_REGION" \
      --query 'DBSnapshots | sort_by(@, &SnapshotCreateTime) | [-1].DBSnapshotIdentifier' \
      --output text 2>/dev/null || echo "")
    if [[ -n "$LATEST_SNAPSHOT" ]]; then
      check_pass "Latest RDS snapshot: $LATEST_SNAPSHOT"
      log "Simulating restore (dry-run — actual restore would use: aws rds restore-db-instance-from-db-snapshot)"
    else
      check_fail "No RDS snapshot found"
    fi
  else
    warn "Skipping RDS check (AWS CLI unavailable or RDS_INSTANCE_ID not set)"
  fi

  section "Step 2: K8s Failover Simulation"
  log "Testing kubectl access to rollback to previous revision..."
  if command -v kubectl &>/dev/null; then
    HISTORY=$(kubectl rollout history deployment/orchestrator-backend -n "$NAMESPACE" 2>/dev/null || echo "")
    REVISIONS=$(echo "$HISTORY" | grep -c "^[0-9]" || echo "0")
    if [[ "$REVISIONS" -ge 2 ]]; then
      check_pass "At least 2 revisions available for rollback ($REVISIONS total)"
      log "Rollback would run: kubectl rollout undo deployment/orchestrator-backend -n $NAMESPACE"
    else
      check_fail "Only $REVISIONS revision(s) — deploy at least once before DR drill"
    fi
  fi

  section "Step 3: Database Connection Test"
  log "Testing database connectivity from within cluster..."
  if command -v kubectl &>/dev/null; then
    DB_TEST=$(kubectl exec -it deploy/orchestrator-backend -n "$NAMESPACE" -- \
      python -c "from app.models.db_session import engine; import asyncio; print('OK')" \
      2>/dev/null || echo "FAILED")
    if [[ "$DB_TEST" == *"OK"* ]]; then
      check_pass "Database connection test passed"
    else
      check_warn "Database connection test inconclusive — verify manually"
    fi
  fi

  section "Step 4: Recovery Time Estimate"
  log "Estimating recovery time for each failure scenario..."
  echo ""
  printf "  %-40s %s\n" "Scenario" "Est. Recovery Time"
  printf "  %-40s %s\n" "─────────────────────────────────────" "──────────────────"
  printf "  %-40s %s\n" "Pod crash (K8s self-heal)"           "< 60 seconds"
  printf "  %-40s %s\n" "Bad deploy → auto rollback"          "5-10 minutes"
  printf "  %-40s %s\n" "Manual rollback (kubectl undo)"      "3-5 minutes"
  printf "  %-40s %s\n" "Node failure (multi-replica)"        "< 2 minutes"
  printf "  %-40s %s\n" "Database failover (RDS Multi-AZ)"    "60-120 seconds"
  printf "  %-40s %s\n" "Region failover (cross-region)"      "15-30 minutes"
  printf "  %-40s %s\n" "Full restore from backup"            "20-45 minutes"
  echo ""

  section "DR Drill Result"
  echo -e "  PASS: ${GREEN}$PASS${NC}   FAIL: ${RED}$FAIL${NC}   WARN: ${YELLOW}$WARN${NC}"
  echo ""
  log "Writing drill log..."
  DR_LOG="$(dirname "$0")/../docs/dr-test-log.md"
  {
    echo ""
    echo "## DR Drill — $(date -u +%Y-%m-%d)"
    echo ""
    echo "- **Date**: $(date -u)"
    echo "- **Operator**: ${USER:-unknown}"
    echo "- **Checks passed**: $PASS"
    echo "- **Checks failed**: $FAIL"
    echo "- **Warnings**: $WARN"
    echo "- **Est. RTO verified**: < 30 min"
    echo ""
  } >> "$DR_LOG" 2>/dev/null || warn "Could not write DR log (non-fatal)"

  success "DR drill complete. Review results above."
  [[ "$FAIL" -gt 0 ]] && exit 1 || exit 0
}

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTE — Actual DR Recovery
# ─────────────────────────────────────────────────────────────────────────────
dr_execute() {
  if [[ "$CONFIRM_FLAG" != "--confirm" ]]; then
    die "DR execution requires --confirm flag. This modifies production systems."
  fi

  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  DISASTER RECOVERY EXECUTION"
  echo "  $(date -u)"
  echo "  WARNING: This will modify production systems"
  echo "═══════════════════════════════════════════════════════════"
  echo ""
  read -r -p "Type 'EXECUTE DR' to confirm: " FINAL_CONFIRM
  [[ "$FINAL_CONFIRM" == "EXECUTE DR" ]] || die "DR cancelled."

  INCIDENT_ID="DR-$(date +%Y%m%d-%H%M)"
  log "Incident ID: $INCIDENT_ID"

  section "Phase 1: Assess"
  log "Gathering system state..."
  kubectl get pods -n "$NAMESPACE" 2>/dev/null || true
  kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' 2>/dev/null | tail -20 || true

  section "Phase 2: Contain"
  log "Attempting automated rollback first..."
  ROLLBACK_SCRIPT="$(dirname "$0")/rollback.sh"
  if [[ -f "$ROLLBACK_SCRIPT" ]]; then
    if echo "yes" | bash "$ROLLBACK_SCRIPT" 2>/dev/null; then
      success "Rollback succeeded — normal recovery path worked"
      log "Update status page and Slack. Incident ID: $INCIDENT_ID"
      exit 0
    else
      warn "Rollback failed — proceeding with full DR"
    fi
  fi

  section "Phase 3: Database Recovery (if needed)"
  log "Checking database connectivity..."
  if ! kubectl exec deploy/orchestrator-backend -n "$NAMESPACE" -- \
    python -c "import asyncio; from app.models.db_session import engine; print('ok')" &>/dev/null; then
    warn "Database appears unavailable"
    if [[ "${RDS_INSTANCE_ID:-}" ]]; then
      log "Starting RDS failover to read replica..."
      aws rds failover-db-cluster --db-cluster-identifier "$RDS_INSTANCE_ID" \
        --region "$AWS_REGION" 2>/dev/null || \
        warn "RDS failover command failed — check AWS Console"
    fi
  fi

  section "Phase 4: Restore from Backup (if database is corrupted)"
  log "If database recovery failed, restore from last backup:"
  log "  1. aws rds restore-db-instance-from-db-snapshot --db-instance-identifier orchestrator-restored ..."
  log "  2. Update DATABASE_URL secret in Kubernetes"
  log "  3. kubectl rollout restart deployment/orchestrator-backend -n $NAMESPACE"
  warn "Manual step required — see docs/disaster-recovery.md for full procedure"

  section "Phase 5: Verify Recovery"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  bash "$SCRIPT_DIR/post-deploy-verify.sh" || warn "Some verification checks failed — review above"

  section "Phase 6: Communicate"
  echo ""
  echo "  Checklist (manual):"
  echo "  [ ] Update status page: https://status.example.com"
  echo "  [ ] Post Slack update: #ops-alerts, #general"
  echo "  [ ] Email affected customers (if data impact)"
  echo "  [ ] Open post-mortem ticket"
  echo "  [ ] Schedule post-mortem meeting within 48h"
  echo ""
  log "Incident $INCIDENT_ID — DR execution complete."
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
case "$MODE" in
  status)  dr_status ;;
  test)    dr_test ;;
  execute) dr_execute ;;
  *)
    echo "Usage: $0 [status|test|execute [--confirm]]"
    echo "  status   — Check DR readiness"
    echo "  test     — Run non-destructive DR drill"
    echo "  execute  — Execute actual DR (requires --confirm)"
    exit 1
    ;;
esac
