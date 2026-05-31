import type {
  DashboardStatsV2,
  ExecutionRecord,
  TimelineDataPoint,
  TokenDataPoint,
  WorkflowStat,
  RecentAgent,
} from '../types'

// ─── Dashboard stats ──────────────────────────────────────────────────────────

export const MOCK_DASHBOARD_STATS: DashboardStatsV2 = {
  totalExecutions: 42,
  successRate: 94,
  avgDurationMs: 192000,   // 3m 12s
  tokensToday: 125000,
  tokensCostToday: 1.50,
}

// ─── Execution history (42 records) ──────────────────────────────────────────

const WORKFLOW_NAMES = [
  'Data Pipeline',
  'Daily Report',
  'Content Generator',
  'Email Sender',
  'Code Reviewer',
  'Slack Notifier',
]

const WORKFLOW_IDS = ['wf-1', 'wf-2', 'wf-3', 'wf-4', 'wf-5', 'wf-6']

// Deterministic data — no Math.random() so it's stable across renders
const RAW_EXECUTIONS: Array<{
  minutesAgo: number
  wfIdx: number
  status: ExecutionRecord['status']
  durationMs: number
  tokens: number
}> = [
  { minutesAgo: 5,    wfIdx: 0, status: 'running',  durationMs: 0,      tokens: 0 },
  { minutesAgo: 18,   wfIdx: 1, status: 'success',  durationMs: 125000, tokens: 3200 },
  { minutesAgo: 32,   wfIdx: 2, status: 'success',  durationMs: 210000, tokens: 5100 },
  { minutesAgo: 47,   wfIdx: 3, status: 'failed',   durationMs: 42000,  tokens: 800 },
  { minutesAgo: 65,   wfIdx: 0, status: 'success',  durationMs: 185000, tokens: 4300 },
  { minutesAgo: 80,   wfIdx: 4, status: 'success',  durationMs: 310000, tokens: 7600 },
  { minutesAgo: 95,   wfIdx: 1, status: 'success',  durationMs: 115000, tokens: 2900 },
  { minutesAgo: 112,  wfIdx: 5, status: 'success',  durationMs: 55000,  tokens: 1200 },
  { minutesAgo: 135,  wfIdx: 2, status: 'success',  durationMs: 195000, tokens: 4800 },
  { minutesAgo: 160,  wfIdx: 0, status: 'success',  durationMs: 205000, tokens: 5200 },
  { minutesAgo: 185,  wfIdx: 3, status: 'success',  durationMs: 68000,  tokens: 1500 },
  { minutesAgo: 210,  wfIdx: 4, status: 'failed',   durationMs: 88000,  tokens: 2100 },
  { minutesAgo: 240,  wfIdx: 1, status: 'success',  durationMs: 132000, tokens: 3100 },
  { minutesAgo: 275,  wfIdx: 2, status: 'success',  durationMs: 225000, tokens: 5500 },
  { minutesAgo: 310,  wfIdx: 0, status: 'success',  durationMs: 178000, tokens: 4100 },
  { minutesAgo: 345,  wfIdx: 5, status: 'success',  durationMs: 48000,  tokens: 980 },
  { minutesAgo: 380,  wfIdx: 1, status: 'success',  durationMs: 142000, tokens: 3400 },
  { minutesAgo: 420,  wfIdx: 3, status: 'success',  durationMs: 72000,  tokens: 1700 },
  { minutesAgo: 460,  wfIdx: 4, status: 'success',  durationMs: 295000, tokens: 7100 },
  { minutesAgo: 500,  wfIdx: 2, status: 'success',  durationMs: 215000, tokens: 5300 },
  { minutesAgo: 545,  wfIdx: 0, status: 'success',  durationMs: 192000, tokens: 4600 },
  { minutesAgo: 590,  wfIdx: 1, status: 'success',  durationMs: 118000, tokens: 2800 },
  { minutesAgo: 640,  wfIdx: 5, status: 'success',  durationMs: 52000,  tokens: 1100 },
  { minutesAgo: 690,  wfIdx: 2, status: 'success',  durationMs: 230000, tokens: 5700 },
  { minutesAgo: 740,  wfIdx: 3, status: 'success',  durationMs: 65000,  tokens: 1400 },
  { minutesAgo: 800,  wfIdx: 0, status: 'success',  durationMs: 188000, tokens: 4500 },
  { minutesAgo: 860,  wfIdx: 4, status: 'success',  durationMs: 320000, tokens: 7800 },
  { minutesAgo: 920,  wfIdx: 1, status: 'success',  durationMs: 128000, tokens: 3000 },
  { minutesAgo: 980,  wfIdx: 2, status: 'success',  durationMs: 200000, tokens: 4900 },
  { minutesAgo: 1050, wfIdx: 5, status: 'success',  durationMs: 58000,  tokens: 1300 },
  { minutesAgo: 1120, wfIdx: 0, status: 'success',  durationMs: 195000, tokens: 4700 },
  { minutesAgo: 1200, wfIdx: 3, status: 'success',  durationMs: 78000,  tokens: 1900 },
  { minutesAgo: 1280, wfIdx: 4, status: 'success',  durationMs: 305000, tokens: 7400 },
  { minutesAgo: 1360, wfIdx: 1, status: 'success',  durationMs: 135000, tokens: 3300 },
  { minutesAgo: 1450, wfIdx: 2, status: 'success',  durationMs: 220000, tokens: 5400 },
  { minutesAgo: 1540, wfIdx: 0, status: 'success',  durationMs: 182000, tokens: 4200 },
  { minutesAgo: 1640, wfIdx: 5, status: 'success',  durationMs: 62000,  tokens: 1450 },
  { minutesAgo: 1740, wfIdx: 3, status: 'success',  durationMs: 70000,  tokens: 1600 },
  { minutesAgo: 1840, wfIdx: 1, status: 'success',  durationMs: 122000, tokens: 2950 },
  { minutesAgo: 1950, wfIdx: 4, status: 'success',  durationMs: 285000, tokens: 6900 },
  { minutesAgo: 2060, wfIdx: 2, status: 'success',  durationMs: 208000, tokens: 5050 },
  { minutesAgo: 2180, wfIdx: 0, status: 'success',  durationMs: 198000, tokens: 4750 },
]

export const MOCK_EXECUTIONS: ExecutionRecord[] = RAW_EXECUTIONS.map((r, i) => ({
  id: `exec-${String(i + 1).padStart(3, '0')}`,
  workflowId: WORKFLOW_IDS[r.wfIdx],
  workflowName: WORKFLOW_NAMES[r.wfIdx],
  startedAt: new Date(Date.now() - r.minutesAgo * 60 * 1000).toISOString(),
  duration_ms: r.durationMs,
  status: r.status,
  tokensUsed: r.tokens,
}))

// ─── Execution timeline (last 30 days) ───────────────────────────────────────

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function labelForDaysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${MONTH_ABBR[d.getMonth()]} ${String(d.getDate()).padStart(2, '0')}`
}

const TIMELINE_SUCCESS = [2,3,1,4,2,5,3,6,4,3,2,4,5,7,4,3,8,6,5,4,7,6,8,9,7,8,10,9,11,8]
const TIMELINE_FAILED  = [0,1,0,0,1,0,1,0,0,1,0,0,1,0,0,1,0,1,0,0,0,1,0,1,0,0,0,1,1,0]

export const MOCK_TIMELINE: TimelineDataPoint[] = TIMELINE_SUCCESS.map((s, i) => ({
  date: labelForDaysAgo(29 - i),
  success: s,
  failed: TIMELINE_FAILED[i],
}))

// ─── Token usage (last 7 days) ────────────────────────────────────────────────

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const MOCK_TOKEN_USAGE: TokenDataPoint[] = [
  { date: DAYS[0], input: 14200, output: 5800 },
  { date: DAYS[1], input: 18500, output: 7200 },
  { date: DAYS[2], input: 12100, output: 4900 },
  { date: DAYS[3], input: 21000, output: 8100 },
  { date: DAYS[4], input: 16800, output: 6600 },
  { date: DAYS[5], input: 9200,  output: 3700 },
  { date: DAYS[6], input: 11500, output: 4600 },
]

// ─── Top workflows ────────────────────────────────────────────────────────────

export const MOCK_TOP_WORKFLOWS: WorkflowStat[] = [
  { name: 'Data Pipeline',      count: 15, successRate: 93 },
  { name: 'Daily Report',       count: 12, successRate: 100 },
  { name: 'Content Generator',  count: 8,  successRate: 87 },
  { name: 'Email Sender',       count: 4,  successRate: 100 },
  { name: 'Code Reviewer',      count: 3,  successRate: 83 },
]

// ─── Recent agents ────────────────────────────────────────────────────────────

export const MOCK_RECENT_AGENTS: RecentAgent[] = [
  { id: '1', name: 'SummaryBot',    role: 'analyst',    model: 'gpt-4o',            lastRunAt: new Date(Date.now() - 2 * 3600000).toISOString(),  status: 'idle' },
  { id: '2', name: 'EmailBot',      role: 'writer',     model: 'claude-sonnet-4-6', lastRunAt: new Date(Date.now() - 5 * 60000).toISOString(),    status: 'running' },
  { id: '3', name: 'DataPipeline',  role: 'processor',  model: 'gpt-4o-mini',       lastRunAt: new Date(Date.now() - 1 * 3600000).toISOString(),  status: 'idle' },
  { id: '4', name: 'CodeReviewer',  role: 'analyst',    model: 'claude-sonnet-4-6', lastRunAt: new Date(Date.now() - 3 * 3600000).toISOString(),  status: 'idle' },
  { id: '5', name: 'SlackNotifier', role: 'writer',     model: undefined,            lastRunAt: new Date(Date.now() - 30 * 60000).toISOString(),  status: 'idle' },
  { id: '6', name: 'Supervisor',    role: 'researcher', model: 'claude-opus-4-8',   lastRunAt: new Date(Date.now() - 15 * 60000).toISOString(),   status: 'idle' },
]

// ─── Mock API functions (replace with real fetch calls) ───────────────────────

const delay = <T>(ms: number, value: T): Promise<T> =>
  new Promise(res => setTimeout(() => res(value), ms))

export const api = {
  getDashboardStats:  () => delay(400,  MOCK_DASHBOARD_STATS),
  getExecutions:      () => delay(600,  MOCK_EXECUTIONS),
  getTimeline:        () => delay(500,  MOCK_TIMELINE),
  getTokenUsage:      () => delay(450,  MOCK_TOKEN_USAGE),
  getTopWorkflows:    () => delay(400,  MOCK_TOP_WORKFLOWS),
  getRecentAgents:    () => delay(350,  MOCK_RECENT_AGENTS),

  deleteExecution: (id: string) =>
    delay(200, { success: true, id }),

  rerunExecution: (id: string) =>
    delay(300, { success: true, newId: `exec-${Date.now()}`, originalId: id }),
}
