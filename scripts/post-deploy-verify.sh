#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# post-deploy-verify.sh — Post-Deployment Verification Script
# Multi-Agent Orchestrator
#
# Runs a thorough functional verification of the production environment
# after a deployment completes. Covers all golden-path user flows.
#
# Usage:
#   ./scripts/post-deploy-verify.sh [BASE_URL]
#
# Examples:
#   ./scripts/post-deploy-verify.sh https://api.example.com
#   BASE_URL=https://api.example.com ./scripts/post-deploy-verify.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://localhost:8000}}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
TIMEOUT=10  # curl timeout per request

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

PASS=0; FAIL=0; WARN=0
RESULTS=()

check_pass() { echo -e "  ${GREEN}✓${NC} $*"; PASS=$((PASS+1)); RESULTS+=("PASS: $*"); }
check_fail() { echo -e "  ${RED}✗${NC} $*"; FAIL=$((FAIL+1)); RESULTS+=("FAIL: $*"); }
check_warn() { echo -e "  ${YELLOW}⚠${NC} $*"; WARN=$((WARN+1)); RESULTS+=("WARN: $*"); }
section()    { echo -e "\n${BOLD}${BLUE}── $* ──${NC}"; }

http_check() {
  local desc="$1" url="$2" expected="${3:-200}"
  local actual
  actual=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$url" 2>/dev/null || echo "000")
  if [[ "$actual" == "$expected" ]]; then
    check_pass "$desc → HTTP $actual"
  else
    check_fail "$desc → HTTP $actual (expected $expected)"
  fi
}

http_body_check() {
  local desc="$1" url="$2" pattern="$3"
  local body
  body=$(curl -s --max-time "$TIMEOUT" "$url" 2>/dev/null || echo "")
  if echo "$body" | grep -q "$pattern"; then
    check_pass "$desc contains '$pattern'"
  else
    check_fail "$desc missing '$pattern' — got: $(echo "$body" | head -c 100)"
  fi
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Post-Deployment Verification"
echo "  API: $BASE_URL"
echo "  Frontend: $FRONTEND_URL"
echo "  Time: $(date -u)"
echo "═══════════════════════════════════════════════════════════"

# ─────────────────────────────────────────────────────────────────────────────
# 1. HEALTH CHECKS
# ─────────────────────────────────────────────────────────────────────────────
section "1. Health Checks"

http_check "Backend /health" "${BASE_URL}/health" "200"
http_body_check "Health response body" "${BASE_URL}/health" '"status"'

# Check for healthy DB and Redis indicators in health response
HEALTH_BODY=$(curl -s --max-time "$TIMEOUT" "${BASE_URL}/health" 2>/dev/null || echo "{}")
if echo "$HEALTH_BODY" | grep -q '"database"'; then
  if echo "$HEALTH_BODY" | grep -q '"database".*"healthy"'; then
    check_pass "Database reported healthy"
  else
    check_warn "Database health status unclear — check /health response"
  fi
fi
if echo "$HEALTH_BODY" | grep -q '"redis"'; then
  if echo "$HEALTH_BODY" | grep -q '"redis".*"healthy"'; then
    check_pass "Redis reported healthy"
  else
    check_warn "Redis health status unclear — check /health response"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. API AVAILABILITY
# ─────────────────────────────────────────────────────────────────────────────
section "2. API Availability"

# Public endpoints (no auth needed)
http_check "API docs (Swagger)" "${BASE_URL}/docs" "200"
http_check "OpenAPI schema" "${BASE_URL}/openapi.json" "200"
http_check "Prometheus metrics" "${BASE_URL}/metrics" "200"

# Auth-protected endpoints should return 401 (not 500)
http_check "GET /api/v1/agents (expect 401)" "${BASE_URL}/api/v1/agents" "401"
http_check "GET /api/v1/workflows (expect 401)" "${BASE_URL}/api/v1/workflows" "401"
http_check "GET /api/v1/models (expect 200)" "${BASE_URL}/api/v1/models" "200"

# ─────────────────────────────────────────────────────────────────────────────
# 3. AUTHENTICATION FLOW
# ─────────────────────────────────────────────────────────────────────────────
section "3. Authentication Flow"

# Register a test user
TIMESTAMP=$(date +%s)
TEST_EMAIL="verify-${TIMESTAMP}@test.local"
TEST_PASS="Verify123!Pass"

REGISTER_RESP=$(curl -s --max-time "$TIMEOUT" -X POST "${BASE_URL}/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"${TEST_EMAIL}\", \"password\": \"${TEST_PASS}\", \"name\": \"Verify Test\"}" \
  2>/dev/null || echo '{"error": "connection failed"}')

if echo "$REGISTER_RESP" | grep -q '"access_token"'; then
  check_pass "User registration succeeds"
  ACCESS_TOKEN=$(echo "$REGISTER_RESP" | grep -oP '"access_token"\s*:\s*"\K[^"]+' || echo "")
elif echo "$REGISTER_RESP" | grep -q '"error"'; then
  ERR=$(echo "$REGISTER_RESP" | grep -oP '"message"\s*:\s*"\K[^"]+' | head -1 || echo "unknown")
  check_fail "User registration failed: $ERR"
  ACCESS_TOKEN=""
else
  check_warn "Registration response unclear — check manually"
  ACCESS_TOKEN=""
fi

# Login
if [[ -n "$ACCESS_TOKEN" ]]; then
  LOGIN_RESP=$(curl -s --max-time "$TIMEOUT" -X POST "${BASE_URL}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\": \"${TEST_EMAIL}\", \"password\": \"${TEST_PASS}\"}" \
    2>/dev/null || echo '{}')

  if echo "$LOGIN_RESP" | grep -q '"access_token"'; then
    check_pass "User login succeeds"
    ACCESS_TOKEN=$(echo "$LOGIN_RESP" | grep -oP '"access_token"\s*:\s*"\K[^"]+' || echo "$ACCESS_TOKEN")
  else
    check_fail "Login failed for registered user"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. CORE WORKFLOW — Agent + Workflow + Execution
# ─────────────────────────────────────────────────────────────────────────────
section "4. Core Workflow (Golden Path)"

if [[ -z "$ACCESS_TOKEN" ]]; then
  check_warn "Skipping golden path (no access token)"
else
  AUTH_HEADER="Authorization: Bearer $ACCESS_TOKEN"

  # Create agent
  AGENT_RESP=$(curl -s --max-time "$TIMEOUT" -X POST "${BASE_URL}/api/v1/agents" \
    -H "Content-Type: application/json" \
    -H "$AUTH_HEADER" \
    -d '{"name": "Verify Agent", "model": "claude-haiku-4-5-20251001", "role": "assistant", "system_prompt": "You are a verification agent."}' \
    2>/dev/null || echo '{}')

  AGENT_ID=$(echo "$AGENT_RESP" | grep -oP '"id"\s*:\s*"\K[^"]+' | head -1 || echo "")
  if [[ -n "$AGENT_ID" ]]; then
    check_pass "Agent creation succeeds (id: ${AGENT_ID:0:8}...)"
  else
    check_fail "Agent creation failed: $(echo "$AGENT_RESP" | head -c 100)"
  fi

  # List agents
  LIST_RESP=$(curl -s --max-time "$TIMEOUT" -H "$AUTH_HEADER" "${BASE_URL}/api/v1/agents" 2>/dev/null || echo '{}')
  if echo "$LIST_RESP" | grep -q '"items"'; then
    check_pass "Agent list endpoint works"
  else
    check_fail "Agent list failed"
  fi

  # Create workflow (if agent was created)
  if [[ -n "$AGENT_ID" ]]; then
    WORKFLOW_RESP=$(curl -s --max-time "$TIMEOUT" -X POST "${BASE_URL}/api/v1/workflows" \
      -H "Content-Type: application/json" \
      -H "$AUTH_HEADER" \
      -d "{\"name\": \"Verify Workflow\", \"nodes\": [{\"id\": \"start\", \"agent_id\": \"${AGENT_ID}\", \"type\": \"agent\"}], \"edges\": []}" \
      2>/dev/null || echo '{}')

    WF_ID=$(echo "$WORKFLOW_RESP" | grep -oP '"id"\s*:\s*"\K[^"]+' | head -1 || echo "")
    if [[ -n "$WF_ID" ]]; then
      check_pass "Workflow creation succeeds (id: ${WF_ID:0:8}...)"
    else
      check_fail "Workflow creation failed: $(echo "$WORKFLOW_RESP" | head -c 100)"
    fi

    # Execute workflow (expect 202 Accepted or 200)
    if [[ -n "$WF_ID" ]]; then
      EXEC_RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" \
        -X POST "${BASE_URL}/api/v1/workflows/${WF_ID}/execute" \
        -H "Content-Type: application/json" \
        -H "$AUTH_HEADER" \
        -d '{"input": {"message": "verify"}, "async": true}' \
        2>/dev/null || echo "000")

      if [[ "$EXEC_RESP" == "202" ]] || [[ "$EXEC_RESP" == "200" ]]; then
        check_pass "Workflow execution accepted (HTTP $EXEC_RESP)"
      else
        check_warn "Workflow execution returned HTTP $EXEC_RESP (LLM API keys may not be set)"
      fi
    fi
  fi

  # List executions
  EXEC_LIST=$(curl -s --max-time "$TIMEOUT" -H "$AUTH_HEADER" "${BASE_URL}/api/v1/executions" 2>/dev/null || echo '{}')
  if echo "$EXEC_LIST" | grep -q '"items"'; then
    check_pass "Executions list endpoint works"
  else
    check_fail "Executions list failed"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. METRICS & MONITORING
# ─────────────────────────────────────────────────────────────────────────────
section "5. Metrics & Monitoring"

METRICS_BODY=$(curl -s --max-time "$TIMEOUT" "${BASE_URL}/metrics" 2>/dev/null || echo "")
if echo "$METRICS_BODY" | grep -q "http_requests_total"; then
  check_pass "Prometheus metrics: http_requests_total present"
else
  check_warn "Prometheus metrics: http_requests_total not found"
fi
if echo "$METRICS_BODY" | grep -q "orchestrator_workflow_executions_total"; then
  check_pass "Prometheus metrics: workflow execution counter present"
else
  check_warn "Prometheus metrics: workflow execution counter not found (no executions yet)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. SECURITY HEADERS
# ─────────────────────────────────────────────────────────────────────────────
section "6. Security Headers"

HEADERS=$(curl -sI --max-time "$TIMEOUT" "${BASE_URL}/health" 2>/dev/null || echo "")

check_header() {
  local header="$1"
  if echo "$HEADERS" | grep -qi "$header"; then
    check_pass "Header present: $header"
  else
    check_fail "Header missing: $header"
  fi
}

check_header "x-content-type-options"
check_header "x-frame-options"
check_header "x-xss-protection"

# HSTS — production only
if echo "$BASE_URL" | grep -q "^https://"; then
  check_header "strict-transport-security"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. RATE LIMITING
# ─────────────────────────────────────────────────────────────────────────────
section "7. Rate Limiting"

RL_HEADER=$(curl -sI --max-time "$TIMEOUT" "${BASE_URL}/health" 2>/dev/null | grep -i "x-ratelimit" | head -1)
if [[ -n "$RL_HEADER" ]]; then
  check_pass "Rate limit headers present"
else
  check_warn "Rate limit headers not detected on /health (may be exempt)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 8. KUBERNETES STATE
# ─────────────────────────────────────────────────────────────────────────────
section "8. Kubernetes State"

if command -v kubectl &>/dev/null; then
  # Pod readiness
  READY_PODS=$(kubectl get pods -l app=orchestrator-backend -n orchestrator \
    --no-headers 2>/dev/null | grep -c "Running" || echo "0")
  DESIRED=$(kubectl get deployment orchestrator-backend -n orchestrator \
    -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "3")

  if [[ "$READY_PODS" -ge "$DESIRED" ]]; then
    check_pass "All $READY_PODS/$DESIRED backend pods are Running"
  elif [[ "$READY_PODS" -gt 0 ]]; then
    check_warn "Only $READY_PODS/$DESIRED backend pods Running — cluster may be stabilizing"
  else
    check_fail "No backend pods Running"
  fi

  # Recent restart check
  RESTARTS=$(kubectl get pods -l app=orchestrator-backend -n orchestrator \
    --no-headers 2>/dev/null | awk '{sum+=$4} END {print sum+0}' || echo "0")
  if [[ "$RESTARTS" -gt 5 ]]; then
    check_warn "High restart count: $RESTARTS — check logs for crash-looping"
  else
    check_pass "Pod restarts within normal range ($RESTARTS total)"
  fi
else
  check_warn "kubectl not found — skipping Kubernetes state checks"
fi

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Post-Deployment Verification Summary"
echo "  $(date -u)"
echo "─────────────────────────────────────────────────────────"
echo -e "  ${GREEN}PASS${NC}: $PASS"
echo -e "  ${YELLOW}WARN${NC}: $WARN"
echo -e "  ${RED}FAIL${NC}: $FAIL"
echo "═══════════════════════════════════════════════════════════"

if [[ "$FAIL" -gt 0 ]]; then
  echo ""
  echo -e "${RED}${BOLD}VERIFICATION FAILED ($FAIL failures)${NC}"
  echo "Failed checks:"
  for r in "${RESULTS[@]}"; do
    [[ "$r" == FAIL:* ]] && echo "  - ${r#FAIL: }"
  done
  echo ""
  echo "Consider rolling back: ./scripts/rollback.sh"
  exit 1
else
  echo ""
  echo -e "${GREEN}${BOLD}VERIFICATION PASSED${NC}"
  [[ "$WARN" -gt 0 ]] && echo "  ($WARN warnings — review above)"
  exit 0
fi
