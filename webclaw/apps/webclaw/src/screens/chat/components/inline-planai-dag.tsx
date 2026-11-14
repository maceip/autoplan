import { useCallback, useEffect, useMemo, useState } from 'react'
import type { AgentServiceInfo } from './autoplan-inspector'
import { cn } from '@/lib/utils'

type WorkflowNode = {
  id: string
  label: string
  worker_class?: string
  role: string
  state: string
  lane_index?: number
  total_lanes?: number
  metrics?: Record<string, unknown>
}

type WorkflowEvent = {
  ts: number
  node_id: string
  state: string
  summary?: string
  detail?: string
}

type PlanAIWorkflow = {
  id: string
  project_id: string
  session_key?: string
  graph_type: string
  title: string
  goal: string
  state: string
  nodes: Array<WorkflowNode>
  events: Array<WorkflowEvent>
  provenance: Array<Array<string>>
  created_at: number
}

type DagStage = {
  id: string
  title: string
  subtitle: string
  detail: string
  state: string
}

type InlinePlanAIDagProps = {
  activeProjectId: string
  activeProjectName?: string
  sessionKey?: string
  sessionMode: 'single' | 'team'
  services?: Array<AgentServiceInfo>
  empty?: boolean
  showOnboardingDemo?: boolean
  onStartDemo?: () => void
  startingDemo?: boolean
  canDispatchDemo?: boolean
}

function dotClass(state: string): string {
  if (state === 'running') return 'bg-sky-400 animate-pulse'
  if (state === 'succeeded') return 'bg-emerald-500'
  if (state === 'failed') return 'bg-red-500'
  return 'bg-primary-400'
}

function stateWord(state: string): string {
  if (state === 'running') return 'Running'
  if (state === 'succeeded') return 'Done'
  if (state === 'failed') return 'Failed'
  return 'Ready'
}

function StraightConnector({ active }: { active?: boolean }) {
  return (
    <svg
      viewBox="0 0 28 24"
      className="h-6 w-6 shrink-0 text-primary-300"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M2 12h22m0 0-4-3.5M24 12l-4 3.5"
        stroke="currentColor"
        strokeWidth={active ? 1.8 : 1.3}
        className={active ? 'text-sky-400' : undefined}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function BranchConnector({
  lanes,
  direction,
  active,
}: {
  lanes: number
  direction: 'fanout' | 'fanin'
  active?: boolean
}) {
  const count = Math.max(2, Math.min(lanes, 4))
  const height = count * 46
  const midY = height / 2
  return (
    <svg
      viewBox={`0 0 36 ${height}`}
      style={{ height: `${height}px` }}
      className="w-8 shrink-0 text-primary-300"
      fill="none"
      aria-hidden="true"
    >
      {Array.from({ length: count }).map((_, idx) => {
        const laneY = idx * 46 + 23
        const d =
          direction === 'fanout'
            ? `M 2 ${midY} C 18 ${midY}, 18 ${laneY}, 34 ${laneY}`
            : `M 2 ${laneY} C 18 ${laneY}, 18 ${midY}, 34 ${midY}`
        return (
          <path
            key={idx}
            d={d}
            stroke="currentColor"
            strokeWidth={active ? 1.75 : 1.3}
            className={active ? 'text-sky-400' : undefined}
            strokeLinecap="round"
          />
        )
      })}
    </svg>
  )
}

function StageCard({
  stage,
  selected,
  compact,
  onSelect,
}: {
  stage: DagStage
  selected: boolean
  compact: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      data-testid={`planai-node-${stage.id}`}
      onClick={onSelect}
      className={cn(
        'group flex items-center gap-2 rounded-lg border text-left transition-colors',
        compact ? 'px-2.5 py-1.5' : 'px-3 py-2',
        selected
          ? 'border-primary-500 bg-primary-100'
          : 'border-primary-200 bg-primary-100/45 hover:border-primary-300 hover:bg-primary-100/80',
      )}
    >
      <span
        className={cn('size-2 shrink-0 rounded-full', dotClass(stage.state))}
      />
      <div className="min-w-0">
        <div className="truncate text-xs font-medium text-primary-950">
          {stage.title}
        </div>
        <div
          data-testid={`planai-node-state-${stage.id}`}
          className="truncate text-[11px] text-primary-600 tabular-nums"
        >
          {stage.subtitle}
        </div>
      </div>
    </button>
  )
}

export function InlinePlanAIDag({
  activeProjectId,
  activeProjectName = '',
  sessionKey = '',
  sessionMode,
  services = [],
  empty = false,
  showOnboardingDemo = false,
  onStartDemo,
  startingDemo = false,
  canDispatchDemo = true,
}: InlinePlanAIDagProps) {
  const [workflows, setWorkflows] = useState<Array<PlanAIWorkflow>>([])
  const [selectedStageId, setSelectedStageId] = useState<string>('')

  const refreshWorkflows = useCallback(async () => {
    try {
      const qs = activeProjectId
        ? `?project_id=${encodeURIComponent(activeProjectId)}&limit=20`
        : '?limit=20'
      const res = await fetch(`/api/autoplan/planai/workflows${qs}`)
      if (!res.ok) return
      const data = (await res.json()) as {
        workflows?: Array<PlanAIWorkflow>
      }
      setWorkflows(data.workflows || [])
    } catch {
      // ignore transient poll errors
    }
  }, [activeProjectId])

  const activeWorkflow = useMemo(() => {
    if (!sessionKey || sessionKey === 'new') return null
    const forSession = workflows.filter((w) => w.session_key === sessionKey)
    if (forSession.length > 0) return forSession[0]
    return null
  }, [sessionKey, workflows])

  useEffect(() => {
    void refreshWorkflows()
    const isRunning = activeWorkflow?.state === 'running'
    const interval = window.setInterval(
      () => {
        void refreshWorkflows()
      },
      isRunning ? 1500 : 6000,
    )
    const onLiveEvent = () => {
      void refreshWorkflows()
    }
    window.addEventListener('autoplan:event', onLiveEvent)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('autoplan:event', onLiveEvent)
    }
  }, [activeWorkflow?.state, refreshWorkflows])

  const showTeamTopology =
    activeWorkflow?.graph_type === 'teamwork' ||
    (!activeWorkflow && sessionMode === 'team')

  const { leadStages, branchStages, tailStages } = useMemo(() => {
    if (!showTeamTopology) {
      const byId = new Map(
        (activeWorkflow?.nodes || []).map((n) => [n.id, n] as const),
      )
      const runner = byId.get('WorktreeRunner')
      const verify = byId.get('VerificationGate')
      const review = byId.get('ChiefReviewSink')
      const singleStages: Array<DagStage> = [
        {
          id: 'WorktreeRunner',
          title: runner?.label || 'Run in branch',
          subtitle: runner ? stateWord(runner.state) : 'Isolated worktree',
          detail:
            runner?.role ||
            'Runs the selected agent inside an isolated git worktree branch so your working tree stays clean.',
          state: runner?.state || 'idle',
        },
        {
          id: 'VerificationGate',
          title: 'Run tests',
          subtitle: verify ? stateWord(verify.state) : 'Project checks',
          detail:
            verify?.role ||
            'Executes the project test command and checks diffs before anything can land.',
          state: verify?.state || 'idle',
        },
        {
          id: 'ChiefReviewSink',
          title: 'Review',
          subtitle: review ? stateWord(review.state) : 'Approve to merge',
          detail:
            'Queues the verified branch in the right-hand Review panel for 1-click approval and merge.',
          state: review?.state || 'idle',
        },
      ]
      return {
        leadStages: singleStages,
        branchStages: [] as Array<DagStage>,
        tailStages: [] as Array<DagStage>,
      }
    }

    const byId = new Map(
      (activeWorkflow?.nodes || []).map((n) => [n.id, n] as const),
    )
    const ctxNode = byId.get('ContextHarvesterWorker')
    const planNode = byId.get('LeadPlannerWorker')
    const fanoutNode = byId.get('SubtaskFanOutWorker')
    const dispatchNode = byId.get('MultiAgentDispatchWorker')
    const joinNode = byId.get('TeamSynthesisJoiner')
    const verifyNode = byId.get('VerificationGateWorker')
    const sinkNode = byId.get('ChiefEscalationSink')

    const dynamicLanes = (activeWorkflow?.nodes || []).filter((n) =>
      n.id.startsWith('subagent_'),
    )

    let lanes: Array<DagStage>
    if (dynamicLanes.length > 0) {
      lanes = dynamicLanes.map((lane) => ({
        id: lane.id,
        title: lane.label,
        subtitle: `${lane.role} · ${stateWord(lane.state)}`,
        detail: `Parallel isolated git worktree (${String(lane.metrics?.branch || lane.role)}).`,
        state: lane.state,
      }))
    } else {
      const ready = services.filter((s) => s.dispatch_ready)
      const fallbackServices =
        ready.length >= 2
          ? ready.slice(0, 3)
          : [
              { display_name: 'Agent 1', service: 'agent-1' },
              { display_name: 'Agent 2', service: 'agent-2' },
            ]
      lanes = fallbackServices.map((svc, idx) => ({
        id: `subagent_${idx + 1}`,
        title: svc.display_name,
        subtitle: dispatchNode
          ? stateWord(dispatchNode.state)
          : `Worktree ${idx + 1}`,
        detail: `Executes its assigned file scope in an isolated git worktree without colliding with sibling agents.`,
        state: dispatchNode?.state || 'idle',
      }))
    }

    const planState =
      planNode?.state === 'running' || fanoutNode?.state === 'running'
        ? 'running'
        : planNode?.state || ctxNode?.state || 'idle'

    const joinAndTestState =
      joinNode?.state === 'running' || verifyNode?.state === 'running'
        ? 'running'
        : verifyNode?.state && verifyNode.state !== 'idle'
          ? verifyNode.state
          : joinNode?.state || 'idle'

    return {
      leadStages: [
        {
          id: 'ContextHarvesterWorker',
          title: 'Read repo',
          subtitle: ctxNode ? stateWord(ctxNode.state) : 'Rules & git',
          detail:
            'Reads repository structure, recent commits, empirical agent pass rates, and active Project Guardrails.',
          state: ctxNode?.state || 'idle',
        },
        {
          id: 'LeadPlannerWorker',
          title: 'Split goal',
          subtitle: planNode ? stateWord(planState) : 'SubGraphWorker',
          detail:
            'PlanAI LeadPlanningSubGraph decomposes your goal into non-overlapping file scopes per agent.',
          state: planState,
        },
      ],
      branchStages: lanes,
      tailStages: [
        {
          id: 'TeamSynthesisJoiner',
          title: 'Join & test',
          subtitle: joinNode
            ? stateWord(joinAndTestState)
            : 'JoinedTaskWorker',
          detail:
            'PlanAI TeamSynthesisJoiner waits for all parallel worktrees via ProvenanceChain, merges branches, and runs project tests.',
          state: joinAndTestState,
        },
        {
          id: 'ChiefEscalationSink',
          title: 'Review',
          subtitle: sinkNode ? stateWord(sinkNode.state) : 'Approve to merge',
          detail:
            'Sends the verified multi-agent bundle to the Review panel for approval.',
          state: sinkNode?.state || 'idle',
        },
      ],
    }
  }, [activeWorkflow, services, showTeamTopology])

  const allStages = useMemo(
    () => [...leadStages, ...branchStages, ...tailStages],
    [branchStages, leadStages, tailStages],
  )

  const selectedStage = useMemo(
    () => allStages.find((s) => s.id === selectedStageId) ?? null,
    [allStages, selectedStageId],
  )

  const stageEvents = useMemo(() => {
    if (!activeWorkflow?.events?.length || !selectedStage) return []
    return activeWorkflow.events.filter(
      (ev) => ev.node_id === selectedStage.id,
    )
  }, [activeWorkflow, selectedStage])

  const toggleStage = (id: string) => {
    setSelectedStageId((prev) => (prev === id ? '' : id))
  }

  const dagDiagram = (
    <div
      data-testid="planai-dag-canvas"
      className="flex items-center overflow-x-auto py-1"
    >
      {leadStages.map((st, idx) => (
        <div key={st.id} className="flex items-center shrink-0">
          <StageCard
            stage={st}
            selected={selectedStage?.id === st.id}
            compact={!empty}
            onSelect={() => toggleStage(st.id)}
          />
          {idx < leadStages.length - 1 ? (
            <StraightConnector active={st.state === 'running'} />
          ) : null}
        </div>
      ))}

      {branchStages.length > 0 ? (
        <>
          <BranchConnector
            lanes={branchStages.length}
            direction="fanout"
            active={branchStages.some((b) => b.state === 'running')}
          />
          <div className="flex flex-col gap-1.5 shrink-0">
            {branchStages.map((lane) => (
              <StageCard
                key={lane.id}
                stage={lane}
                selected={selectedStage?.id === lane.id}
                compact={!empty}
                onSelect={() => toggleStage(lane.id)}
              />
            ))}
          </div>
          <BranchConnector
            lanes={branchStages.length}
            direction="fanin"
            active={tailStages[0]?.state === 'running'}
          />
          {tailStages.map((st, idx) => (
            <div key={st.id} className="flex items-center shrink-0">
              <StageCard
                stage={st}
                selected={selectedStage?.id === st.id}
                compact={!empty}
                onSelect={() => toggleStage(st.id)}
              />
              {idx < tailStages.length - 1 ? (
                <StraightConnector active={st.state === 'running'} />
              ) : null}
            </div>
          ))}
        </>
      ) : null}
    </div>
  )

  const detailDrawer = selectedStage ? (
    <div
      data-testid="planai-node-inspector"
      className="mt-2 flex items-start justify-between gap-3 rounded-lg border border-primary-200 bg-primary-100/55 px-3 py-2 text-xs"
    >
      <div className="min-w-0 space-y-1">
        <div className="font-medium text-primary-950">
          {selectedStage.title}{' '}
          <span className="font-mono text-[11px] font-normal text-primary-500">
            {selectedStage.id}
          </span>
        </div>
        {stageEvents.length > 0 ? (
          <div className="space-y-0.5 text-primary-800">
            {stageEvents.slice(-3).map((ev, i) => (
              <div key={`${ev.ts}-${i}`}>{ev.summary || ev.detail}</div>
            ))}
          </div>
        ) : (
          <p className="text-primary-600 text-pretty">{selectedStage.detail}</p>
        )}
      </div>
      <button
        type="button"
        aria-label="Close stage details"
        onClick={() => setSelectedStageId('')}
        className="shrink-0 rounded px-1.5 py-0.5 text-primary-500 hover:bg-primary-200 hover:text-primary-900"
      >
        ×
      </button>
    </div>
  ) : null

  if (empty) {
    return (
      <section
        data-testid="planai-graph-view"
        className="flex flex-1 min-h-0 flex-col items-center justify-center px-6 py-6 select-none"
      >
        <div className="flex max-w-full flex-col items-center gap-3">
          <div className="text-xs text-primary-600">
            {activeProjectName ? `${activeProjectName} · ` : ''}
            {showTeamTopology
              ? 'Parallel multi-agent git worktree workflow'
              : 'Isolated git worktree workflow'}
          </div>
          {dagDiagram}
          {detailDrawer ? (
            <div className="w-full max-w-[620px]">{detailDrawer}</div>
          ) : null}
          {showOnboardingDemo && onStartDemo ? (
            <button
              type="button"
              data-testid="start-demo-button"
              disabled={!canDispatchDemo || startingDemo}
              onClick={onStartDemo}
              className="mt-1 rounded-md border border-primary-200 bg-primary-100/60 px-3 py-1 text-xs text-primary-700 hover:bg-primary-100 hover:text-primary-950 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {startingDemo ? 'Starting demo…' : 'Start Demo'}
            </button>
          ) : null}
        </div>
      </section>
    )
  }

  return (
    <section
      data-testid="planai-graph-view"
      className="shrink-0 border-b border-primary-200 bg-surface px-4 py-2 select-none"
    >
      <div className="mx-auto flex max-w-[920px] flex-col">
        {dagDiagram}
        {detailDrawer}
      </div>
    </section>
  )
}
