import { useCallback, useEffect, useRef, useState } from 'react'

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

type PromptVersionInfo = {
  id: string
  worker_role: string
  generation: number
  prompt_template: string
  rationale: string
  pass_count: number
  fail_count: number
  active: boolean
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

type ServiceFitnessEntry = {
  service?: string
  total_runs: number
  succeeded_runs: number
  failed_runs: number
  pass_rate: number | null
}

type EvolutionStatusPayload = {
  bootstrap?: {
    corpus_loaded?: boolean
    corpus_total_prompts?: number
    corpus_total_sessions?: number
  }
  active_generation?: number
  active_prompts?: {
    lead_planner?: PromptVersionInfo | null
    chief_triage?: PromptVersionInfo | null
  }
  rules?: Array<EvolutionRuleInfo>
  rules_count?: number
  service_fitness?: Record<string, ServiceFitnessEntry> | Array<ServiceFitnessEntry>
}

type LlmDiagnosticsPayload = {
  configured?: boolean
  status_label?: string
  last_provider_used?: string
  total_hybrid_calls?: number
  chromium_prompt_bridge?: {
    connected?: boolean
    total_bridged_calls?: number
    last_call_latency_ms?: number | null
    active_client?: {
      app_name?: string
      chrome_version?: string
      local_backend_model?: string
    } | null
  }
  gemini_nano_investigation?: {
    weights_present?: boolean
    summary?: string
  }
  local_mlx?: {
    available?: boolean
    listening?: boolean
    model_id?: string
  }
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

const DEFAULT_WIDTH = 392
const MIN_WIDTH = 290
const MAX_WIDTH = 560

const DECISION_ALLOWED: Record<string, Array<string>> = {
  approve: ['needs_review'],
  request_changes: ['needs_review', 'queued', 'triaged'],
  reject: ['needs_review', 'queued', 'triaged', 'in_progress'],
  snooze: ['needs_review', 'queued', 'triaged'],
}

export function AutoplanInspector({
  services,
  chiefLlmStatus,
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
  const [llmStatus, setLlmStatus] = useState<LlmDiagnosticsPayload | null>(null)
  const [evolving, setEvolving] = useState(false)
  const [newRuleText, setNewRuleText] = useState('')
  const [addingRule, setAddingRule] = useState(false)
  const [inspectorError, setInspectorError] = useState<string>('')
  const dragStartRef = useRef<{ x: number; w: number } | null>(null)
  const prevRunStatesRef = useRef<Record<string, string> | null>(null)

  const refreshEvolutionAndLlm = useCallback(async () => {
    try {
      const projParam = activeProjectId
        ? `?project_id=${encodeURIComponent(activeProjectId)}`
        : ''
      const [eRes, lRes] = await Promise.all([
        fetch(`/api/autoplan/evolution/status${projParam}`),
        fetch('/api/autoplan/llm/status'),
      ])
      if (eRes.ok) {
        const eData = (await eRes.json()) as EvolutionStatusPayload
        setEvolutionStatus(eData)
      }
      if (lRes.ok) {
        const lData = (await lRes.json()) as LlmDiagnosticsPayload
        setLlmStatus(lData)
      }
    } catch {
      // Handled via main inspectorError when explicit action runs
    }
  }, [activeProjectId])

  const refreshQueueAndRuns = useCallback(async () => {
    try {
      const qQuery = queueFilter ? `?status=${encodeURIComponent(queueFilter)}` : ''
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
    void refreshEvolutionAndLlm()
    const interval = window.setInterval(() => {
      void refreshQueueAndRuns()
      if (tab === 'evolution') {
        void refreshEvolutionAndLlm()
      }
    }, 3000)
    const onLiveEvent = () => {
      void refreshQueueAndRuns()
      void refreshEvolutionAndLlm()
      onRefreshAgents()
    }
    window.addEventListener('autoplan:event', onLiveEvent)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('autoplan:event', onLiveEvent)
    }
  }, [onRefreshAgents, refreshEvolutionAndLlm, refreshQueueAndRuns, tab])

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
      await refreshEvolutionAndLlm()
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
      await refreshEvolutionAndLlm()
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
      await refreshEvolutionAndLlm()
    } catch (err) {
      setInspectorError(err instanceof Error ? err.message : String(err))
    } finally {
      setAddingRule(false)
    }
  }

  const selectedItem = items.find((it) => it.id === selectedItemId) ?? null
  const activeRunsCount = runs.filter((r) => r.state === 'running').length
  const activeGen = evolutionStatus?.active_generation ?? 1

  const fitnessRows: Array<{ service: string } & ServiceFitnessEntry> = (() => {
    const raw = evolutionStatus?.service_fitness
    if (!raw) return []
    if (Array.isArray(raw)) {
      return raw.map((r) => ({ ...r, service: r.service || 'unknown' }))
    }
    return Object.entries(raw).map(([svc, val]) => ({ ...val, service: svc }))
  })()

  return (
    <aside
      data-testid="autoplan-inspector"
      style={{ width: `${width}px` }}
      className="relative flex h-full shrink-0 border-l border-primary-200 bg-surface text-xs text-primary-900"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize inspector pane"
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
        <div className="flex h-10 shrink-0 items-center border-b border-primary-200 px-2">
          <div className="grid w-full grid-cols-4 gap-0.5 rounded-lg border border-primary-200 bg-primary-100 p-0.5 text-[11px]">
            <button
              type="button"
              data-testid="inspector-tab-queue"
              onClick={() => setTab('queue')}
              className={`rounded-md px-1.5 py-1 text-center font-medium transition-colors truncate ${
                tab === 'queue'
                  ? 'border border-primary-300 bg-surface text-primary-950'
                  : 'border border-transparent text-primary-700 hover:text-primary-900'
              }`}
            >
              Queue ({items.length})
            </button>
            <button
              type="button"
              data-testid="inspector-tab-agents"
              onClick={() => setTab('agents')}
              className={`rounded-md px-1.5 py-1 text-center font-medium transition-colors truncate ${
                tab === 'agents'
                  ? 'border border-primary-300 bg-surface text-primary-950'
                  : 'border border-transparent text-primary-700 hover:text-primary-900'
              }`}
            >
              Agents ({services.length})
            </button>
            <button
              type="button"
              data-testid="inspector-tab-runs"
              onClick={() => setTab('runs')}
              className={`rounded-md px-1.5 py-1 text-center font-medium transition-colors truncate ${
                tab === 'runs'
                  ? 'border border-primary-300 bg-surface text-primary-950'
                  : 'border border-transparent text-primary-700 hover:text-primary-900'
              }`}
            >
              Runs ({activeRunsCount > 0 ? `${activeRunsCount} live` : runs.length})
            </button>
            <button
              type="button"
              data-testid="inspector-tab-evolution"
              onClick={() => setTab('evolution')}
              className={`rounded-md px-1.5 py-1 text-center font-medium transition-colors truncate ${
                tab === 'evolution'
                  ? 'border border-primary-300 bg-surface text-primary-950'
                  : 'border border-transparent text-primary-700 hover:text-primary-900'
              }`}
            >
              Brain (v{activeGen})
            </button>
          </div>
        </div>

        {inspectorError ? (
          <div
            data-testid="inspector-error"
            role="alert"
            className="border-b border-red-500/40 bg-red-500/10 px-3 py-1.5 text-red-600"
          >
            {inspectorError}
          </div>
        ) : null}

        {tab === 'queue' ? (
          <div className="flex flex-1 flex-col min-h-0 overflow-hidden">
            <div className="flex items-center justify-between border-b border-primary-200 px-3 py-1.5 text-[11px] text-primary-600">
              <span data-testid="webclaw-chief-status" className="truncate">
                Chief: {chiefLlmStatus || 'deterministic'}
              </span>
              <select
                aria-label="Filter queue status"
                data-testid="webclaw-queue-filter"
                value={queueFilter}
                onChange={(e) => setQueueFilter(e.target.value)}
                className="border border-primary-200 bg-surface px-1.5 py-0.5 text-[11px]"
              >
                <option value="">all</option>
                <option value="needs_review">needs_review</option>
                <option value="queued">queued</option>
                <option value="in_progress">in_progress</option>
                <option value="landed">landed</option>
                <option value="done">done</option>
                <option value="snoozed">snoozed</option>
                <option value="rejected">rejected</option>
              </select>
            </div>

            <div
              data-testid="webclaw-queue-list"
              className="max-h-52 shrink-0 overflow-y-auto border-b border-primary-200"
            >
              {items.length === 0 ? (
                <div className="px-3 py-4 text-primary-500">
                  No queue items match filter.
                </div>
              ) : (
                items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    data-testid={`webclaw-queue-item-${item.id}`}
                    onClick={() => setSelectedItemId(item.id)}
                    className={`block w-full border-b border-primary-200 px-3 py-2 text-left ${
                      selectedItemId === item.id
                        ? 'bg-primary-100'
                        : 'hover:bg-primary-50'
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-medium truncate">{item.title}</span>
                      <span className="shrink-0 font-mono text-[11px] border border-primary-300 px-1">
                        {item.status}
                      </span>
                    </div>
                    <div className="mt-0.5 font-mono text-[11px] text-primary-600 truncate">
                      P{item.priority} · {item.kind} · {item.source_agent}
                    </div>
                  </button>
                ))
              )}
            </div>

            <div
              data-testid="webclaw-queue-detail"
              className="flex-1 overflow-y-auto px-3 py-2.5 space-y-2.5"
            >
              {selectedItem ? (
                <>
                  <div>
                    <div className="font-semibold text-sm">
                      {selectedItem.title}
                    </div>
                    <div className="mt-0.5 font-mono text-[11px] text-primary-600">
                      <span data-testid="webclaw-detail-status">
                        {selectedItem.status}
                      </span>
                      {' · '}P{selectedItem.priority} · {selectedItem.source_agent}
                      {selectedItem.branch
                        ? ` · ${selectedItem.branch} → ${selectedItem.target_branch}`
                        : ''}
                    </div>
                  </div>

                  {selectedItem.recommendation ? (
                    <div className="border border-primary-200 p-2 text-[11px]">
                      {selectedItem.recommendation}
                    </div>
                  ) : null}

                  {selectedItem.result?.test ? (
                    <div
                      data-testid="webclaw-detail-test"
                      className="border border-primary-200 p-2 font-mono text-[11px]"
                    >
                      Test exit {String(selectedItem.result.test.exit_code)} (
                      {selectedItem.result.test.passed ? 'passed' : 'failed'}) ·{' '}
                      {selectedItem.result.test.command}
                    </div>
                  ) : null}

                  {selectedItem.result?.merged_commit ? (
                    <div
                      data-testid="webclaw-merged-commit"
                      className="border border-primary-200 p-2 font-mono text-[11px]"
                    >
                      Landed commit: {selectedItem.result.merged_commit.slice(0, 12)}
                    </div>
                  ) : null}

                  {selectedItem.body ? (
                    <pre className="max-h-36 overflow-auto border border-primary-200 p-2 font-mono text-[11px] whitespace-pre-wrap">
                      {selectedItem.body}
                    </pre>
                  ) : null}

                  <input
                    type="text"
                    data-testid="webclaw-decision-note-input"
                    value={decisionNote}
                    onChange={(e) => setDecisionNote(e.target.value)}
                    placeholder="Feedback note (learns into Brain on changes/reject)…"
                    className="w-full rounded border border-primary-200 bg-primary-50 px-2 py-1 text-[11px] text-primary-900 placeholder:text-primary-500 outline-none"
                  />

                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    <button
                      type="button"
                      data-testid="webclaw-approve-button"
                      disabled={
                        !DECISION_ALLOWED.approve.includes(selectedItem.status)
                      }
                      onClick={() => void decideItem(selectedItem.id, 'approve')}
                      className="rounded border border-primary-800 bg-primary-900 px-2.5 py-1 font-medium text-surface disabled:cursor-not-allowed disabled:border-primary-200 disabled:bg-primary-100 disabled:text-primary-400 disabled:opacity-60"
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
                      className="rounded border border-primary-300 px-2.5 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      Changes
                    </button>
                    <button
                      type="button"
                      data-testid="webclaw-reject-button"
                      disabled={
                        !DECISION_ALLOWED.reject.includes(selectedItem.status)
                      }
                      onClick={() => void decideItem(selectedItem.id, 'reject')}
                      className="rounded border border-primary-300 px-2.5 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      data-testid="webclaw-snooze-button"
                      disabled={
                        !DECISION_ALLOWED.snooze.includes(selectedItem.status)
                      }
                      onClick={() => void decideItem(selectedItem.id, 'snooze')}
                      className="rounded border border-primary-300 px-2.5 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      Snooze
                    </button>
                    {selectedItem.status === 'snoozed' ||
                    selectedItem.status === 'failed' ? (
                      <button
                        type="button"
                        data-testid="webclaw-wake-button"
                        onClick={() => void wakeItem(selectedItem.id)}
                        className="rounded border border-primary-800 px-2.5 py-1 font-medium"
                      >
                        Wake
                      </button>
                    ) : null}
                  </div>
                </>
              ) : (
                <div className="text-primary-500">
                  Select a queue item or dispatch work to populate the queue.
                </div>
              )}
            </div>
          </div>
        ) : null}

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
                  <span className="font-semibold text-sm">
                    {svc.display_name}
                  </span>
                  <span
                    data-testid={`agent-mode-${svc.service}`}
                    className="border border-primary-300 px-1.5 py-0.5 font-mono text-[11px]"
                  >
                    {svc.mode}
                  </span>
                </div>
                <div className="font-mono text-[11px] text-primary-600">
                  {svc.version || 'local store'} ·{' '}
                  {svc.default_model || 'no model'} ·{' '}
                  <span data-testid={`agent-sessions-count-${svc.service}`}>
                    {svc.observed_sessions_count} sessions
                  </span>
                </div>
                <div className="text-[11px] text-primary-600 break-words">
                  {svc.auth_status}
                </div>
                <div className="flex items-center gap-1.5 pt-1">
                  <button
                    type="button"
                    data-testid={`agent-demo-btn-${svc.service}`}
                    disabled={
                      !svc.dispatch_ready || busyDemoService === svc.service
                    }
                    onClick={() => void onRunSimpleTask(svc.service)}
                    className="rounded border border-primary-300 bg-primary-100 px-2.5 py-1 font-medium text-primary-900 hover:bg-primary-200 disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    {busyDemoService === svc.service
                      ? 'Starting…'
                      : 'Start Demo'}
                  </button>
                  <button
                    type="button"
                    data-testid={`agent-scan-btn-${svc.service}`}
                    onClick={() => void toggleScannedSessions(svc.service)}
                    className="rounded border border-primary-300 px-2 py-1"
                  >
                    {expandedSessionsSvc === svc.service
                      ? 'Hide sessions'
                      : 'Inspect sessions'}
                  </button>
                </div>

                {expandedSessionsSvc === svc.service ? (
                  <div
                    data-testid={`agent-scanned-list-${svc.service}`}
                    className="mt-2 border-t border-primary-200 pt-2 space-y-1 font-mono text-[11px]"
                  >
                    {(scannedSessions[svc.service] || []).length === 0 ? (
                      <div className="text-primary-500">
                        No sessions found in local store.
                      </div>
                    ) : (
                      (scannedSessions[svc.service] || []).map((s) => (
                        <div
                          key={s.session_id}
                          className="border border-primary-200 px-2 py-1"
                        >
                          <div className="truncate font-semibold">
                            {s.session_id}
                          </div>
                          {s.preview ? (
                            <div className="truncate text-primary-600">
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
        ) : null}

        {tab === 'runs' ? (
          <div
            data-testid="webclaw-runs-list"
            className="flex-1 overflow-y-auto divide-y divide-primary-200"
          >
            {runs.length === 0 ? (
              <div className="p-3 text-primary-500">No agent runs yet.</div>
            ) : (
              runs.map((run) => (
                <div
                  key={run.id}
                  data-testid={`webclaw-run-${run.id}`}
                  className="p-3 space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-semibold">{run.id}</span>
                    <span
                      data-testid={`webclaw-run-state-${run.id}`}
                      className="border border-primary-300 px-1.5 py-0.5 font-mono text-[11px]"
                    >
                      {run.state}
                    </span>
                  </div>
                  <div className="font-mono text-[11px] text-primary-600">
                    {run.service} · {run.model || 'default'}
                    {run.role ? ` · ${run.role}` : ''}
                    {run.metadata?.duration_s !== undefined
                      ? ` · ${run.metadata.duration_s}s`
                      : ''}
                    {run.session_id ? ` · ${run.session_id.slice(0, 14)}` : ''}
                  </div>
                  <div className="truncate text-[11px] text-primary-700">
                    {run.prompt}
                  </div>
                  {run.response_text ? (
                    <pre className="max-h-24 overflow-auto border border-primary-200 p-1.5 font-mono text-[11px] whitespace-pre-wrap">
                      {run.response_text}
                    </pre>
                  ) : null}
                  {run.state === 'running' ? (
                    <button
                      type="button"
                      data-testid={`webclaw-stop-run-${run.id}`}
                      onClick={() => void stopRun(run.id)}
                      className="border border-red-500 px-2 py-0.5 text-red-600"
                    >
                      Stop run
                    </button>
                  ) : null}
                </div>
              ))
            )}
          </div>
        ) : null}

        {tab === 'evolution' ? (
          <div
            data-testid="webclaw-evolution-panel"
            className="flex-1 overflow-y-auto p-3 space-y-3"
          >
            {/* Header + Evolve Action */}
            <div className="flex items-center justify-between gap-2 rounded-lg border border-primary-200 bg-primary-100 p-2.5">
              <div className="min-w-0">
                <div className="font-semibold text-primary-950">
                  PlanAI Evolution Engine · Gen v{activeGen}
                </div>
                <div className="text-[11px] text-primary-600">
                  {evolutionStatus?.bootstrap?.corpus_loaded
                    ? `Bootstrapped from ${evolutionStatus.bootstrap.corpus_total_prompts?.toLocaleString() ?? 0} prompts (${evolutionStatus.bootstrap.corpus_total_sessions ?? 0} sessions)`
                    : 'Learning live from Chief decisions & verification gates'}
                </div>
              </div>
              <button
                type="button"
                data-testid="inspector-evolve-button"
                disabled={evolving}
                onClick={() => void handleRunEvolution()}
                className="shrink-0 rounded-md border border-primary-800 bg-primary-900 px-2.5 py-1.5 font-medium text-surface hover:bg-primary-800 disabled:opacity-40"
              >
                {evolving ? 'Evolving…' : 'Evolve Prompts'}
              </button>
            </div>

            {/* PlanAI LLM Core & Chromium Prompt API Diagnostics */}
            <div
              data-testid="inspector-llm-diagnostics"
              className="rounded-lg border border-primary-200 p-2.5 space-y-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-primary-900">
                  PlanAI LLM Core
                </span>
                <span className="rounded border border-primary-300 px-1.5 py-0.5 font-mono text-[10px]">
                  {llmStatus?.chromium_prompt_bridge?.connected
                    ? 'Chromium Prompt API live'
                    : llmStatus?.local_mlx?.available
                      ? 'Local Metal MLX'
                      : 'Deterministic / Env'}
                </span>
              </div>
              <div className="font-mono text-[11px] text-primary-600 break-words">
                {llmStatus?.status_label || chiefLlmStatus || 'deterministic'}
              </div>
              {llmStatus?.chromium_prompt_bridge ? (
                <div className="text-[11px] text-primary-600">
                  Bridge calls:{' '}
                  {llmStatus.chromium_prompt_bridge.total_bridged_calls ?? 0}
                  {llmStatus.chromium_prompt_bridge.last_call_latency_ms
                    ? ` · last ${llmStatus.chromium_prompt_bridge.last_call_latency_ms}ms`
                    : ''}
                </div>
              ) : null}
            </div>

            {/* Active Prompt Generations */}
            <div className="space-y-1.5">
              <div className="font-semibold text-primary-900">
                Active Prompt Generations
              </div>
              {(
                [
                  evolutionStatus?.active_prompts?.lead_planner,
                  evolutionStatus?.active_prompts?.chief_triage,
                ].filter(Boolean) as Array<PromptVersionInfo>
              ).map((pv) => (
                <div
                  key={pv.id}
                  data-testid={`prompt-version-${pv.worker_role}`}
                  className="rounded-lg border border-primary-200 p-2 space-y-1"
                >
                  <div className="flex items-center justify-between font-mono text-[11px]">
                    <span className="font-semibold text-primary-950">
                      {pv.worker_role} · v{pv.generation}
                    </span>
                    <span className="text-primary-600">
                      pass {pv.pass_count} / fail {pv.fail_count}
                    </span>
                  </div>
                  <div className="text-[11px] text-primary-600">
                    {pv.rationale}
                  </div>
                </div>
              ))}
            </div>

            {/* Service Empirical Fitness */}
            {fitnessRows.length > 0 ? (
              <div className="space-y-1">
                <div className="font-semibold text-primary-900">
                  Measured Agent Fitness
                </div>
                <div className="divide-y divide-primary-200 rounded-lg border border-primary-200">
                  {fitnessRows.map((row) => (
                    <div
                      key={row.service}
                      className="flex items-center justify-between px-2.5 py-1.5 font-mono text-[11px]"
                    >
                      <span>{row.service}</span>
                      <span className="text-primary-600">
                        {row.succeeded_runs}/{row.total_runs} ok
                        {row.pass_rate !== null
                          ? ` (${Math.round(row.pass_rate * 100)}%)`
                          : ''}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Learned Guardrail Rules + Add Rule */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-primary-900">
                  Learned Guardrail Rules ({evolutionStatus?.rules?.length ?? 0})
                </span>
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
                  placeholder="Add persistent planning rule…"
                  className="min-w-0 flex-1 rounded border border-primary-200 bg-primary-50 px-2 py-1 text-[11px] outline-none"
                />
                <button
                  type="submit"
                  disabled={addingRule || !newRuleText.trim()}
                  className="shrink-0 rounded border border-primary-300 bg-primary-100 px-2 py-1 font-medium disabled:opacity-40"
                >
                  + Rule
                </button>
              </form>

              <div className="space-y-1.5 max-h-60 overflow-y-auto">
                {(evolutionStatus?.rules ?? []).map((rule) => (
                  <div
                    key={rule.id}
                    data-testid={`evolution-rule-${rule.id}`}
                    className="rounded border border-primary-200 p-2 text-[11px]"
                  >
                    <div className="flex items-center justify-between font-mono text-[10px] text-primary-600">
                      <span>
                        {rule.category} · {rule.source_type}
                      </span>
                      <span>×{rule.evidence_count}</span>
                    </div>
                    <div className="mt-0.5 text-primary-900">
                      {rule.rule_text}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </aside>
  )
}
