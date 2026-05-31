#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# rollback.sh — Manual Rollback Script
# Multi-Agent Orchestrator
#
# Usage:
#   ./scripts/rollback.sh [OPTIONS]
#
# Options:
#   --revision N       Roll back to specific deployment revision
#   --image-tag TAG    Roll back to a specific image tag
#   --dry-run          Show what would happen without making changes
#   --no-verify        Skip health verification after rollback
#   -h, --help         Show this help
#
# Examples:
#   ./scripts/rollback.sh                     # Roll back one revision
#   ./scripts/rollback.sh --revision 5        # Roll back to revision 5
#   ./scripts/rollback.sh --image-tag abc1234 # Roll back to specific image
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

NAMESPACE="orchestrator"
REVISION=""
IMAGE_TAG=""
DRY_RUN=false
NO_VERIFY=false
DEPLOYMENT="orchestrator-backend"
REGISTRY="${DOCKER_REGISTRY_URL:-}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

log()     { echo -e "${BLUE}[$(date -u +%H:%M:%S)]${NC} $*"; }
success() { echo -e "${GREEN}[$(date -u +%H:%M:%S)] ✓${NC} $*"; }
warn()    { echo -e "${YELLOW}[$(date -u +%H:%M:%S)] ⚠${NC} $*"; }
error()   { echo -e "${RED}[$(date -u +%H:%M:%S)] ✗${NC} $*" >&2; }
die()     { error "$*"; exit 1; }
dry()     { echo -e "${YELLOW}[DRY-RUN]${NC} $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --revision)   REVISION="$2"; shift 2 ;;
    --image-tag)  IMAGE_TAG="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=true; shift ;;
    --no-verify)  NO_VERIFY=true; shift ;;
    -h|--help)    head -30 "$0" | sed 's/^# *//'; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Multi-Agent Orchestrator — ROLLBACK"
echo "  Namespace:  $NAMESPACE"
echo "  Deployment: $DEPLOYMENT"
echo "  Dry run:    $DRY_RUN"
[[ -n "$REVISION"  ]] && echo "  To revision: $REVISION"
[[ -n "$IMAGE_TAG" ]] && echo "  To image:   $IMAGE_TAG"
echo "════════════════════════════════════════════════════════════"
echo ""

warn "You are about to roll back the production deployment."
if [[ "$DRY_RUN" == "false" ]]; then
  read -r -p "Type 'yes' to confirm rollback: " CONFIRM
  [[ "$CONFIRM" == "yes" ]] || die "Rollback cancelled."
fi

# ── Step 1: Collect diagnostics ───────────────────────────────────────────────
log "Collecting pre-rollback diagnostics..."
CURRENT_IMAGE=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" \
  -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
log "Current image: $CURRENT_IMAGE"

kubectl get pods -n "$NAMESPACE" -l "app=$DEPLOYMENT" --no-headers 2>/dev/null | head -10 || true

log "Recent events:"
kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' 2>/dev/null | tail -15 || true

log "Last 50 log lines:"
kubectl logs -l "app=$DEPLOYMENT" -n "$NAMESPACE" --tail=50 2>/dev/null || true

# ── Step 2: Show rollout history ──────────────────────────────────────────────
log "Rollout history:"
kubectl rollout history "deployment/$DEPLOYMENT" -n "$NAMESPACE" 2>/dev/null || true

# ── Step 3: Execute rollback ──────────────────────────────────────────────────
log "Executing rollback..."

if [[ "$DRY_RUN" == "true" ]]; then
  if [[ -n "$IMAGE_TAG" ]]; then
    dry "kubectl set image deployment/$DEPLOYMENT backend=${REGISTRY}/orchestrator-backend:${IMAGE_TAG} -n $NAMESPACE"
  elif [[ -n "$REVISION" ]]; then
    dry "kubectl rollout undo deployment/$DEPLOYMENT --to-revision=$REVISION -n $NAMESPACE"
  else
    dry "kubectl rollout undo deployment/$DEPLOYMENT -n $NAMESPACE"
  fi
  dry "kubectl rollout status deployment/$DEPLOYMENT -n $NAMESPACE --timeout=180s"
else
  if [[ -n "$IMAGE_TAG" ]]; then
    log "Rolling back to image tag: $IMAGE_TAG"
    kubectl set image "deployment/$DEPLOYMENT" \
      "backend=${REGISTRY}/orchestrator-backend:${IMAGE_TAG}" \
      -n "$NAMESPACE"
  elif [[ -n "$REVISION" ]]; then
    log "Rolling back to revision: $REVISION"
    kubectl rollout undo "deployment/$DEPLOYMENT" --to-revision="$REVISION" -n "$NAMESPACE"
  else
    log "Rolling back to previous revision..."
    kubectl rollout undo "deployment/$DEPLOYMENT" -n "$NAMESPACE"
  fi

  log "Waiting for rollback to complete (timeout: 180s)..."
  kubectl rollout status "deployment/$DEPLOYMENT" -n "$NAMESPACE" --timeout=180s
fi

NEW_IMAGE=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" \
  -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
success "Rollback complete. Running image: $NEW_IMAGE"

# ── Step 4: Verify rollback ───────────────────────────────────────────────────
if [[ "$NO_VERIFY" == "true" ]] || [[ "$DRY_RUN" == "true" ]]; then
  warn "Skipping health verification"
else
  log "Waiting 15s for pods to stabilize..."
  sleep 15

  HOSTNAME=$(kubectl get svc "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null \
    || kubectl get svc "$DEPLOYMENT" -n "$NAMESPACE" \
       -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null \
    || echo "localhost:8000")

  URL="http://${HOSTNAME}"
  log "Verifying health at $URL/health..."

  VERIFIED=false
  for i in $(seq 1 6); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${URL}/health" 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
      success "Health check passed after rollback (attempt $i)"
      VERIFIED=true
      break
    fi
    warn "Health check attempt $i/6: got $HTTP_CODE"
    sleep 10
  done

  if [[ "$VERIFIED" == "false" ]]; then
    error "Rollback health check FAILED after 60s"
    error ""
    error "MANUAL INTERVENTION REQUIRED:"
    error "  1. Check pod logs: kubectl logs -l app=$DEPLOYMENT -n $NAMESPACE --tail=100"
    error "  2. Check events: kubectl describe deployment/$DEPLOYMENT -n $NAMESPACE"
    error "  3. If DB migration is the issue: kubectl exec -it deploy/$DEPLOYMENT -n $NAMESPACE -- alembic downgrade -1"
    error "  4. Contact infrastructure team: check #ops-alerts Slack channel"
    exit 1
  fi

  log "Running post-rollback verification..."
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$SCRIPT_DIR/post-deploy-verify.sh" ]]; then
    BASE_URL="$URL" bash "$SCRIPT_DIR/post-deploy-verify.sh" || warn "Post-verify had failures — review above"
  fi
fi

# ── Step 5: Summary ───────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
success "ROLLBACK COMPLETE"
echo "  Previous image: $CURRENT_IMAGE"
echo "  Restored image: $NEW_IMAGE"
echo ""
echo "  Next steps:"
echo "  1. Investigate root cause of failed deployment"
echo "  2. Fix the issue in a new branch"
echo "  3. Open a PR with tests"
echo "  4. Merge only after CI is green"
echo "════════════════════════════════════════════════════════════"
