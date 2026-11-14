import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

export type AgentServiceInfo = {
  service: string
  display_name: string
  installed: boolean
  executable: string
  version: string
  dispatch_ready: boolean
  mode: 'dispatch' | 'observe_only'
  auth_status: string
  default_model: string
  available_models: Array<string>
  observed_sessions_count: number
  store_path: string
  active_runs: number
}

type ScannedSession = {
  service: string
  session_id: string
  cwd: string
  updated_at: number
  preview: string
}

type AgentRun = {
  id: string
  service: string
  model: string
  prompt: string
  cwd: string
  branch: string
  session_id: string
  queue_item_id: string
  project_id?: string
  workflow_id?: string
  role?: string
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'stopped'
  exit_code: number | null
  response_text: string
  stderr_tail: string
  started_at: number
  finished_at: number | null
  metadata: {
    duration_s?: number
    branch_commit?: string
    total_tokens?: number
  }
}

type QueueItem = {
  id: string
  project_id?: string
  workflow_id?: string
  source_agent: string
  kind: string
  title: string
  body: string
  repo_path: string
  branch: string
  target_branch: string
  test_command: string
  priority: number
  status: string
  recommendation: string
  result: {
    test?: {
      command?: string
      exit_code?: number
      passed?: boolean
      stdout_tail?: string
      stderr_tail?: string
    }
    merged_commit?: string
  }
  created_at: number
}

type EvolutionRuleInfo = {
  id: string
  category: string
  rule_text: string
  source_type: string
  source_ref: string
  project_id: string
  evidence_count: number
}

type EvolutionStatusPayload = {
  active_generation?: number
  rules?: Array<EvolutionRuleInfo>
  rules_count?: number
}

export type InspectorTab = 'queue' | 'agents' | 'runs' | 'evolution'

type AutoplanInspectorProps = {
  services: Array<AgentServiceInfo>
  chiefLlmStatus: string
  activeProjectId?: string
  onRunSimpleTask: (service: string) => Promise<void>
  busyDemoService: string | null
  onRefreshAgents: () => void
  onRefreshHistory?: () => void
  onRunFinished?: (runId: string) => void
  activeTab?: InspectorTab
  onTabChange?: (tab: InspectorTab) => void
}

const DEFAULT_WIDTH = 360
const MIN_WIDTH = 280
const MAX_WIDTH = 520

const DECISION_ALLOWED: Record<string, Array<string>> = {
  approve: ['needs_review'],
  request_changes: ['needs_review', 'queued', 'triaged'],
  reject: ['needs_review', 'queued', 'triaged', 'in_progress'],
  snooze: ['needs_review', 'queued', 'triaged'],
}

function cleanRecommendation(raw: string): string {
  return raw.replace(/^\[[^\]]+\]\s*/, '').trim()
}

export function AutoplanInspector({
  services,
  activeProjectId = '',
  onRunSimpleTask,
  busyDemoService,
  onRefreshAgents,
  onRefreshHistory,
  onRunFinished,
  activeTab,
  onTabChange,
}: AutoplanInspectorProps) {
  const [internalTab, setInternalTab] = useState<InspectorTab>('queue')
  const tab = activeTab ?? internalTab
  const setTab = useCallback(
    (next: InspectorTab) => {
      setInternalTab(next)
      onTabChange?.(next)
    },
    [onTabChange],
  )
  const [width, setWidth] = useState<number>(DEFAULT_WIDTH)
  const [items, setItems] = useState<Array<QueueItem>>([])
  const [runs, setRuns] = useState<Array<AgentRun>>([])
  const [queueFilter, setQueueFilter] = useState<string>('')
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const [decisionNote, setDecisionNote] = useState<string>('')
  const [expandedSessionsSvc, setExpandedSessionsSvc] = useState<string | null>(
    null,
  )
  const [scannedSessions, setScannedSessions] = useState<
    Record<string, Array<ScannedSession>>
  >({})
  const [evolutionStatus, setEvolutionStatus] =
    useState<EvolutionStatusPayload | null>(null)
  const [evolving, setEvolving] = useState(false)
  const [newRuleText, setNewRuleText] = useState('')
  const [addingRule, setAddingRule] = useState(false)
  const [inspectorError, setInspectorError] = useState<string>('')
  const dragStartRef = useRef<{ x: number; w: number } | null>(null)
  const prevRunStatesRef = useRef<Record<string, string> | null>(null)

  const refreshEvolution = useCallback(async () => {
    try {
      const projParam = activeProjectId
        ? `?project_id=${encodeURIComponent(activeProjectId)}`
        : ''
      const eRes = await fetch(`/api/autoplan/evolution/status${projParam}`)
      if (eRes.ok) {
        const eData = (await eRes.json()) as EvolutionStatusPayload
        setEvolutionStatus(eData)
      }
    } catch {
      // ignore background poll errors
    }
  }, [activeProjectId])

  const refreshQueueAndRuns = useCallback(async () => {
    try {
      const qQuery = queueFilter
        ? `?status=${encodeURIComponent(queueFilter)}`
        : ''
      const [qRes, rRes] = await Promise.all([
        fetch(`/api/autoplan/queue/items${qQuery}`),
        fetch('/api/autoplan/agents/runs?limit=30'),
      ])
      const qData = (await qRes.json()) as {
        success?: boolean
        items?: Array<QueueItem>
        error?: string
      }
      const rData = (await rRes.json()) as {
        success?: boolean
        runs?: Array<AgentRun>
        error?: string
      }
      if (!qRes.ok || qData.success === false) {
        throw new Error(qData.error || `Queue HTTP ${qRes.status}`)
      }
      if (!rRes.ok || rData.success === false) {
        throw new Error(rData.error || `Runs HTTP ${rRes.status}`)
      }
      const nextItems = qData.items || []
      const nextRuns = rData.runs || []

      const prevStates = prevRunStatesRef.current
      const nextStates: Record<string, string> = {}
      let shouldRefreshChat = false
      for (const run of nextRuns) {
        nextStates[run.id] = run.state
        if (prevStates !== null && prevStates[run.id] !== run.state) {
          shouldRefreshChat = true
          if (
            run.state === 'succeeded' ||
            run.state === 'failed' ||
            run.state === 'stopped'
          ) {
            onRunFinished?.(run.id)
          }
        }
      }
      prevRunStatesRef.current = nextStates
      if (shouldRefreshChat) {
        onRefreshHistory?.()
      }

      setItems(nextItems)
      setRuns(nextRuns)
      setSelectedItemId((prev) => {
        if (prev && nextItems.some((it) => it.id === prev)) return prev
        return nextItems.length > 0 ? nextItems[0].id : null
      })
      setInspectorError('')
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    }
  }, [onRefreshHistory, onRunFinished, queueFilter])

  useEffect(() => {
    void refreshQueueAndRuns()
    void refreshEvolution()
    const interval = window.setInterval(() => {
      void refreshQueueAndRuns()
    }, 2500)
    const onLiveEvent = () => {
      void refreshQueueAndRuns()
      void refreshEvolution()
    }
    window.addEventListener('autoplan:event', onLiveEvent)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('autoplan:event', onLiveEvent)
    }
  }, [refreshEvolution, refreshQueueAndRuns])

  useEffect(() => {
    function onMouseMove(e: MouseEvent) {
      if (!dragStartRef.current) return
      const delta = dragStartRef.current.x - e.clientX
      const next = Math.min(
        MAX_WIDTH,
        Math.max(MIN_WIDTH, dragStartRef.current.w + delta),
      )
      setWidth(next)
    }
    function onMouseUp() {
      dragStartRef.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  async function decideItem(itemId: string, action: string) {
    try {
      const res = await fetch(`/api/autoplan/queue/items/${itemId}/decision`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          action,
          note: decisionNote.trim(),
          actor: 'webclaw-operator',
        }),
      })
      const payload = (await res.json()) as { success?: boolean; error?: string }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Decision HTTP ${res.status}`)
      }
      setDecisionNote('')
      await refreshQueueAndRuns()
      await refreshEvolution()
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    }
  }

  async function wakeItem(itemId: string) {
    try {
      const res = await fetch(`/api/autoplan/queue/items/${itemId}/wake`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
      })
      const payload = (await res.json()) as { success?: boolean; error?: string }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Wake HTTP ${res.status}`)
      }
      await refreshQueueAndRuns()
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    }
  }

  async function stopRun(runId: string) {
    try {
      const res = await fetch(`/api/autoplan/agents/runs/${runId}/stop`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
      })
      const payload = (await res.json()) as { success?: boolean; error?: string }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Stop HTTP ${res.status}`)
      }
      await refreshQueueAndRuns()
      onRefreshAgents()
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    }
  }

  async function toggleScannedSessions(serviceId: string) {
    if (expandedSessionsSvc === serviceId) {
      setExpandedSessionsSvc(null)
      return
    }
    setExpandedSessionsSvc(serviceId)
    try {
      const res = await fetch(
        `/api/autoplan/agents/${encodeURIComponent(serviceId)}/sessions?limit=8`,
      )
      const payload = (await res.json()) as {
        success?: boolean
        sessions?: Array<ScannedSession>
        error?: string
      }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Scan HTTP ${res.status}`)
      }
      setScannedSessions((prev) => ({
        ...prev,
        [serviceId]: payload.sessions || [],
      }))
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleRunEvolution() {
    setEvolving(true)
    setInspectorError('')
    try {
      const res = await fetch('/api/autoplan/evolution/evolve', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          project_id: activeProjectId || '*',
          reason: 'inspector_manual',
        }),
      })
      const payload = (await res.json()) as { success?: boolean; error?: string }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Evolution HTTP ${res.status}`)
      }
      await refreshEvolution()
      window.dispatchEvent(new CustomEvent('autoplan:event'))
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    } finally {
      setEvolving(false)
    }
  }

  async function handleAddRule(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = newRuleText.trim()
    if (!trimmed) return
    setAddingRule(true)
    setInspectorError('')
    try {
      const res = await fetch('/api/autoplan/evolution/rules', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          rule_text: trimmed,
          category: 'operator_rule',
          project_id: activeProjectId || '*',
        }),
      })
      const payload = (await res.json()) as { success?: boolean; error?: string }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Rule HTTP ${res.status}`)
      }
      setNewRuleText('')
      await refreshEvolution()
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    } finally {
      setAddingRule(false)
    }
  }

  const selectedItem = items.find((it) => it.id === selectedItemId) ?? null
  const needsReviewCount = items.filter((i) => i.status === 'needs_review').length
  const activeRunsCount = runs.filter((r) => r.state === 'running').length

  return (
    <aside
      data-testid="autoplan-inspector"
      style={{ width: `${width}px` }}
      className="relative flex h-full shrink-0 border-l border-primary-200 bg-surface text-xs text-primary-900"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panel"
        data-testid="inspector-resizer"
        onDoubleClick={() => setWidth(DEFAULT_WIDTH)}
        onMouseDown={(e) => {
          dragStartRef.current = { x: e.clientX, w: width }
          document.body.style.cursor = 'ew-resize'
          document.body.style.userSelect = 'none'
        }}
        className="w-1 cursor-ew-resize hover:bg-primary-300 shrink-0"
      />

      <div className="flex min-w-0 flex-1 flex-col h-full overflow-hidden">
        {/* 3 tabs max (1 active + 2 adjacent labels) */}
        <div className="flex h-10 shrink-0 items-stretch border-b border-primary-200 px-3 gap-4">
          {(
            [
              [
                'queue',
                'inspector-tab-queue',
                needsReviewCount > 0 ? `Review (${needsReviewCount})` : 'Review',
              ],
              [
                'agents',
                'inspector-tab-agents',
                activeRunsCount > 0 ? `Agents (${activeRunsCount})` : 'Agents',
              ],
              ['evolution', 'inspector-tab-evolution', 'Rules'],
            ] as const
          ).map(([id, testId, label]) => {
            const isActive =
              tab === id || (id === 'agents' && tab === 'runs')
            return (
              <button
                key={id}
                type="button"
                data-testid={testId}
                onClick={() => setTab(id)}
                className={cn(
                  'flex items-center border-b-2 text-xs font-medium transition-colors tabular-nums',
                  isActive
                    ? 'border-primary-950 text-primary-950'
                    : 'border-transparent text-primary-600 hover:text-primary-900',
                )}
              >
                {label}
              </button>
            )
          })}
        </div>

        {inspectorError ? (
          <div
            data-testid="inspector-error"
            role="alert"
            className="border-b border-red-500/40 bg-red-500/10 px-3 py-1.5 text-red-500"
          >
            {inspectorError}
          </div>
        ) : null}

        {tab === 'queue' ? (
          <div className="flex flex-1 flex-col min-h-0 overflow-hidden">
            <div className="flex items-center justify-between border-b border-primary-200 px-3 py-1.5 text-xs text-primary-600">
              <span className="tabular-nums">{items.length} items</span>
              <select
                aria-label="Filter status"
                data-testid="webclaw-queue-filter"
                value={queueFilter}
                onChange={(e) => setQueueFilter(e.target.value)}
                className="rounded bg-primary-100 px-2 py-0.5 text-xs text-primary-800 outline-none"
              >
                <option value="">All</option>
                <option value="needs_review">Needs review</option>
                <option value="landed">Landed</option>
                <option value="done">Done</option>
                <option value="snoozed">Snoozed</option>
              </select>
            </div>

            <div
              data-testid="webclaw-queue-list"
              className="max-h-56 shrink-0 overflow-y-auto border-b border-primary-200 divide-y divide-primary-200"
            >
              {items.length === 0 ? (
                <div className="px-3 py-6 text-center text-primary-500">
                  Nothing waiting for review.
                </div>
              ) : (
                items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    data-testid={`webclaw-queue-item-${item.id}`}
                    onClick={() => setSelectedItemId(item.id)}
                    className={cn(
                      'block w-full px-3 py-2 text-left transition-colors',
                      selectedItemId === item.id
                        ? 'bg-primary-100'
                        : 'hover:bg-primary-100/50',
                    )}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-medium text-primary-950 truncate">
                        {item.title}
                      </span>
                      <span className="shrink-0 text-[11px] text-primary-600">
                        {item.status}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-primary-500 truncate">
                      {item.source_agent}
                      {item.branch ? ` · ${item.branch}` : ''}
                    </div>
                  </button>
                ))
              )}
            </div>

            <div
              data-testid="webclaw-queue-detail"
              className="flex-1 overflow-y-auto px-3 py-3 space-y-2.5"
            >
              {selectedItem ? (
                <>
                  <div>
                    <div className="font-medium text-sm text-primary-950 text-pretty">
                      {selectedItem.title}
                    </div>
                    <div className="mt-0.5 text-[11px] text-primary-600">
                      <span data-testid="webclaw-detail-status">
                        {selectedItem.status}
                      </span>
                      {selectedItem.branch
                        ? ` · ${selectedItem.branch}`
                        : ` · ${selectedItem.source_agent}`}
                    </div>
                  </div>

                  {selectedItem.recommendation ? (
                    <p className="text-xs text-primary-800 text-pretty">
                      {cleanRecommendation(selectedItem.recommendation)}
                    </p>
                  ) : null}

                  {selectedItem.result?.test ? (
                    <div
                      data-testid="webclaw-detail-test"
                      className="rounded-md bg-primary-100 px-2.5 py-1.5 font-mono text-[11px] text-primary-800"
                    >
                      Test exit {String(selectedItem.result.test.exit_code)} (
                      {selectedItem.result.test.passed ? 'passed' : 'failed'})
                    </div>
                  ) : null}

                  {selectedItem.result?.merged_commit ? (
                    <div
                      data-testid="webclaw-merged-commit"
                      className="font-mono text-[11px] text-primary-600"
                    >
                      Landed {selectedItem.result.merged_commit.slice(0, 10)}
                    </div>
                  ) : null}

                  {selectedItem.body ? (
                    <pre className="max-h-32 overflow-auto rounded-md bg-primary-100 p-2 font-mono text-[11px] text-primary-800 whitespace-pre-wrap">
                      {selectedItem.body}
                    </pre>
                  ) : null}

                  <input
                    type="text"
                    data-testid="webclaw-decision-note-input"
                    value={decisionNote}
                    onChange={(e) => setDecisionNote(e.target.value)}
                    placeholder="Add feedback note (optional)…"
                    className="h-7 w-full rounded-md border border-primary-200 bg-primary-100 px-2 text-xs text-primary-950 placeholder:text-primary-500 outline-none"
                  />

                  <div className="flex items-center gap-1.5 pt-0.5">
                    <button
                      type="button"
                      data-testid="webclaw-approve-button"
                      disabled={
                        !DECISION_ALLOWED.approve.includes(selectedItem.status)
                      }
                      onClick={() => void decideItem(selectedItem.id, 'approve')}
                      className="h-7 rounded-md bg-primary-900 px-3 text-xs font-medium text-surface disabled:cursor-not-allowed disabled:bg-primary-200 disabled:text-primary-500 disabled:opacity-40"
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      data-testid="webclaw-request-changes-button"
                      disabled={
                        !DECISION_ALLOWED.request_changes.includes(
                          selectedItem.status,
                        )
                      }
                      onClick={() =>
                        void decideItem(selectedItem.id, 'request_changes')
                      }
                      className="h-7 rounded-md border border-primary-200 px-2.5 text-xs text-primary-800 hover:bg-primary-100 disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      Request changes
                    </button>
                    <details className="relative">
                      <summary className="flex h-7 cursor-pointer list-none items-center rounded-md px-2 text-xs text-primary-600 hover:bg-primary-100 hover:text-primary-950">
                        More
                      </summary>
                      <div className="absolute right-0 bottom-8 z-20 flex w-28 flex-col rounded-md border border-primary-200 bg-surface p-1 shadow-md">
                        <button
                          type="button"
                          data-testid="webclaw-reject-button"
                          disabled={
                            !DECISION_ALLOWED.reject.includes(
                              selectedItem.status,
                            )
                          }
                          onClick={() =>
                            void decideItem(selectedItem.id, 'reject')
                          }
                          className="rounded px-2 py-1 text-left text-xs text-primary-800 hover:bg-primary-100 disabled:opacity-35"
                        >
                          Reject
                        </button>
                        <button
                          type="button"
                          data-testid="webclaw-snooze-button"
                          disabled={
                            !DECISION_ALLOWED.snooze.includes(
                              selectedItem.status,
                            )
                          }
                          onClick={() =>
                            void decideItem(selectedItem.id, 'snooze')
                          }
                          className="rounded px-2 py-1 text-left text-xs text-primary-800 hover:bg-primary-100 disabled:opacity-35"
                        >
                          Snooze
                        </button>
                        {selectedItem.status === 'snoozed' ||
                        selectedItem.status === 'failed' ? (
                          <button
                            type="button"
                            data-testid="webclaw-wake-button"
                            onClick={() => void wakeItem(selectedItem.id)}
                            className="rounded px-2 py-1 text-left text-xs font-medium text-primary-900 hover:bg-primary-100"
                          >
                            Wake
                          </button>
                        ) : null}
                      </div>
                    </details>
                  </div>
                </>
              ) : (
                <div className="py-4 text-primary-500">
                  Select an item above to review.
                </div>
              )}
            </div>
          </div>
        ) : null}

        {tab === 'agents' || tab === 'runs' ? (
          <div className="flex flex-1 flex-col min-h-0 overflow-hidden">
            <div className="flex items-center justify-between border-b border-primary-200 px-3 py-1.5">
              <div className="flex rounded-md bg-primary-100 p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => setTab('agents')}
                  className={cn(
                    'rounded px-2 py-0.5 font-medium transition-colors',
                    tab === 'agents'
                      ? 'bg-surface text-primary-950 shadow-2xs'
                      : 'text-primary-600 hover:text-primary-900',
                  )}
                >
                  Services
                </button>
                <button
                  type="button"
                  data-testid="inspector-tab-runs"
                  onClick={() => setTab('runs')}
                  className={cn(
                    'rounded px-2 py-0.5 font-medium transition-colors tabular-nums',
                    tab === 'runs'
                      ? 'bg-surface text-primary-950 shadow-2xs'
                      : 'text-primary-600 hover:text-primary-900',
                  )}
                >
                  {runs.length > 0 ? `Runs (${runs.length})` : 'Runs'}
                </button>
              </div>
            </div>

            {tab === 'agents' ? (
              <div
                data-testid="webclaw-agents-list"
                className="flex-1 overflow-y-auto divide-y divide-primary-200"
              >
            {services.map((svc) => (
              <div
                key={svc.service}
                data-testid={`agent-card-${svc.service}`}
                className="p-3 space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-sm text-primary-950">
                    {svc.display_name}
                  </span>
                  <span
                    data-testid={`agent-mode-${svc.service}`}
                    className="text-[11px] text-primary-600"
                  >
                    {svc.mode}
                  </span>
                </div>
                <div className="text-[11px] text-primary-600">
                  {svc.default_model || 'default'} ·{' '}
                  <span data-testid={`agent-sessions-count-${svc.service}`}>
                    {svc.observed_sessions_count} sessions
                  </span>
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    data-testid={`agent-demo-btn-${svc.service}`}
                    disabled={
                      !svc.dispatch_ready || busyDemoService === svc.service
                    }
                    onClick={() => void onRunSimpleTask(svc.service)}
                    className="h-7 rounded-md border border-primary-200 bg-primary-100 px-2.5 text-xs font-medium text-primary-900 hover:bg-primary-200 disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    {busyDemoService === svc.service
                      ? 'Starting…'
                      : 'Start Demo'}
                  </button>
                  <button
                    type="button"
                    data-testid={`agent-scan-btn-${svc.service}`}
                    onClick={() => void toggleScannedSessions(svc.service)}
                    className="h-7 rounded-md px-2 text-xs text-primary-600 hover:bg-primary-100 hover:text-primary-950"
                  >
                    {expandedSessionsSvc === svc.service
                      ? 'Hide sessions'
                      : 'Recent sessions'}
                  </button>
                </div>

                {expandedSessionsSvc === svc.service ? (
                  <div
                    data-testid={`agent-scanned-list-${svc.service}`}
                    className="mt-2 border-t border-primary-200 pt-2 space-y-1 text-[11px]"
                  >
                    {(scannedSessions[svc.service] || []).length === 0 ? (
                      <div className="text-primary-500">
                        No sessions found locally.
                      </div>
                    ) : (
                      (scannedSessions[svc.service] || []).map((s) => (
                        <div key={s.session_id} className="py-1">
                          <div className="truncate font-mono text-primary-800">
                            {s.session_id}
                          </div>
                          {s.preview ? (
                            <div className="truncate text-primary-500">
                              {s.preview}
                            </div>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                ) : null}
              </div>
            ))}
              </div>
            ) : (
              <div
                data-testid="webclaw-runs-list"
                className="flex-1 overflow-y-auto divide-y divide-primary-200"
              >
                {runs.length === 0 ? (
                  <div className="p-4 text-primary-500">No runs yet.</div>
                ) : (
                  runs.map((run) => (
                    <div
                      key={run.id}
                      data-testid={`webclaw-run-${run.id}`}
                      className="p-3 space-y-1"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-primary-950">
                          {run.service}
                          {run.role ? ` · ${run.role}` : ''}
                        </span>
                        <span
                          data-testid={`webclaw-run-state-${run.id}`}
                          className="text-[11px] text-primary-600 tabular-nums"
                        >
                          {run.state}
                        </span>
                      </div>
                      <div className="truncate text-xs text-primary-600">
                        {run.prompt}
                      </div>
                      {run.response_text ? (
                        <pre className="max-h-20 overflow-auto rounded bg-primary-100 p-2 font-mono text-[11px] text-primary-800 whitespace-pre-wrap">
                          {run.response_text}
                        </pre>
                      ) : null}
                      {run.state === 'running' ? (
                        <button
                          type="button"
                          data-testid={`webclaw-stop-run-${run.id}`}
                          onClick={() => void stopRun(run.id)}
                          className="rounded border border-red-500/50 px-2 py-0.5 text-xs text-red-500"
                        >
                          Stop
                        </button>
                      ) : null}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        ) : null}

        {tab === 'evolution' ? (
          <div
            data-testid="webclaw-evolution-panel"
            className="flex-1 overflow-y-auto p-3 space-y-3"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-primary-950">
                Project Guardrails
              </span>
              <button
                type="button"
                data-testid="inspector-evolve-button"
                disabled={evolving}
                onClick={() => void handleRunEvolution()}
                className="h-7 rounded-md border border-primary-200 bg-primary-100 px-2.5 text-xs font-medium text-primary-900 hover:bg-primary-200 disabled:opacity-40"
              >
                {evolving ? 'Updating…' : 'Update from feedback'}
              </button>
            </div>

            <form
              data-testid="inspector-add-rule-form"
              onSubmit={(e) => void handleAddRule(e)}
              className="flex gap-1.5"
            >
              <input
                type="text"
                data-testid="inspector-add-rule-input"
                value={newRuleText}
                onChange={(e) => setNewRuleText(e.target.value)}
                placeholder="Add guardrail rule…"
                className="h-7 min-w-0 flex-1 rounded-md border border-primary-200 bg-primary-100 px-2 text-xs text-primary-950 outline-none"
              />
              <button
                type="submit"
                disabled={addingRule || !newRuleText.trim()}
                className="h-7 shrink-0 rounded-md bg-primary-900 px-2.5 text-xs font-medium text-surface disabled:opacity-40"
              >
                Add
              </button>
            </form>

            <div className="divide-y divide-primary-200">
              {(evolutionStatus?.rules ?? []).map((rule) => (
                <div
                  key={rule.id}
                  data-testid={`evolution-rule-${rule.id}`}
                  className="py-2 text-xs text-primary-800 text-pretty"
                >
                  {rule.rule_text}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </aside>
  )
}
