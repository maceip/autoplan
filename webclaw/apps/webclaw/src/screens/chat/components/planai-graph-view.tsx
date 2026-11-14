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

const HUMAN_STAGE_COPY: Record<string, { title: string; summary: string }> = {
  ContextHarvesterWorker: {
    title: 'Read repository & rules',
    summary: 'Inspects git branch, recent commits, and active project guardrails',
  },
  LeadPlannerWorker: {
    title: 'Break goal into tasks',
    summary: 'Splits the goal into non-overlapping tasks per agent',
  },
  SubtaskFanOutWorker: {
    title: 'Prepare isolated branches',
    summary: 'Creates a dedicated git worktree for each parallel agent',
  },
  MultiAgentDispatchWorker: {
    title: 'Run agents in parallel',
    summary: 'Executes assigned agents concurrently without file collisions',
  },
  TeamSynthesisJoiner: {
    title: 'Combine agent changes',
    summary: 'Joins completed branches once all parallel tasks finish',
  },
  VerificationGateWorker: {
    title: 'Run tests & checks',
    summary: 'Runs the project test command and verifies clean diffs',
  },
  ChiefEscalationSink: {
    title: 'Send to review',
    summary: 'Queues the verified change bundle for approval',
  },
  TraceCollectorWorker: {
    title: 'Collect feedback & failures',
    summary: 'Reads recent review notes and failed test runs',
  },
  FailureCritiqueWorker: {
    title: 'Analyze recurring issues',
    summary: 'Identifies what caused bounced reviews or test failures',
  },
  EvolutionCritiqueJoiner: {
    title: 'Combine findings',
    summary: 'Merges planner and review findings into one update',
  },
  PromptMutationWorker: {
    title: 'Refine prompts & rules',
    summary: 'Updates planning instructions with concrete guardrails',
  },
  EvolutionCommitSink: {
    title: 'Save updated rules',
    summary: 'Persists the new prompt version and guardrail rules',
  },
}

const TEAMWORK_BLUEPRINT_NODES: Array<PlanAINode> = [
  {
    id: 'ContextHarvesterWorker',
    label: 'ContextHarvesterWorker',
    worker_type: 'TaskWorker',
    role: HUMAN_STAGE_COPY.ContextHarvesterWorker.summary,
    state: 'idle',
  },
  {
    id: 'LeadPlannerWorker',
    label: 'LeadPlannerWorker',
    worker_type: 'LLMTaskWorker',
    role: HUMAN_STAGE_COPY.LeadPlannerWorker.summary,
    state: 'idle',
  },
  {
    id: 'SubtaskFanOutWorker',
    label: 'SubtaskFanOutWorker',
    worker_type: 'TaskWorker',
    role: HUMAN_STAGE_COPY.SubtaskFanOutWorker.summary,
    state: 'idle',
  },
  {
    id: 'MultiAgentDispatchWorker',
    label: 'MultiAgentDispatchWorker',
    worker_type: 'TaskWorker',
    role: HUMAN_STAGE_COPY.MultiAgentDispatchWorker.summary,
    state: 'idle',
  },
  {
    id: 'TeamSynthesisJoiner',
    label: 'TeamSynthesisJoiner',
    worker_type: 'JoinedTaskWorker',
    role: HUMAN_STAGE_COPY.TeamSynthesisJoiner.summary,
    state: 'idle',
  },
  {
    id: 'VerificationGateWorker',
    label: 'VerificationGateWorker',
    worker_type: 'TaskWorker',
    role: HUMAN_STAGE_COPY.VerificationGateWorker.summary,
    state: 'idle',
  },
  {
    id: 'ChiefEscalationSink',
    label: 'ChiefEscalationSink',
    worker_type: 'TaskWorker',
    role: HUMAN_STAGE_COPY.ChiefEscalationSink.summary,
    state: 'idle',
  },
]

function humanStateLabel(state: PlanAINode['state']): string {
  if (state === 'running') return 'Running'
  if (state === 'succeeded') return 'Done'
  if (state === 'failed') return 'Failed'
  return 'Ready'
}

function stateDotClasses(state: PlanAINode['state']): string {
  if (state === 'running') return 'bg-[#268bd2]'
  if (state === 'succeeded') return 'bg-[#7aae66]'
  if (state === 'failed') return 'bg-red-500'
  return 'bg-primary-400'
}

export function PlanAIGraphView({
  activeProjectId,
  compact = false,
}: PlanAIGraphViewProps) {
  const [workflows, setWorkflows] = useState<Array<PlanAIWorkflow>>([])
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('')
  const [selectedNodeId, setSelectedNodeId] = useState<string>(
    'TeamSynthesisJoiner',
  )
  const [subTab, setSubTab] = useState<'dag' | 'provenance' | 'python'>('dag')
  const [errorMsg, setErrorMsg] = useState('')

  const refreshWorkflows = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ limit: '20' })
      if (activeProjectId) qs.set('project_id', activeProjectId)
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
  }, [activeProjectId])

  useEffect(() => {
    void refreshWorkflows()
    const hasRunning = workflows.some((w) => w.state === 'running')
    const interval = window.setInterval(
      () => {
        void refreshWorkflows()
      },
      hasRunning ? 1500 : 5000,
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
    () =>
      workflows.find((w) => w.id === selectedWorkflowId) ??
      workflows[0] ??
      null,
    [selectedWorkflowId, workflows],
  )

  const displayNodes = activeWorkflow?.nodes?.length
    ? activeWorkflow.nodes
    : TEAMWORK_BLUEPRINT_NODES

  const selectedNode = useMemo(
    () =>
      displayNodes.find((n) => n.id === selectedNodeId) ??
      displayNodes[0] ??
      null,
    [displayNodes, selectedNodeId],
  )

  const nodeEvents = useMemo(() => {
    if (!activeWorkflow?.events?.length || !selectedNode) return []
    return activeWorkflow.events.filter((ev) => ev.node_id === selectedNode.id)
  }, [activeWorkflow, selectedNode])

  return (
    <section
      data-testid="planai-graph-view"
      className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-surface text-xs text-primary-900"
    >
      {/* Single thin 40px action bar — zero stacked toolbars */}
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-primary-200 px-3.5">
        <div className="flex min-w-0 items-center gap-2">
          <select
            aria-label="Select run"
            data-testid="planai-workflow-selector"
            value={activeWorkflow?.id || ''}
            onChange={(e) => setSelectedWorkflowId(e.target.value)}
            className="h-7 max-w-[300px] truncate rounded-md border border-primary-200 bg-primary-100 px-2 text-xs font-medium text-primary-950 outline-none"
          >
            {workflows.length === 0 ? (
              <option value="">Default team pipeline</option>
            ) : (
              workflows.map((wf) => (
                <option key={wf.id} value={wf.id}>
                  {wf.title.slice(0, 48)} · {wf.state}
                </option>
              ))
            )}
          </select>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <div className="flex rounded-md bg-primary-100 p-0.5">
            {(['dag', 'provenance', 'python'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                data-testid={`planai-subtab-${mode}`}
                onClick={() => setSubTab(mode)}
                className={cn(
                  'rounded px-2 py-0.5 text-xs font-medium transition-colors',
                  subTab === mode
                    ? 'bg-surface text-primary-950 shadow-2xs'
                    : 'text-primary-600 hover:text-primary-900',
                )}
              >
                {mode === 'dag'
                  ? 'Steps'
                  : mode === 'provenance'
                    ? 'Lineage'
                    : 'Code'}
              </button>
            ))}
          </div>

          {!compact ? (
            <a
              href={
                activeWorkflow?.id
                  ? `/planai-editor?workflow_id=${encodeURIComponent(activeWorkflow.id)}`
                  : '/planai-editor'
              }
              target="_blank"
              rel="noreferrer"
              data-testid="open-svelteflow-editor-link"
              className="rounded-md px-2 py-1 text-xs text-primary-600 hover:bg-primary-100 hover:text-primary-950"
            >
              Visual editor ↗
            </a>
          ) : null}
        </div>
      </div>

      {errorMsg ? (
        <div
          role="alert"
          className="border-b border-red-500/40 bg-red-500/10 px-3.5 py-1.5 text-red-500"
        >
          {errorMsg}
        </div>
      ) : null}

      <div className="flex flex-1 min-h-0 flex-col overflow-y-auto px-5 py-4">
        {subTab === 'dag' ? (
          <div className="mx-auto w-full max-w-[640px] space-y-4">
            {!activeWorkflow ? (
              <p className="text-xs text-primary-600 text-pretty">
                Switch the chat input to <strong>Team</strong> and send a goal to
                run this pipeline across isolated git worktrees.
              </p>
            ) : null}

            <div data-testid="planai-dag-canvas" className="flex flex-col">
              {displayNodes.map((node, index) => {
                const copy = HUMAN_STAGE_COPY[node.id]
                const title = copy ? copy.title : node.label
                const summary = copy ? copy.summary : node.role
                const isSelected = selectedNode?.id === node.id
                const isLast = index === displayNodes.length - 1
                return (
                  <div key={node.id} className="flex flex-col">
                    <button
                      type="button"
                      data-testid={`planai-node-${node.id}`}
                      onClick={() => setSelectedNodeId(node.id)}
                      className={cn(
                        'flex w-full items-center justify-between gap-3 rounded-lg border px-3.5 py-2.5 text-left transition-colors',
                        isSelected
                          ? 'border-primary-400 bg-primary-100'
                          : 'border-primary-200 bg-primary-100/40 hover:bg-primary-100/80',
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              'size-2 shrink-0 rounded-full',
                              stateDotClasses(node.state),
                            )}
                          />
                          <span className="text-[13px] font-medium text-primary-950">
                            {index + 1}. {title}
                          </span>
                        </div>
                        <div className="mt-0.5 pl-4 text-xs text-primary-600 text-pretty">
                          {summary}
                        </div>
                      </div>

                      <span
                        data-testid={`planai-node-state-${node.id}`}
                        className="shrink-0 text-xs text-primary-600 tabular-nums"
                      >
                        {humanStateLabel(node.state)}
                      </span>
                    </button>

                    {!isLast ? (
                      <div className="pl-6 py-0.5" aria-hidden="true">
                        <div className="h-3 w-px bg-primary-300" />
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>

            {selectedNode ? (
              <div
                data-testid="planai-node-inspector"
                className="rounded-lg border border-primary-200 bg-primary-100/40 px-3.5 py-3 space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-primary-950">
                    {HUMAN_STAGE_COPY[selectedNode.id]?.title ||
                      selectedNode.label}
                  </span>
                  <span className="font-mono text-[11px] text-primary-500">
                    {selectedNode.id}
                  </span>
                </div>
                {nodeEvents.length > 0 ? (
                  <div className="space-y-1 pt-1 text-xs text-primary-800">
                    {nodeEvents.map((ev, idx) => (
                      <div key={`${ev.ts}-${idx}`}>{ev.summary}</div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-primary-600">
                    {HUMAN_STAGE_COPY[selectedNode.id]?.summary ||
                      selectedNode.role}
                  </p>
                )}
              </div>
            ) : null}
          </div>
        ) : null}

        {subTab === 'provenance' ? (
          <div
            data-testid="planai-provenance-panel"
            className="mx-auto w-full max-w-[640px] space-y-2"
          >
            {activeWorkflow?.provenance?.length ? (
              activeWorkflow.provenance.map((chain, idx) => (
                <div
                  key={idx}
                  className="rounded-lg border border-primary-200 bg-primary-100/40 px-3 py-2 font-mono text-xs text-primary-900 break-all"
                >
                  {chain.join(' → ')}
                </div>
              ))
            ) : (
              <p className="text-xs text-primary-600">
                No completed team run selected yet. Run a goal in Team mode to
                view task lineage across stages.
              </p>
            )}
          </div>
        ) : null}

        {subTab === 'python' ? (
          <div
            data-testid="planai-python-panel"
            className="mx-auto w-full max-w-[680px]"
          >
            <pre className="overflow-x-auto rounded-lg border border-primary-200 bg-primary-100/40 p-3.5 font-mono text-xs text-primary-900">
              {activeWorkflow?.python_code ||
                `from planai import Graph, InitialTaskWorker, JoinedTaskWorker, SubGraphWorker\n\n# TeamSynthesisJoiner(JoinedTaskWorker) joins parallel isolated git worktrees\n# once every SubAgentResultTask finishes upstream.`}
            </pre>
          </div>
        ) : null}
      </div>
    </section>
  )
}
