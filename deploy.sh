#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — Production Deployment Script
# Multi-Agent Orchestrator
#
# Usage:
#   ./deploy.sh [OPTIONS]
#
# Options:
#   --env ENV           Target environment (staging|production) [default: production]
#   --image-tag TAG     Docker image tag to deploy [default: current git SHA]
#   --skip-checks       Skip pre-deployment checks (NOT recommended)
#   --skip-smoke        Skip post-deployment smoke tests
#   --dry-run           Print what would happen; don't actually deploy
#   --rollback-on-fail  Automatically roll back if smoke tests fail [default: true]
#   --canary PERCENT    Deploy as canary at given percentage (10|25|50|100)
#   --blue-green        Use blue/green deployment strategy
#   -h, --help          Show this help
#
# Required environment variables (or GitHub Secrets in CI):
#   AWS_ACCESS_KEY_ID         IAM access key
#   AWS_SECRET_ACCESS_KEY     IAM secret key
#   AWS_REGION                AWS region (e.g. us-east-1)
#   EKS_CLUSTER_NAME          EKS cluster name
#   DOCKER_REGISTRY_URL       ECR registry URL
#   SLACK_WEBHOOK_URL         Slack incoming webhook URL
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
IFS=$'\n\t'

# ── Defaults ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV="${DEPLOY_ENV:-production}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo "latest")}"
GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
SKIP_CHECKS=false
SKIP_SMOKE=false
DRY_RUN=false
ROLLBACK_ON_FAIL=true
CANARY_PERCENT=""
BLUE_GREEN=false
NAMESPACE="orchestrator"
DEPLOY_TIMEOUT=300   # seconds to wait for rollout
SMOKE_DURATION=600   # seconds for smoke-test monitoring
LOG_FILE="/tmp/deploy-$(date +%Y%m%d-%H%M%S).log"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
log()     { echo -e "${BLUE}[$(date -u +%H:%M:%S)]${NC} $*" | tee -a "$LOG_FILE"; }
success() { echo -e "${GREEN}[$(date -u +%H:%M:%S)] ✓${NC} $*" | tee -a "$LOG_FILE"; }
warn()    { echo -e "${YELLOW}[$(date -u +%H:%M:%S)] ⚠${NC} $*" | tee -a "$LOG_FILE"; }
error()   { echo -e "${RED}[$(date -u +%H:%M:%S)] ✗${NC} $*" | tee -a "$LOG_FILE" >&2; }
die()     { error "$*"; send_slack_notification "FAILED" "$*"; exit 1; }
dry()     { echo -e "${YELLOW}[DRY-RUN]${NC} $*"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
usage() {
  grep '^#' "$0" | sed 's/^# *//' | head -30
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)           ENV="$2"; shift 2 ;;
    --image-tag)     IMAGE_TAG="$2"; shift 2 ;;
    --skip-checks)   SKIP_CHECKS=true; shift ;;
    --skip-smoke)    SKIP_SMOKE=true; shift ;;
    --dry-run)       DRY_RUN=true; shift ;;
    --rollback-on-fail) ROLLBACK_ON_FAIL=true; shift ;;
    --no-rollback)   ROLLBACK_ON_FAIL=false; shift ;;
    --canary)        CANARY_PERCENT="$2"; shift 2 ;;
    --blue-green)    BLUE_GREEN=true; shift ;;
    -h|--help)       usage ;;
    *) die "Unknown option: $1" ;;
  esac
done

BACKEND_IMAGE="${DOCKER_REGISTRY_URL:-}/orchestrator-backend:${IMAGE_TAG}"
FRONTEND_IMAGE="${DOCKER_REGISTRY_URL:-}/orchestrator-frontend:${IMAGE_TAG}"

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Pre-deployment checks
# ─────────────────────────────────────────────────────────────────────────────
run_pre_checks() {
  log "${BOLD}Running pre-deployment checks...${NC}"

  local failed=0

  # ── 1. Required tools ──────────────────────────────────────────────────────
  log "Checking required tools..."
  for tool in kubectl docker aws curl bc git; do
    if ! command -v "$tool" &>/dev/null; then
      error "Required tool not found: $tool"
      failed=$((failed + 1))
    fi
  done

  # ── 2. AWS credentials ────────────────────────────────────────────────────
  log "Checking AWS credentials..."
  if ! aws sts get-caller-identity &>/dev/null; then
    error "AWS credentials invalid or missing"
    failed=$((failed + 1))
  else
    AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    success "AWS authenticated (account: $AWS_ACCOUNT)"
  fi

  # ── 3. Kubernetes connectivity ────────────────────────────────────────────
  log "Checking Kubernetes connectivity..."
  if ! kubectl cluster-info &>/dev/null; then
    error "Cannot connect to Kubernetes cluster"
    failed=$((failed + 1))
  else
    K8S_VERSION=$(kubectl version --short 2>/dev/null | grep "Server Version" | awk '{print $3}')
    success "Kubernetes connected (server: $K8S_VERSION)"
  fi

  # ── 4. Namespace exists ───────────────────────────────────────────────────
  log "Checking namespace: $NAMESPACE"
  if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    warn "Namespace '$NAMESPACE' not found — creating..."
    if [[ "$DRY_RUN" == "false" ]]; then
      kubectl create namespace "$NAMESPACE"
    fi
  fi

  # ── 5. Docker image exists in registry ───────────────────────────────────
  log "Checking images exist in registry..."
  if ! docker manifest inspect "$BACKEND_IMAGE" &>/dev/null; then
    error "Backend image not found: $BACKEND_IMAGE"
    failed=$((failed + 1))
  else
    success "Backend image verified: $BACKEND_IMAGE"
  fi
  if ! docker manifest inspect "$FRONTEND_IMAGE" &>/dev/null; then
    error "Frontend image not found: $FRONTEND_IMAGE"
    failed=$((failed + 1))
  else
    success "Frontend image verified: $FRONTEND_IMAGE"
  fi

  # ── 6. Secrets exist in cluster ───────────────────────────────────────────
  log "Checking required secrets in cluster..."
  for secret in orchestrator-secrets; do
    if ! kubectl get secret "$secret" -n "$NAMESPACE" &>/dev/null; then
      error "Secret not found: $secret (run: kubectl create secret generic $secret ...)"
      failed=$((failed + 1))
    else
      success "Secret found: $secret"
    fi
  done

  # ── 7. ConfigMap exists ───────────────────────────────────────────────────
  log "Checking ConfigMap..."
  if ! kubectl get configmap orchestrator-config -n "$NAMESPACE" &>/dev/null; then
    warn "ConfigMap 'orchestrator-config' not found — will be applied from k8s/configmap.yaml"
  fi

  # ── 8. Disk space check (local) ───────────────────────────────────────────
  log "Checking local disk space..."
  DISK_AVAIL=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
  if [[ "$DISK_AVAIL" -gt 80 ]]; then
    warn "Local disk usage is ${DISK_AVAIL}% (>80%)"
  else
    success "Local disk usage: ${DISK_AVAIL}%"
  fi

  # ── Result ────────────────────────────────────────────────────────────────
  if [[ "$failed" -gt 0 ]]; then
    die "Pre-deployment checks failed ($failed error(s)). Fix issues before deploying."
  fi
  success "All pre-deployment checks passed."
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — Deploy
# ─────────────────────────────────────────────────────────────────────────────
do_deploy() {
  log "${BOLD}Starting deployment: $IMAGE_TAG → $ENV${NC}"
  log "Backend:  $BACKEND_IMAGE"
  log "Frontend: $FRONTEND_IMAGE"
  log "Log file: $LOG_FILE"

  # Record previous image for rollback reference
  PREVIOUS_BACKEND=$(kubectl get deployment orchestrator-backend \
    -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "none")
  log "Previous backend image: $PREVIOUS_BACKEND"

  if [[ "$BLUE_GREEN" == "true" ]]; then
    deploy_blue_green
  elif [[ -n "$CANARY_PERCENT" ]]; then
    deploy_canary "$CANARY_PERCENT"
  else
    deploy_rolling
  fi
}

deploy_rolling() {
  log "Strategy: Rolling update"

  if [[ "$DRY_RUN" == "true" ]]; then
    dry "kubectl apply -f k8s/configmap.yaml"
    dry "kubectl set image deployment/orchestrator-backend backend=$BACKEND_IMAGE -n $NAMESPACE"
    dry "kubectl set image deployment/orchestrator-frontend frontend=$FRONTEND_IMAGE -n $NAMESPACE"
    dry "kubectl rollout status deployment/orchestrator-backend -n $NAMESPACE --timeout=${DEPLOY_TIMEOUT}s"
    return
  fi

  log "Applying ConfigMap..."
  kubectl apply -f "$SCRIPT_DIR/k8s/configmap.yaml" -n "$NAMESPACE"

  log "Patching deployment images..."
  # Use sed to update the image tags in deployment.yaml then apply
  sed \
    -e "s|orchestrator-backend:.*|${BACKEND_IMAGE}|g" \
    -e "s|orchestrator-frontend:.*|${FRONTEND_IMAGE}|g" \
    "$SCRIPT_DIR/k8s/deployment.yaml" | kubectl apply -f -

  kubectl apply -f "$SCRIPT_DIR/k8s/service.yaml"

  log "Waiting for backend rollout (timeout: ${DEPLOY_TIMEOUT}s)..."
  kubectl rollout status deployment/orchestrator-backend \
    -n "$NAMESPACE" \
    --timeout="${DEPLOY_TIMEOUT}s"

  # Wait for all pods to be Ready
  kubectl wait pod \
    -l app=orchestrator-backend \
    -n "$NAMESPACE" \
    --for=condition=Ready \
    --timeout=120s

  success "Rolling deployment complete."
  kubectl get pods -n "$NAMESPACE"
}

deploy_canary() {
  local percent="$1"
  log "Strategy: Canary at ${percent}%"

  if [[ "$DRY_RUN" == "true" ]]; then
    dry "kubectl scale deployment orchestrator-backend-canary --replicas=<n> -n $NAMESPACE"
    return
  fi

  # Determine replica counts
  TOTAL_REPLICAS=$(kubectl get deployment orchestrator-backend -n "$NAMESPACE" \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "3")
  CANARY_REPLICAS=$(( (TOTAL_REPLICAS * percent + 99) / 100 ))
  CANARY_REPLICAS=$(( CANARY_REPLICAS < 1 ? 1 : CANARY_REPLICAS ))

  log "Deploying $CANARY_REPLICAS canary replica(s) (${percent}% of ${TOTAL_REPLICAS})..."

  # Create canary deployment from the existing one
  kubectl get deployment orchestrator-backend -n "$NAMESPACE" -o json \
    | jq --arg image "$BACKEND_IMAGE" --arg name "orchestrator-backend-canary" \
        --argjson replicas "$CANARY_REPLICAS" \
      '.metadata.name = $name |
       .spec.replicas = $replicas |
       .spec.selector.matchLabels.track = "canary" |
       .spec.template.metadata.labels.track = "canary" |
       .spec.template.spec.containers[0].image = $image |
       del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .status)' \
    | kubectl apply -f -

  kubectl rollout status deployment/orchestrator-backend-canary \
    -n "$NAMESPACE" --timeout="${DEPLOY_TIMEOUT}s"

  log "Canary is live at ${percent}%. Monitor for 5 min before proceeding."
  warn "Run with --canary 100 when ready to complete the rollout."
}

deploy_blue_green() {
  log "Strategy: Blue/Green"

  CURRENT_SLOT=$(kubectl get service orchestrator-backend -n "$NAMESPACE" \
    -o jsonpath='{.spec.selector.slot}' 2>/dev/null || echo "blue")
  NEW_SLOT=$([ "$CURRENT_SLOT" = "blue" ] && echo "green" || echo "blue")
  log "Current slot: $CURRENT_SLOT → Deploying to: $NEW_SLOT"

  if [[ "$DRY_RUN" == "true" ]]; then
    dry "kubectl apply green deployment with $BACKEND_IMAGE"
    dry "kubectl patch service to switch to $NEW_SLOT"
    return
  fi

  # Deploy to inactive slot
  kubectl get deployment "orchestrator-backend-${CURRENT_SLOT}" -n "$NAMESPACE" -o json \
    | jq --arg image "$BACKEND_IMAGE" --arg name "orchestrator-backend-${NEW_SLOT}" \
        --arg slot "$NEW_SLOT" \
      '.metadata.name = $name |
       .spec.selector.matchLabels.slot = $slot |
       .spec.template.metadata.labels.slot = $slot |
       .spec.template.spec.containers[0].image = $image |
       del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .status)' \
    | kubectl apply -f -

  kubectl rollout status "deployment/orchestrator-backend-${NEW_SLOT}" \
    -n "$NAMESPACE" --timeout="${DEPLOY_TIMEOUT}s"

  log "Green environment is healthy. Switching load balancer to $NEW_SLOT..."
  kubectl patch service orchestrator-backend -n "$NAMESPACE" \
    --type=json \
    -p="[{\"op\": \"replace\", \"path\": \"/spec/selector/slot\", \"value\": \"${NEW_SLOT}\"}]"

  success "Traffic switched to $NEW_SLOT."
  log "Previous slot ($CURRENT_SLOT) kept for 30 min as instant rollback."
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Smoke tests
# ─────────────────────────────────────────────────────────────────────────────
run_smoke_tests() {
  log "${BOLD}Running post-deployment smoke tests (${SMOKE_DURATION}s)...${NC}"

  # Get the service endpoint
  local hostname
  hostname=$(kubectl get svc orchestrator-backend -n "$NAMESPACE" \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null \
    || kubectl get svc orchestrator-backend -n "$NAMESPACE" \
       -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)

  if [[ -z "$hostname" ]]; then
    hostname="localhost:8000"
    warn "Could not get LoadBalancer address; using localhost fallback"
  fi

  local base_url="http://${hostname}"
  log "Smoke-testing: $base_url"

  # ── Initial /health check ─────────────────────────────────────────────────
  log "Initial /health check..."
  local attempts=0
  while [[ $attempts -lt 10 ]]; do
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${base_url}/health" || echo "000")
    if [[ "$http_code" == "200" ]]; then
      success "/health returned 200"
      break
    fi
    attempts=$((attempts + 1))
    warn "Attempt ${attempts}/10: got ${http_code}, retrying in 10s..."
    sleep 10
    if [[ $attempts -ge 10 ]]; then
      die "Initial /health check failed after ${attempts} attempts"
    fi
  done

  # ── API sanity checks ─────────────────────────────────────────────────────
  log "Checking API endpoints..."

  local api_status
  api_status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${base_url}/api/v1/models" || echo "000")
  if [[ "$api_status" == "200" ]] || [[ "$api_status" == "401" ]]; then
    success "/api/v1/models responded ($api_status)"
  else
    warn "/api/v1/models returned unexpected: $api_status"
  fi

  # ── Rolling error-rate monitor ────────────────────────────────────────────
  log "Monitoring for ${SMOKE_DURATION}s (error_rate < 1%, no 3 consecutive failures)..."
  local end_time=$((SECONDS + SMOKE_DURATION))
  local total=0 errors=0 consecutive=0

  while [[ $SECONDS -lt $end_time ]]; do
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${base_url}/health" || echo "000")
    total=$((total + 1))

    if [[ "$http_code" == "200" ]]; then
      consecutive=0
      log "✓ [$(date -u +%H:%M:%S)] /health OK (checks=${total} errors=${errors})"
    else
      errors=$((errors + 1))
      consecutive=$((consecutive + 1))
      warn "✗ [$(date -u +%H:%M:%S)] /health ${http_code} (errors=${errors}/${total})"

      if [[ $consecutive -ge 3 ]]; then
        error "3 consecutive health-check failures — triggering rollback"
        return 1
      fi
    fi

    # Check rolling error rate every 20 checks
    if [[ $((total % 20)) -eq 0 ]] && [[ $total -gt 0 ]]; then
      local rate
      rate=$(echo "scale=2; $errors * 100 / $total" | bc)
      log "── Rolling error rate: ${rate}% (${errors}/${total}) ──"
      if [[ $(echo "$rate > 1" | bc) -eq 1 ]]; then
        error "Error rate ${rate}% exceeds 1% threshold"
        return 1
      fi
    fi

    sleep 30
  done

  local final_rate
  final_rate=$(echo "scale=2; $errors * 100 / $total" | bc)
  success "Smoke tests passed: ${total} checks, ${errors} errors (${final_rate}%)"
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — Rollback
# ─────────────────────────────────────────────────────────────────────────────
do_rollback() {
  log "${BOLD}${RED}Initiating rollback...${NC}"

  if [[ "$DRY_RUN" == "true" ]]; then
    dry "kubectl rollout undo deployment/orchestrator-backend -n $NAMESPACE"
    return
  fi

  log "Collecting pre-rollback diagnostics..."
  kubectl get pods -n "$NAMESPACE" | tee -a "$LOG_FILE" || true
  kubectl logs -l app=orchestrator-backend -n "$NAMESPACE" --tail=50 2>/dev/null | tee -a "$LOG_FILE" || true

  log "Rolling back orchestrator-backend..."
  kubectl rollout undo deployment/orchestrator-backend -n "$NAMESPACE"
  kubectl rollout status deployment/orchestrator-backend -n "$NAMESPACE" --timeout=180s

  log "Verifying rollback health..."
  local hostname
  hostname=$(kubectl get svc orchestrator-backend -n "$NAMESPACE" \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "localhost:8000")

  sleep 15
  local check
  for i in $(seq 1 5); do
    check=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://${hostname}/health" || echo "000")
    if [[ "$check" == "200" ]]; then
      success "Rollback verified — /health 200"
      send_slack_notification "ROLLBACK_SUCCESS" "Rolled back to previous version successfully"
      return 0
    fi
    warn "Rollback health check ${i}/5: got ${check}"
    sleep 10
  done

  die "Rollback health check failed — MANUAL INTERVENTION REQUIRED"
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Slack notification
# ─────────────────────────────────────────────────────────────────────────────
send_slack_notification() {
  local status="$1"
  local message="${2:-}"

  if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then
    warn "SLACK_WEBHOOK_URL not set — skipping Slack notification"
    return
  fi

  local color icon text
  case "$status" in
    START)            color="warning"; icon=":rocket:"  ;;
    SUCCESS)          color="good";    icon=":white_check_mark:" ;;
    FAILED)           color="danger";  icon=":x:" ;;
    ROLLBACK_SUCCESS) color="warning"; icon=":rewind:" ;;
    *)                color="#cccccc"; icon=":information_source:" ;;
  esac

  text="${icon} *Deploy ${status}* — \`orchestrator\` \`${IMAGE_TAG}\` (${ENV})"
  [[ -n "$message" ]] && text+="\n${message}"

  curl -s -o /dev/null -X POST "$SLACK_WEBHOOK_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"text\": \"${text}\", \"attachments\": [{\"color\": \"${color}\", \"fields\": [{\"title\": \"Environment\", \"value\": \"${ENV}\", \"short\": true}, {\"title\": \"Image tag\", \"value\": \"\`${IMAGE_TAG}\`\", \"short\": true}, {\"title\": \"Log\", \"value\": \"${LOG_FILE}\"}]}]}" \
    || warn "Slack notification failed (non-fatal)"
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — Post-deployment documentation
# ─────────────────────────────────────────────────────────────────────────────
write_deploy_log() {
  local status="$1"
  local deploy_log="$SCRIPT_DIR/docs/deploy-history.log"

  printf '%s | %-10s | %-8s | %-8s | %s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$status" \
    "$ENV" \
    "$IMAGE_TAG" \
    "${GITHUB_ACTOR:-$(git config user.email 2>/dev/null || echo "unknown")}" \
    >> "$deploy_log" 2>/dev/null || true
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
main() {
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "  Multi-Agent Orchestrator — Production Deployment"
  echo "  Environment : $ENV"
  echo "  Image tag   : $IMAGE_TAG"
  echo "  Git SHA     : $GIT_SHA"
  echo "  Strategy    : $([ "$BLUE_GREEN" = "true" ] && echo "blue/green" || ([ -n "$CANARY_PERCENT" ] && echo "canary ${CANARY_PERCENT}%" || echo "rolling"))"
  echo "  Dry run     : $DRY_RUN"
  echo "════════════════════════════════════════════════════════════"
  echo ""

  send_slack_notification "START"

  # ── Step 1: AWS + K8s auth ────────────────────────────────────────────────
  if [[ "${AWS_REGION:-}" && "${EKS_CLUSTER_NAME:-}" ]]; then
    log "Updating kubeconfig for EKS cluster: $EKS_CLUSTER_NAME"
    if [[ "$DRY_RUN" == "false" ]]; then
      aws eks update-kubeconfig --name "$EKS_CLUSTER_NAME" --region "${AWS_REGION}"
    fi
  fi

  # ── Step 2: Pre-deployment checks ────────────────────────────────────────
  if [[ "$SKIP_CHECKS" == "false" ]]; then
    run_pre_checks
  else
    warn "Pre-deployment checks skipped (--skip-checks)"
  fi

  # ── Step 3: Deploy ────────────────────────────────────────────────────────
  do_deploy

  # ── Step 4: Smoke tests ───────────────────────────────────────────────────
  if [[ "$SKIP_SMOKE" == "false" ]]; then
    if ! run_smoke_tests; then
      error "Smoke tests failed!"
      write_deploy_log "SMOKE_FAILED"
      if [[ "$ROLLBACK_ON_FAIL" == "true" ]]; then
        do_rollback
      fi
      send_slack_notification "FAILED" "Smoke tests failed — see $LOG_FILE"
      exit 1
    fi
  else
    warn "Smoke tests skipped (--skip-smoke)"
  fi

  # ── Step 5: Success ───────────────────────────────────────────────────────
  write_deploy_log "SUCCESS"
  send_slack_notification "SUCCESS"

  echo ""
  echo "════════════════════════════════════════════════════════════"
  success "Deployment complete!"
  echo "  Environment : $ENV"
  echo "  Image tag   : $IMAGE_TAG"
  echo "  Log file    : $LOG_FILE"
  echo "════════════════════════════════════════════════════════════"
  echo ""
}

main "$@"
