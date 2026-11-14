import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ProjectInfo } from '../types'
import { cn } from '@/lib/utils'

export type PlanAINode = {
  id: string
  label: string
  worker_type: string
  svelte_type?: string
  role: string
  state: 'idle' | 'running' | 'succeeded' | 'failed'
  position?: { x: number; y: number }
  metrics?: Record<string, unknown>
}

export type PlanAIEdge = {
  id: string
  source: string
  target: string
  task_type: string
  active?: boolean
}

export type PlanAIWorkflowEvent = {
  ts: number
  node_id: string
  state: string
  summary: string
}

export type PlanAIWorkflow = {
  id: string
  project_id: string
  session_key: string
  graph_type: 'teamwork' | 'evolution' | string
  title: string
  goal: string
  state: 'running' | 'succeeded' | 'failed' | 'stopped'
  nodes: Array<PlanAINode>
  edges: Array<PlanAIEdge>
  events: Array<PlanAIWorkflowEvent>
  provenance: Array<Array<string>>
  result: Record<string, unknown>
  python_code: string
  evolution_gen: number
  queue_item_id?: string
  created_at: number
  updated_at: number
  finished_at: number | null
}

type PlanAIGraphViewProps = {
  activeProjectId: string
  projects: Array<ProjectInfo>
  sessionKey?: string
  compact?: boolean
  onWorkflowLaunched?: (workflowId: string) => void
}

const TEAMWORK_BLUEPRINT_NODES: Array<PlanAINode> = [
  {
    id: 'ContextHarvesterWorker',
    label: 'ContextHarvesterWorker',
    worker_type: 'TaskWorker (SubGraph)',
    role: 'Reads target project git state, branch, learned Brain rules & service fitness',
    state: 'idle',
  },
  {
    id: 'LeadPlannerWorker',
    label: 'LeadPlannerWorker',
    worker_type: 'LLMTaskWorker (SubGraph)',
    role: 'Decomposes goal into disjoint multi-agent roles using evolved prompt',
    state: 'idle',
  },
  {
    id: 'SubtaskFanOutWorker',
    label: 'SubtaskFanOutWorker',
    worker_type: 'TaskWorker',
    role: 'Publishes N typed SubAgentDirectiveTasks in parallel',
    state: 'idle',
  },
  {
    id: 'MultiAgentDispatchWorker',
    label: 'MultiAgentDispatchWorker',
    worker_type: 'TaskWorker (x3 parallel)',
    role: 'Executes real agents (Antigravity / MiMo / MiniMax) in isolated git worktrees',
    state: 'idle',
  },
  {
    id: 'TeamSynthesisJoiner',
    label: 'TeamSynthesisJoiner',
    worker_type: 'JoinedTaskWorker',
    role: 'Joins all parallel SubAgentResultTasks by ProvenanceChain & merges worktrees',
    state: 'idle',
  },
  {
    id: 'VerificationGateWorker',
    label: 'VerificationGateWorker',
    worker_type: 'TaskWorker',
    role: 'Runs project test_command + Law-2 Reality Scan + Secret Scan',
    state: 'idle',
  },
  {
    id: 'ChiefEscalationSink',
    label: 'ChiefEscalationSink',
    worker_type: 'TaskWorker',
    role: 'Submits verified bundle to Chief Queue & feeds EvolutionEngine',
    state: 'idle',
  },
]

const TEAMWORK_BLUEPRINT_EDGES: Array<PlanAIEdge> = [
  {
    id: 'e_ctx_plan',
    source: 'ContextHarvesterWorker',
    target: 'LeadPlannerWorker',
    task_type: 'ProjectContextTask',
  },
  {
    id: 'e_plan_fanout',
    source: 'LeadPlannerWorker',
    target: 'SubtaskFanOutWorker',
    task_type: 'TeamPlanTask',
  },
  {
    id: 'e_fanout_exec',
    source: 'SubtaskFanOutWorker',
    target: 'MultiAgentDispatchWorker',
    task_type: 'SubAgentDirectiveTask',
  },
  {
    id: 'e_exec_join',
    source: 'MultiAgentDispatchWorker',
    target: 'TeamSynthesisJoiner',
    task_type: 'SubAgentResultTask',
  },
  {
    id: 'e_join_gate',
    source: 'TeamSynthesisJoiner',
    target: 'VerificationGateWorker',
    task_type: 'JoinedTeamSynthesisTask',
  },
  {
    id: 'e_gate_sink',
    source: 'VerificationGateWorker',
    target: 'ChiefEscalationSink',
    task_type: 'VerifiedTeamBundleTask',
  },
]

function nodeToneClasses(state: PlanAINode['state'], selected: boolean): string {
  if (state === 'running') {
    return selected
      ? 'border-[#268bd2] bg-[#268bd2]/20 ring-1 ring-[#268bd2]'
      : 'border-[#268bd2]/80 bg-[#268bd2]/10'
  }
  if (state === 'succeeded') {
    return selected
      ? 'border-[#7aae66] bg-[#7aae66]/15 ring-1 ring-[#7aae66]'
      : 'border-[#7aae66]/60 bg-primary-100'
  }
  if (state === 'failed') {
    return selected
      ? 'border-red-500 bg-red-500/15 ring-1 ring-red-500'
      : 'border-red-500/60 bg-red-500/10'
  }
  return selected
    ? 'border-primary-400 bg-primary-100 ring-1 ring-primary-400'
    : 'border-primary-200 bg-primary-100/70'
}

function stateDotClasses(state: PlanAINode['state']): string {
  if (state === 'running') return 'bg-[#268bd2] animate-pulse'
  if (state === 'succeeded') return 'bg-[#7aae66]'
  if (state === 'failed') return 'bg-red-500'
  return 'bg-primary-400'
}

export function PlanAIGraphView({
  activeProjectId,
  projects,
  sessionKey = '',
  compact = false,
  onWorkflowLaunched,
}: PlanAIGraphViewProps) {
  const [workflows, setWorkflows] = useState<Array<PlanAIWorkflow>>([])
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('')
  const [selectedNodeId, setSelectedNodeId] = useState<string>(
    'TeamSynthesisJoiner',
  )
  const [subTab, setSubTab] = useState<'dag' | 'provenance' | 'python'>('dag')
  const [projectFilter, setProjectFilter] = useState<string>('')
  const [teamGoal, setTeamGoal] = useState<string>('')
  const [launchingTeam, setLaunchingTeam] = useState(false)
  const [evolving, setEvolving] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const refreshWorkflows = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ limit: '25' })
      if (projectFilter) qs.set('project_id', projectFilter)
      const res = await fetch(`/api/autoplan/planai/workflows?${qs.toString()}`)
      const payload = (await res.json()) as {
        success?: boolean
        workflows?: Array<PlanAIWorkflow>
        error?: string
      }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Workflows HTTP ${res.status}`)
      }
      const list = payload.workflows || []
      setWorkflows(list)
      setSelectedWorkflowId((prev) => {
        if (prev && list.some((w) => w.id === prev)) return prev
        return list[0]?.id || ''
      })
      setErrorMsg('')
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    }
  }, [projectFilter])

  useEffect(() => {
    void refreshWorkflows()
    const hasRunning = workflows.some((w) => w.state === 'running')
    const interval = window.setInterval(
      () => {
        void refreshWorkflows()
      },
      hasRunning ? 1200 : 4000,
    )
    const onLiveEvent = () => {
      void refreshWorkflows()
    }
    window.addEventListener('autoplan:event', onLiveEvent)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('autoplan:event', onLiveEvent)
    }
  }, [refreshWorkflows, workflows])

  const activeWorkflow = useMemo(
    () => workflows.find((w) => w.id === selectedWorkflowId) ?? workflows[0] ?? null,
    [selectedWorkflowId, workflows],
  )

  const displayNodes = activeWorkflow?.nodes?.length
    ? activeWorkflow.nodes
    : TEAMWORK_BLUEPRINT_NODES
  const displayEdges = activeWorkflow?.edges?.length
    ? activeWorkflow.edges
    : TEAMWORK_BLUEPRINT_EDGES

  const selectedNode = useMemo(
    () =>
      displayNodes.find((n) => n.id === selectedNodeId) ??
      displayNodes[0] ??
      null,
    [displayNodes, selectedNodeId],
  )

  async function handleLaunchTeamwork() {
    const clean = teamGoal.trim()
    if (!clean || launchingTeam) return
    setLaunchingTeam(true)
    setErrorMsg('')
    try {
      const targetProj = projectFilter || activeProjectId
      const res = await fetch('/api/autoplan/planai/teamwork', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          goal: clean,
          project_id: targetProj,
          session_key: sessionKey,
        }),
      })
      const payload = (await res.json()) as {
        success?: boolean
        workflow?: PlanAIWorkflow
        error?: string
      }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Teamwork HTTP ${res.status}`)
      }
      setTeamGoal('')
      if (payload.workflow?.id) {
        setSelectedWorkflowId(payload.workflow.id)
        onWorkflowLaunched?.(payload.workflow.id)
      }
      await refreshWorkflows()
      window.dispatchEvent(new CustomEvent('autoplan:event'))
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setLaunchingTeam(false)
    }
  }

  async function handleRunEvolution() {
    if (evolving) return
    setEvolving(true)
    setErrorMsg('')
    try {
      const res = await fetch('/api/autoplan/evolution/evolve', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          project_id: projectFilter || activeProjectId || '*',
          reason: 'graph_view_trigger',
        }),
      })
      const payload = (await res.json()) as {
        success?: boolean
        workflow?: PlanAIWorkflow
        error?: string
      }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Evolution HTTP ${res.status}`)
      }
      if (payload.workflow?.id) {
        setSelectedWorkflowId(payload.workflow.id)
      }
      await refreshWorkflows()
      window.dispatchEvent(new CustomEvent('autoplan:event'))
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setEvolving(false)
    }
  }

  return (
    <section
      data-testid="planai-graph-view"
      className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-surface text-xs text-primary-900"
    >
      {/* Top PlanAI Graph Control Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-primary-200 bg-primary-100/70 px-3 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-primary-700">
            PlanAI DAG
          </span>

          <select
            aria-label="Filter workflows by project"
            data-testid="planai-project-filter"
            value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value)}
            className="h-7 rounded-md border border-primary-300 bg-surface px-2 text-xs text-primary-900"
          >
            <option value="">All projects ({projects.length})</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          <select
            aria-label="Select PlanAI workflow execution"
            data-testid="planai-workflow-selector"
            value={activeWorkflow?.id || ''}
            onChange={(e) => setSelectedWorkflowId(e.target.value)}
            className="h-7 max-w-[280px] truncate rounded-md border border-primary-300 bg-surface px-2 text-xs text-primary-950"
          >
            {workflows.length === 0 ? (
              <option value="">
                Blueprint · MultiAgentTeamworkGraph (no runs yet)
              </option>
            ) : (
              workflows.map((wf) => (
                <option key={wf.id} value={wf.id}>
                  [{wf.state}] {wf.graph_type === 'evolution' ? 'Evolution' : 'Team'} ·{' '}
                  {wf.title.slice(0, 44)} (Gen v{wf.evolution_gen})
                </option>
              ))
            )}
          </select>

          {activeWorkflow ? (
            <span
              data-testid="planai-workflow-state-badge"
              className={cn(
                'rounded-md border px-2 py-0.5 font-mono text-[11px]',
                activeWorkflow.state === 'running'
                  ? 'border-[#268bd2] bg-[#268bd2]/15 text-primary-950'
                  : activeWorkflow.state === 'succeeded'
                    ? 'border-[#7aae66]/60 bg-[#7aae66]/15 text-primary-950'
                    : 'border-red-500/60 bg-red-500/15 text-red-400',
              )}
            >
              {activeWorkflow.state} · Gen v{activeWorkflow.evolution_gen}
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          <div className="flex rounded-md border border-primary-200 bg-surface p-0.5">
            {(['dag', 'provenance', 'python'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                data-testid={`planai-subtab-${mode}`}
                onClick={() => setSubTab(mode)}
                className={cn(
                  'rounded px-2 py-0.5 text-[11px] font-medium transition-colors',
                  subTab === mode
                    ? 'bg-primary-200 text-primary-950'
                    : 'text-primary-600 hover:text-primary-900',
                )}
              >
                {mode === 'dag'
                  ? 'Live Graph'
                  : mode === 'provenance'
                    ? 'Provenance'
                    : 'Python'}
              </button>
            ))}
          </div>

          <button
            type="button"
            data-testid="planai-run-evolution-btn"
            disabled={evolving}
            onClick={() => void handleRunEvolution()}
            className="h-7 rounded-md border border-primary-300 bg-surface px-2.5 text-[11px] font-medium text-primary-950 hover:bg-primary-200 disabled:opacity-40"
          >
            {evolving ? 'Evolving…' : 'Evolve Prompts'}
          </button>

          {!compact ? (
            <a
              href="/planai-editor"
              target="_blank"
              rel="noreferrer"
              data-testid="open-svelteflow-editor-link"
              className="flex h-7 items-center rounded-md border border-primary-300 bg-surface px-2.5 text-[11px] font-medium text-primary-800 hover:bg-primary-200 hover:text-primary-950"
            >
              SvelteFlow Editor ↗
            </a>
          ) : null}
        </div>
      </div>

      {/* Inline Multi-Agent Teamwork Goal Launcher */}
      <div className="flex items-center gap-2 border-b border-primary-200 px-3 py-2">
        <input
          type="text"
          data-testid="planai-team-goal-input"
          value={teamGoal}
          onChange={(e) => setTeamGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void handleLaunchTeamwork()
            }
          }}
          placeholder="Dispatch multi-agent PlanAI Team Graph goal (isolated git worktrees + JoinedTaskWorker synthesis)…"
          className="h-8 min-w-0 flex-1 rounded-lg border border-primary-300 bg-primary-100 px-3 text-xs text-primary-950 placeholder:text-primary-500 outline-none focus:border-[#268bd2]"
        />
        <button
          type="button"
          data-testid="planai-launch-team-btn"
          disabled={!teamGoal.trim() || launchingTeam}
          onClick={() => void handleLaunchTeamwork()}
          className="h-8 shrink-0 rounded-lg border border-[#268bd2]/60 bg-[#268bd2]/20 px-3 text-xs font-semibold text-primary-950 hover:bg-[#268bd2]/30 disabled:opacity-40"
        >
          {launchingTeam ? 'Running Graph…' : 'Launch Team Graph'}
        </button>
      </div>

      {errorMsg ? (
        <div
          role="alert"
          className="border-b border-red-500/40 bg-red-500/10 px-3 py-1.5 text-red-400"
        >
          {errorMsg}
        </div>
      ) : null}

      {/* Main Canvas Body */}
      <div className="flex flex-1 min-h-0 flex-col overflow-y-auto p-3 gap-3">
        {subTab === 'dag' ? (
          <>
            {/* Nested SubGraph Banner when viewing Teamwork Graph */}
            {(!activeWorkflow || activeWorkflow.graph_type === 'teamwork') && (
              <div className="flex items-center justify-between rounded-lg border border-dashed border-primary-300 bg-primary-100/40 px-3 py-1.5 text-[11px] text-primary-700">
                <span>
                  <strong className="text-primary-900">SubGraphWorker:</strong>{' '}
                  <code>LeadPlanningSubGraph</code> wraps{' '}
                  <code>ContextHarvesterWorker → LeadPlannerWorker</code>, then
                  fans out to parallel git worktrees and joins at{' '}
                  <code>TeamSynthesisJoiner (JoinedTaskWorker)</code>.
                </span>
                <span className="font-mono text-[10px] text-primary-600">
                  {displayNodes.length} workers · {displayEdges.length} typed Task edges
                </span>
              </div>
            )}

            {/* Interactive DAG Pipeline Flow */}
            <div
              data-testid="planai-dag-canvas"
              className="flex flex-col gap-1.5 rounded-xl border border-primary-200 bg-primary-100/30 p-3"
            >
              {displayNodes.map((node, index) => {
                const outgoingEdge = displayEdges.find(
                  (e) => e.source === node.id,
                )
                const isSelected = selectedNode?.id === node.id
                const metricEntries = Object.entries(node.metrics || {})
                return (
                  <div key={node.id} className="flex flex-col items-stretch">
                    <button
                      type="button"
                      data-testid={`planai-node-${node.id}`}
                      onClick={() => setSelectedNodeId(node.id)}
                      className={cn(
                        'flex w-full items-start justify-between gap-3 rounded-xl border p-3 text-left transition-colors',
                        nodeToneClasses(node.state, isSelected),
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={cn(
                              'size-2.5 shrink-0 rounded-full',
                              stateDotClasses(node.state),
                            )}
                          />
                          <span className="font-mono text-[12px] font-semibold text-primary-950">
                            {index + 1}. {node.label}
                          </span>
                          <span className="rounded border border-primary-300 bg-surface px-1.5 py-px font-mono text-[10px] text-primary-700">
                            {node.worker_type}
                          </span>
                        </div>
                        <div className="mt-1 text-[11px] text-primary-700">
                          {node.role}
                        </div>
                        {metricEntries.length > 0 ? (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {metricEntries.map(([k, v]) => (
                              <span
                                key={k}
                                className="rounded bg-surface px-1.5 py-0.5 font-mono text-[10px] text-primary-800"
                              >
                                {k}: {String(v)}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </div>

                      <span
                        data-testid={`planai-node-state-${node.id}`}
                        className="shrink-0 rounded border border-primary-300 bg-surface px-2 py-0.5 font-mono text-[10px] uppercase text-primary-800"
                      >
                        {node.state}
                      </span>
                    </button>

                    {outgoingEdge ? (
                      <div className="flex items-center gap-2 pl-6 py-1 font-mono text-[10px] text-primary-600">
                        <span
                          className={cn(
                            'inline-block h-3.5 w-0.5',
                            outgoingEdge.active
                              ? 'bg-[#268bd2] animate-pulse'
                              : 'bg-primary-300',
                          )}
                        />
                        <span>↓ publishes</span>
                        <code className="rounded border border-primary-200 bg-surface px-1.5 py-px text-primary-900">
                          {outgoingEdge.task_type}
                        </code>
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>

            {/* Selected Node & Execution Event Log */}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div
                data-testid="planai-node-inspector"
                className="rounded-xl border border-primary-200 bg-primary-100/50 p-3 space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-semibold text-primary-950">
                    {selectedNode?.label || 'Worker Inspector'}
                  </span>
                  <span className="font-mono text-[11px] text-primary-600">
                    {selectedNode?.worker_type}
                  </span>
                </div>
                <p className="text-[11px] text-primary-700">
                  {selectedNode?.role}
                </p>
                {activeWorkflow?.queue_item_id ? (
                  <div className="pt-1 font-mono text-[11px] text-primary-800">
                    Escalated Queue Item:{' '}
                    <code>{activeWorkflow.queue_item_id}</code>
                  </div>
                ) : null}
              </div>

              <div
                data-testid="planai-event-timeline"
                className="rounded-xl border border-primary-200 bg-primary-100/50 p-3"
              >
                <div className="mb-1.5 font-mono text-xs font-semibold text-primary-950">
                  Real-Time Worker Execution Trace (
                  {activeWorkflow?.events?.length ?? 0})
                </div>
                {activeWorkflow?.events?.length ? (
                  <div className="max-h-36 space-y-1 overflow-y-auto font-mono text-[11px]">
                    {activeWorkflow.events.map((ev, idx) => (
                      <div
                        key={`${ev.ts}-${idx}`}
                        className="flex items-baseline justify-between gap-2 border-b border-primary-200/60 pb-1"
                      >
                        <span className="truncate text-primary-800">
                          <strong>{ev.node_id}</strong>: {ev.summary}
                        </span>
                        <span className="shrink-0 text-[10px] text-primary-600">
                          {ev.state}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11px] text-primary-600">
                    No execution trace recorded yet. Launch a Team Graph or run
                    Evolve Prompts above to stream live PlanAI worker events.
                  </div>
                )}
              </div>
            </div>
          </>
        ) : null}

        {subTab === 'provenance' ? (
          <div
            data-testid="planai-provenance-panel"
            className="rounded-xl border border-primary-200 bg-primary-100/50 p-3 space-y-2"
          >
            <div className="font-mono text-xs font-semibold text-primary-950">
              PlanAI ProvenanceChain Lineage (
              {activeWorkflow?.provenance?.length ?? 0} chains)
            </div>
            <p className="text-[11px] text-primary-700">
              PlanAI tracks every task&apos;s upstream{' '}
              <code>(WorkerName, TaskID)</code> tuple chain so{' '}
              <code>JoinedTaskWorker</code> deterministically joins parallel
              sub-agent branches once all upstream siblings complete.
            </p>
            {activeWorkflow?.provenance?.length ? (
              <div className="space-y-1.5 font-mono text-[11px]">
                {activeWorkflow.provenance.map((chain, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-primary-200 bg-surface p-2 text-primary-900 break-all"
                  >
                    {chain.join(' ──▶ ')}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-primary-600">
                Run a PlanAI workflow to inspect live ProvenanceChain tuples.
              </div>
            )}
          </div>
        ) : null}

        {subTab === 'python' ? (
          <div
            data-testid="planai-python-panel"
            className="rounded-xl border border-primary-200 bg-primary-100/50 p-3 space-y-2"
          >
            <div className="font-mono text-xs font-semibold text-primary-950">
              Executable PlanAI Graph Definition (Python)
            </div>
            <pre className="overflow-x-auto rounded-lg border border-primary-200 bg-surface p-3 font-mono text-[11px] text-primary-900">
              {activeWorkflow?.python_code ||
                `from planai import Graph, InitialTaskWorker, JoinedTaskWorker, SubGraphWorker\n# Select or launch a workflow to view its exact PlanAI Python graph source.`}
            </pre>
          </div>
        ) : null}
      </div>
    </section>
  )
}
