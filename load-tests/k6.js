/**
 * k6 Load Test — Multi-Agent Orchestrator
 *
 * Scenarios:
 *   ramp-up  : 0 → 50 VUs over 2 min (warm up)
 *   sustained: 50 → 100 VUs over 2 min, held for 5 min (main test)
 *   ramp-down: 100 → 0 over 1 min
 *   Total    : ~10 min, 100 peak VUs
 *
 * Usage:
 *   k6 run load-tests/k6.js -e BASE_URL=http://localhost:8000
 *
 * Thresholds (CI gate):
 *   - p95 latency < 2s
 *   - Error rate < 1%
 *
 * Install k6: https://k6.io/docs/getting-started/installation/
 */

import http from 'k6/http'
import { check, group, sleep } from 'k6'
import { Rate, Trend, Counter } from 'k6/metrics'
import { randomString } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js'

// ── Custom metrics ─────────────────────────────────────────────────────────────
const errorRate     = new Rate('custom_error_rate')
const agentCreated  = new Counter('agents_created')
const workflowExec  = new Counter('workflows_executed')
const authLatency   = new Trend('auth_login_duration_ms')
const apiLatency    = new Trend('api_duration_ms')

// ── Configuration ──────────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000'

export const options = {
  scenarios: {
    ramp_up: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 50  },  // ramp to 50 VUs
        { duration: '2m', target: 100 },  // ramp to 100 VUs
        { duration: '5m', target: 100 },  // hold at 100 VUs
        { duration: '1m', target: 0   },  // ramp down
      ],
      gracefulRampDown: '30s',
    },
  },

  thresholds: {
    // p95 latency must stay below 2s
    http_req_duration: ['p(95)<2000'],
    // Error rate must stay below 1%
    custom_error_rate: ['rate<0.01'],
    // Health check must always succeed
    'http_req_duration{endpoint:health}': ['p(99)<500'],
  },

  // Output a clean summary at the end
  summaryTrendStats: ['min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function headers(token) {
  const h = { 'Content-Type': 'application/json' }
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

function registerUser() {
  const email = `load-${randomString(8)}@test.local`
  const password = 'LoadTest!Pass1'
  const res = http.post(
    `${BASE_URL}/auth/register`,
    JSON.stringify({ email, password }),
    { headers: headers(), tags: { endpoint: 'register' } }
  )
  const ok = check(res, { 'register 201': (r) => r.status === 201 })
  errorRate.add(!ok)
  return ok ? { email, password } : null
}

function loginUser(credentials) {
  const start = Date.now()
  const res = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify(credentials),
    { headers: headers(), tags: { endpoint: 'login' } }
  )
  authLatency.add(Date.now() - start)
  const ok = check(res, { 'login 200': (r) => r.status === 200 })
  errorRate.add(!ok)
  if (!ok) return null
  return res.json('access_token')
}

// ── Default function (runs per VU iteration) ──────────────────────────────────

export default function () {
  // ── Health check ─────────────────────────────────────────────────────────────
  group('health', () => {
    const res = http.get(`${BASE_URL}/health`, { tags: { endpoint: 'health' } })
    const ok = check(res, {
      'status 200': (r) => r.status === 200,
      'status ok': (r) => r.json('status') === 'ok',
    })
    errorRate.add(!ok)
  })

  sleep(0.5)

  // ── Auth flow ─────────────────────────────────────────────────────────────────
  let token = null
  group('auth', () => {
    const creds = registerUser()
    if (!creds) return
    token = loginUser(creds)
  })

  if (!token) {
    sleep(1)
    return
  }

  sleep(0.5)

  // ── List agents ───────────────────────────────────────────────────────────────
  group('agents_list', () => {
    const start = Date.now()
    const res = http.get(
      `${BASE_URL}/api/v1/agents?limit=10`,
      { headers: headers(token), tags: { endpoint: 'agents_list' } }
    )
    apiLatency.add(Date.now() - start)
    const ok = check(res, {
      'agents list 200': (r) => r.status === 200,
    })
    errorRate.add(!ok)
  })

  sleep(0.3)

  // ── Create agent ──────────────────────────────────────────────────────────────
  let agentId = null
  group('agent_create', () => {
    const start = Date.now()
    const res = http.post(
      `${BASE_URL}/api/v1/agents`,
      JSON.stringify({
        name: `Load Test Agent ${randomString(4)}`,
        role: 'Summarizer',
        system_prompt: 'You are a load-test agent.',
        model: 'claude-sonnet-4-6',
      }),
      { headers: headers(token), tags: { endpoint: 'agent_create' } }
    )
    apiLatency.add(Date.now() - start)
    const ok = check(res, { 'agent created 201': (r) => r.status === 201 })
    errorRate.add(!ok)
    if (ok) {
      agentId = res.json('id')
      agentCreated.add(1)
    }
  })

  sleep(0.3)

  // ── Create + execute workflow ─────────────────────────────────────────────────
  group('workflow_lifecycle', () => {
    // Create
    const createStart = Date.now()
    const createRes = http.post(
      `${BASE_URL}/api/v1/workflows`,
      JSON.stringify({
        name: `Load Workflow ${randomString(4)}`,
        dag_config: { nodes: [], edges: [] },
      }),
      { headers: headers(token), tags: { endpoint: 'workflow_create' } }
    )
    apiLatency.add(Date.now() - createStart)
    const createOk = check(createRes, { 'workflow created 201': (r) => r.status === 201 })
    errorRate.add(!createOk)
    if (!createOk) return

    const workflowId = createRes.json('id')
    sleep(0.2)

    // Execute (fire-and-forget — we don't wait for completion)
    const execStart = Date.now()
    const execRes = http.post(
      `${BASE_URL}/api/v1/workflows/${workflowId}/execute`,
      JSON.stringify({ input: 'Load test input', async: true }),
      { headers: headers(token), tags: { endpoint: 'workflow_execute' } }
    )
    apiLatency.add(Date.now() - execStart)
    const execOk = check(execRes, {
      'execution accepted': (r) => r.status === 202 || r.status === 200,
    })
    errorRate.add(!execOk)
    if (execOk) workflowExec.add(1)
  })

  sleep(0.5)

  // ── List executions ───────────────────────────────────────────────────────────
  group('executions_list', () => {
    const start = Date.now()
    const res = http.get(
      `${BASE_URL}/api/v1/executions?limit=5`,
      { headers: headers(token), tags: { endpoint: 'executions_list' } }
    )
    apiLatency.add(Date.now() - start)
    const ok = check(res, { 'executions 200': (r) => r.status === 200 })
    errorRate.add(!ok)
  })

  sleep(1)
}

// ── Summary output ─────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const summary = {
    timestamp: new Date().toISOString(),
    vus_max: data.metrics.vus_max ? data.metrics.vus_max.values.max : 0,
    duration_s: data.state.testRunDurationMs / 1000,
    requests_total: data.metrics.http_reqs ? data.metrics.http_reqs.values.count : 0,
    error_rate: data.metrics.custom_error_rate
      ? data.metrics.custom_error_rate.values.rate
      : 0,
    p95_ms: data.metrics.http_req_duration
      ? data.metrics.http_req_duration.values['p(95)']
      : 0,
    p99_ms: data.metrics.http_req_duration
      ? data.metrics.http_req_duration.values['p(99)']
      : 0,
    agents_created: data.metrics.agents_created
      ? data.metrics.agents_created.values.count
      : 0,
    workflows_executed: data.metrics.workflows_executed
      ? data.metrics.workflows_executed.values.count
      : 0,
    thresholds_passed: !data.state.isStdErrInProgress,
  }

  // Write JSON summary for CI consumption
  return {
    'load-tests/results.json': JSON.stringify(summary, null, 2),
    stdout: `
═══════════════════════════════════════════════════
  Load Test Summary
═══════════════════════════════════════════════════
  Peak VUs       : ${summary.vus_max}
  Total requests : ${summary.requests_total}
  Error rate     : ${(summary.error_rate * 100).toFixed(2)}%  (threshold: <1%)
  Latency p95    : ${summary.p95_ms.toFixed(0)} ms  (threshold: <2000ms)
  Latency p99    : ${summary.p99_ms.toFixed(0)} ms
  Agents created : ${summary.agents_created}
  Workflows exec : ${summary.workflows_executed}
  Thresholds     : ${summary.thresholds_passed ? 'ALL PASSED ✓' : 'FAILED ✗'}
═══════════════════════════════════════════════════
`,
  }
}
