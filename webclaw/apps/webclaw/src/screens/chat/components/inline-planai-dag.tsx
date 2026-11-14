import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import dagre from '@dagrejs/dagre'
import type { AgentServiceInfo } from './autoplan-inspector'
import { cn } from '@/lib/utils'

type NodeKind = 'agent' | 'deterministic' | 'human_gate' | 'terminal'

type WorkflowNode = {
  id: string
  label: string
  kind?: NodeKind
  worker_class?: string
  worker_type?: string
  role: string
  state: string
  lane_index?: number
  total_lanes?: number
  metrics?: Record<string, unknown>
}

type WorkflowEdge = {
  id: string
  source: string
  target: string
  label?: string
  task_type?: string
  active?: boolean
  is_back_edge?: boolean
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
  round?: number
  max_rounds?: number
  current_state?: string
  visit_counts?: Record<string, number>
  nodes: Array<WorkflowNode>
  edges: Array<WorkflowEdge>
  events: Array<WorkflowEvent>
  provenance: Array<unknown>
  result?: Record<string, unknown>
  created_at: number
}

type WorkflowQueueItemInfo = {
  id: string
  title: string
  body: string
  status: string
  branch: string
  target_branch: string
  repo_path: string
  test_command: string
  result?: Record<string, unknown>
}

type WorkflowDetailPayload = {
  success: boolean
  workflow?: PlanAIWorkflow
  item?: WorkflowQueueItemInfo | null
  queue_item?: WorkflowQueueItemInfo | null
  runs?: Array<{
    id: string
    service: string
    model: string
    state: string
    round?: number
    response_text?: string
  }>
  changed_files?: Array<string>
  diff_text?: string
  test_report?: {
    configured?: boolean
    command?: string
    exit_code?: number
    passed?: boolean
    stdout_tail?: string
    stderr_tail?: string
    duration_s?: number
  }
  reality_scan?: {
    passed?: boolean
    violations?: Array<string>
  }
  secret_scan?: {
    passed?: boolean
    redacted_hits_count?: number
  }
  policy_guardian?: {
    allowed?: boolean
    severity?: number
    checks_run?: number
    summary?: string
    risk_signals?: Array<{
      code: string
      label: string
      target?: string
      reason?: string
      severity?: number
    }>
  }
  critic_review?: {
    verdict?: string
    notes?: string
    blind_spots?: Array<string>
  }
  trajectory?: {
    step_count?: number
    steps?: Array<{
      index: number
      type: string
      tool_name?: string
      status: string
      reversible?: boolean
      vetting_verdict?: string
    }>
    board_messages?: Array<{
      seq: number
      author: string
      kind: string
      text: string
    }>
    spawn_decision?: {
      routine?: string
      count?: number
    }
  }
  can_force_revision?: boolean
}

type TrajectoryRevertPreview = {
  target_index: number
  steps_removed: number
  irreversible_among_removed: Array<number>
  safe_to_revert: boolean
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

type PositionedNode = {
  id: string
  label: string
  subtitle: string
  detail: string
  kind: NodeKind
  state: string
  visits: number
  x: number
  y: number
  width: number
  height: number
}

type PositionedEdge = {
  id: string
  source: string
  target: string
  label: string
  active: boolean
  isBackEdge: boolean
  points: Array<{ x: number; y: number }>
  labelPos: { x: number; y: number }
}

function inferNodeKind(node: WorkflowNode): NodeKind {
  if (
    node.kind === 'agent' ||
    node.kind === 'deterministic' ||
    node.kind === 'human_gate' ||
    node.kind === 'terminal'
  ) {
    return node.kind
  }
  if (node.id === 'DoneTerminal' || node.id === 'AbortedTerminal') {
    return 'terminal'
  }
  if (node.id === 'ChiefReviewSink' || node.id === 'ChiefEscalationSink') {
    return 'human_gate'
  }
  if (
    node.id === 'VerificationGate' ||
    node.id === 'VerificationGateWorker' ||
    node.id === 'ContextHarvesterWorker' ||
    node.id === 'SubtaskFanOutWorker' ||
    node.id === 'TeamSynthesisJoiner' ||
    node.id === 'PolicyGuardianGateWorker' ||
    node.id === 'TemplateIntegrityGateWorker' ||
    node.id === 'SkillAndMemoryAccumulatorWorker'
  ) {
    return 'deterministic'
  }
  return 'agent'
}

function stateWord(state: string): string {
  if (state === 'running') return 'Running'
  if (state === 'waiting_gate') return 'Gate'
  if (state === 'succeeded') return 'Done'
  if (state === 'aborted') return 'Aborted'
  if (state === 'failed') return 'Failed'
  return 'Ready'
}

function shortenLabel(raw: string, maxLen = 17): string {
  const clean = raw.trim()
  if (clean.length <= maxLen) return clean
  return `${clean.slice(0, maxLen - 1)}…`
}

function roundedRectPath(
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): string {
  const rx = Math.min(r, w / 2, h / 2)
  const left = x - w / 2
  const top = y - h / 2
  const right = x + w / 2
  const bottom = y + h / 2
  return [
    `M ${left + rx} ${top}`,
    `L ${right - rx} ${top}`,
    `Q ${right} ${top} ${right} ${top + rx}`,
    `L ${right} ${bottom - rx}`,
    `Q ${right} ${bottom} ${right - rx} ${bottom}`,
    `L ${left + rx} ${bottom}`,
    `Q ${left} ${bottom} ${left} ${bottom - rx}`,
    `L ${left} ${top + rx}`,
    `Q ${left} ${top} ${left + rx} ${top}`,
    'Z',
  ].join(' ')
}

function hexagonPath(x: number, y: number, w: number, h: number): string {
  const indent = Math.max(8, Math.round(w * 0.16))
  const left = x - w / 2
  const right = x + w / 2
  const top = y - h / 2
  const bottom = y + h / 2
  return [
    `M ${left + indent} ${top}`,
    `L ${right - indent} ${top}`,
    `L ${right} ${y}`,
    `L ${right - indent} ${bottom}`,
    `L ${left + indent} ${bottom}`,
    `L ${left} ${y}`,
    'Z',
  ].join(' ')
}

function diamondPath(x: number, y: number, w: number, h: number): string {
  const dw = w * 1.18
  const dh = h * 1.32
  return [
    `M ${x} ${y - dh / 2}`,
    `L ${x + dw / 2} ${y}`,
    `L ${x} ${y + dh / 2}`,
    `L ${x - dw / 2} ${y}`,
    'Z',
  ].join(' ')
}

function edgeBezierPath(points: Array<{ x: number; y: number }>): string {
  if (points.length === 0) return ''
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`
  if (points.length === 2) {
    return `M ${points[0].x} ${points[0].y} L ${points[1].x} ${points[1].y}`
  }
  if (points.length === 3) {
    return `M ${points[0].x} ${points[0].y} Q ${points[1].x} ${points[1].y} ${points[2].x} ${points[2].y}`
  }
  const parts = [`M ${points[0].x} ${points[0].y}`]
  for (let i = 1; i < points.length - 2; i += 1) {
    const midX = (points[i].x + points[i + 1].x) / 2
    const midY = (points[i].y + points[i + 1].y) / 2
    parts.push(`Q ${points[i].x} ${points[i].y} ${midX} ${midY}`)
  }
  const penult = points[points.length - 2]
  const last = points[points.length - 1]
  parts.push(`Q ${penult.x} ${penult.y} ${last.x} ${last.y}`)
  return parts.join(' ')
}

function nodeColors(state: string, selected: boolean) {
  if (state === 'running') {
    return {
      fill: 'rgba(14, 165, 233, 0.14)',
      stroke: '#38bdf8',
      title: 'var(--color-primary-950)',
      sub: '#38bdf8',
    }
  }
  if (state === 'waiting_gate') {
    return {
      fill: 'rgba(245, 158, 11, 0.16)',
      stroke: '#f59e0b',
      title: 'var(--color-primary-950)',
      sub: '#f59e0b',
    }
  }
  if (state === 'succeeded') {
    return {
      fill: 'rgba(16, 185, 129, 0.13)',
      stroke: '#10b981',
      title: 'var(--color-primary-950)',
      sub: '#10b981',
    }
  }
  if (state === 'failed' || state === 'aborted') {
    return {
      fill: 'rgba(239, 68, 68, 0.14)',
      stroke: '#ef4444',
      title: 'var(--color-primary-950)',
      sub: '#ef4444',
    }
  }
  return {
    fill: selected ? 'var(--color-primary-200)' : 'var(--color-primary-100)',
    stroke: selected ? 'var(--color-primary-700)' : 'var(--color-primary-300)',
    title: 'var(--color-primary-950)',
    sub: 'var(--color-primary-600)',
  }
}

function buildBlueprintGraph(
  teamMode: boolean,
  services: Array<AgentServiceInfo>,
): { nodes: Array<WorkflowNode>; edges: Array<WorkflowEdge> } {
  if (!teamMode) {
    const primarySvc =
      services.find((s) => s.dispatch_ready)?.display_name || 'Agent'
    return {
      nodes: [
        {
          id: 'WorktreeRunner',
          label: `Run ${primarySvc}`,
          kind: 'agent',
          worker_class: 'WorktreeRunner',
          role: 'Executes in an isolated git worktree branch so your working tree stays clean.',
          state: 'idle',
        },
        {
          id: 'VerificationGate',
          label: 'Verify & scan',
          kind: 'deterministic',
          worker_class: 'VerificationGate',
          role: 'Runs deterministic project test command plus Law-2 reality and secret scans.',
          state: 'idle',
        },
        {
          id: 'ChiefReviewSink',
          label: 'Human Gate',
          kind: 'human_gate',
          worker_class: 'ChiefReviewSink',
          role: 'Pauses for operator review: Approve & Merge, Request Revision, or Abort.',
          state: 'idle',
        },
        {
          id: 'DoneTerminal',
          label: 'Landed',
          kind: 'terminal',
          worker_class: 'TerminalState',
          role: 'Verified branch merged cleanly onto target branch.',
          state: 'idle',
        },
        {
          id: 'AbortedTerminal',
          label: 'Aborted',
          kind: 'terminal',
          worker_class: 'TerminalState',
          role: 'Workflow aborted or halted.',
          state: 'idle',
        },
      ],
      edges: [
        {
          id: 'e_run_verify',
          source: 'WorktreeRunner',
          target: 'VerificationGate',
          label: 'committed',
        },
        {
          id: 'e_verify_review',
          source: 'VerificationGate',
          target: 'ChiefReviewSink',
          label: 'verified',
        },
        {
          id: 'e_review_done',
          source: 'ChiefReviewSink',
          target: 'DoneTerminal',
          label: 'approve',
        },
        {
          id: 'e_review_revision',
          source: 'ChiefReviewSink',
          target: 'WorktreeRunner',
          label: 'revision',
          is_back_edge: true,
        },
        {
          id: 'e_review_abort',
          source: 'ChiefReviewSink',
          target: 'AbortedTerminal',
          label: 'abort',
        },
      ],
    }
  }

  const readyServices = services.filter((s) => s.dispatch_ready).slice(0, 3)
  const nodes: Array<WorkflowNode> = [
    {
      id: 'ContextHarvesterWorker',
      label: 'Read repo',
      kind: 'deterministic',
      worker_class: 'ContextHarvesterWorker',
      role: 'Harvests repository tree, recent commits, empirical pass rates, and active guardrails.',
      state: 'idle',
    },
    {
      id: 'LeadPlannerWorker',
      label: 'Lead Planner',
      kind: 'agent',
      worker_class: 'PlanAILeadPlannerLLMWorker',
      role: 'PlanAI LLMTaskWorker decomposes goal into disjoint file scopes.',
      state: 'idle',
    },
  ]
  const edges: Array<WorkflowEdge> = [
    {
      id: 'e_ctx_plan',
      source: 'ContextHarvesterWorker',
      target: 'LeadPlannerWorker',
      label: 'context',
    },
  ]

  if (readyServices.length >= 2) {
    readyServices.forEach((svc, idx) => {
      const laneId = `subagent_${idx + 1}`
      nodes.push({
        id: laneId,
        label: svc.display_name,
        kind: 'agent',
        worker_class: 'MultiAgentDispatchWorker',
        role: `Isolated git worktree lane ${idx + 1} (${svc.service}).`,
        state: 'idle',
      })
      edges.push({
        id: `e_plan_${laneId}`,
        source: 'LeadPlannerWorker',
        target: laneId,
        label: `lane ${idx + 1}`,
      })
      edges.push({
        id: `e_${laneId}_join`,
        source: laneId,
        target: 'TeamSynthesisJoiner',
      })
    })
  } else {
    nodes.push({
      id: 'MultiAgentDispatchWorker',
      label: 'Parallel lanes',
      kind: 'agent',
      worker_class: 'MultiAgentDispatchWorker',
      role: 'Dispatches sub-agents into parallel isolated git worktrees.',
      state: 'idle',
    })
    edges.push({
      id: 'e_plan_exec',
      source: 'LeadPlannerWorker',
      target: 'MultiAgentDispatchWorker',
      label: 'fan-out',
    })
    edges.push({
      id: 'e_exec_join',
      source: 'MultiAgentDispatchWorker',
      target: 'TeamSynthesisJoiner',
      label: 'join',
    })
  }

  nodes.push(
    {
      id: 'TeamSynthesisJoiner',
      label: 'Join & merge',
      kind: 'deterministic',
      worker_class: 'TeamSynthesisJoiner',
      role: 'PlanAI JoinedTaskWorker merges parallel branches via ProvenanceChain.',
      state: 'idle',
    },
    {
      id: 'VerificationGateWorker',
      label: 'Verify & scan',
      kind: 'deterministic',
      worker_class: 'VerificationGateWorker',
      role: 'Runs integrated test command plus Law-2 reality and secret scans.',
      state: 'idle',
    },
    {
      id: 'CriticWorker',
      label: 'Adversarial Critic',
      kind: 'agent',
      worker_class: 'PlanAICriticLLMWorker',
      role: 'PlanAI LLMTaskWorker adversarial critic audits integrated bundle before Human Gate.',
      state: 'idle',
    },
    {
      id: 'ChiefEscalationSink',
      label: 'Human Gate',
      kind: 'human_gate',
      worker_class: 'ChiefEscalationSink',
      role: 'Pauses integrated multi-agent bundle for operator review.',
      state: 'idle',
    },
    {
      id: 'DoneTerminal',
      label: 'Landed',
      kind: 'terminal',
      worker_class: 'TerminalState',
      role: 'Integrated branch merged cleanly onto target branch.',
      state: 'idle',
    },
    {
      id: 'AbortedTerminal',
      label: 'Aborted',
      kind: 'terminal',
      worker_class: 'TerminalState',
      role: 'Workflow aborted or halted.',
      state: 'idle',
    },
  )

  edges.push(
    {
      id: 'e_join_verify',
      source: 'TeamSynthesisJoiner',
      target: 'VerificationGateWorker',
      label: 'merged',
    },
    {
      id: 'e_gate_critic',
      source: 'VerificationGateWorker',
      target: 'CriticWorker',
      label: 'verified',
    },
    {
      id: 'e_critic_sink',
      source: 'CriticWorker',
      target: 'ChiefEscalationSink',
      label: 'critiqued',
    },
    {
      id: 'e_sink_done',
      source: 'ChiefEscalationSink',
      target: 'DoneTerminal',
      label: 'approve',
    },
    {
      id: 'e_sink_revision',
      source: 'ChiefEscalationSink',
      target: 'LeadPlannerWorker',
      label: 'revision',
      is_back_edge: true,
    },
    {
      id: 'e_sink_abort',
      source: 'ChiefEscalationSink',
      target: 'AbortedTerminal',
      label: 'abort',
    },
  )

  return { nodes, edges }
}

export function InlinePlanAIDag({
  activeProjectId: _activeProjectId,
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
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [containerWidth, setContainerWidth] = useState<number>(760)
  const [workflows, setWorkflows] = useState<Array<PlanAIWorkflow>>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string>('')
  const [detail, setDetail] = useState<WorkflowDetailPayload | null>(null)
  const [gateTab, setGateTab] = useState<'summary' | 'diff' | 'checks'>('diff')
  const [revisionOpen, setRevisionOpen] = useState<boolean>(false)
  const [revisionNote, setRevisionNote] = useState<string>('')
  const [resetBranchOnRevision, setResetBranchOnRevision] =
    useState<boolean>(false)
  const [trajectoryExpanded, setTrajectoryExpanded] = useState<boolean>(false)
  const [revertPreview, setRevertPreview] =
    useState<TrajectoryRevertPreview | null>(null)
  const [revertBusy, setRevertBusy] = useState<boolean>(false)
  const [confirmAbort, setConfirmAbort] = useState<boolean>(false)
  const [gateBusy, setGateBusy] = useState<boolean>(false)
  const [gateError, setGateError] = useState<string>('')
  const [dismissedGateRoundKey, setDismissedGateRoundKey] = useState<string>('')

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const measure = () => {
      const w = el.getBoundingClientRect().width
      if (w > 120) setContainerWidth(Math.round(w))
    }
    measure()
    const ro = new ResizeObserver(() => measure())
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const refreshWorkflows = useCallback(async () => {
    try {
      const res = await fetch('/api/autoplan/planai/workflows?limit=30')
      if (!res.ok) return
      const data = (await res.json()) as {
        workflows?: Array<PlanAIWorkflow>
      }
      setWorkflows(data.workflows || [])
    } catch {
      // ignore transient poll errors
    }
  }, [])

  const activeWorkflow = useMemo(() => {
    if (!sessionKey || sessionKey === 'new') return null
    const forSession = workflows.filter((w) => w.session_key === sessionKey)
    return forSession.length > 0 ? forSession[0] : null
  }, [sessionKey, workflows])

  const fetchWorkflowDetail = useCallback(async (wfId: string) => {
    try {
      const res = await fetch(`/api/autoplan/planai/workflows/${wfId}/detail`)
      if (!res.ok) return
      const payload = (await res.json()) as WorkflowDetailPayload
      if (payload.success) setDetail(payload)
    } catch {
      // ignore transient detail fetch error
    }
  }, [])

  useEffect(() => {
    void refreshWorkflows()
    const isRunning = activeWorkflow?.state === 'running'
    const interval = window.setInterval(
      () => {
        void refreshWorkflows()
      },
      isRunning ? 1200 : 5000,
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

  const activeWfId = activeWorkflow?.id || ''
  const activeWfState = activeWorkflow?.state || ''
  const activeWfRound = activeWorkflow?.round || 1

  useEffect(() => {
    if (!activeWfId) {
      setDetail(null)
      return
    }
    if (
      activeWfState === 'waiting_gate' ||
      activeWfState === 'succeeded' ||
      activeWfState === 'aborted' ||
      selectedNodeId !== ''
    ) {
      void fetchWorkflowDetail(activeWfId)
    }
  }, [
    activeWfId,
    activeWfState,
    activeWfRound,
    selectedNodeId,
    fetchWorkflowDetail,
  ])

  const showTeamTopology =
    activeWorkflow?.graph_type === 'teamwork' ||
    (!activeWorkflow && sessionMode === 'team')

  const rawGraph = useMemo(() => {
    if (activeWorkflow && activeWorkflow.nodes.length > 0) {
      const hasDynamicLanes = activeWorkflow.nodes.some((n) =>
        n.id.startsWith('subagent_'),
      )
      const filteredNodes = activeWorkflow.nodes.filter((n) => {
        if (n.id === 'SubtaskFanOutWorker') return false
        if (hasDynamicLanes && n.id === 'MultiAgentDispatchWorker') return false
        return true
      })
      const nodeIds = new Set(filteredNodes.map((n) => n.id))
      const rawEdges: Array<WorkflowEdge> = []
      for (const e of activeWorkflow.edges || []) {
        let src = e.source
        let tgt = e.target
        if (src === 'SubtaskFanOutWorker') src = 'LeadPlannerWorker'
        if (tgt === 'SubtaskFanOutWorker') continue
        if (nodeIds.has(src) && nodeIds.has(tgt)) {
          rawEdges.push({ ...e, source: src, target: tgt })
        }
      }
      return { nodes: filteredNodes, edges: rawEdges }
    }
    return buildBlueprintGraph(showTeamTopology, services)
  }, [activeWorkflow, services, showTeamTopology])

  const rankdir = containerWidth < 500 ? 'TB' : 'LR'

  const layoutResult = useMemo(() => {
    const g = new dagre.graphlib.Graph({ multigraph: true })
    g.setGraph({
      rankdir,
      nodesep: empty ? 22 : 16,
      ranksep: rankdir === 'LR' ? (empty ? 42 : 34) : 28,
      marginx: 16,
      marginy: 16,
    })
    g.setDefaultEdgeLabel(() => ({}))

    const visitsMap = activeWorkflow?.visit_counts || {}
    const compact = !empty
    const baseW = compact ? 106 : 118
    const baseH = compact ? 36 : 40

    for (const n of rawGraph.nodes) {
      const kind = inferNodeKind(n)
      const w =
        kind === 'human_gate'
          ? Math.round(baseW * 1.06)
          : kind === 'terminal'
            ? Math.round(baseW * 0.86)
            : baseW
      const h = kind === 'human_gate' ? Math.round(baseH * 1.15) : baseH
      g.setNode(n.id, { width: w, height: h })
    }

    for (const e of rawGraph.edges) {
      g.setEdge(e.source, e.target, { label: e.label || '' }, e.id)
    }

    dagre.layout(g)

    const graphMeta = g.graph()
    const totalW = Math.max(240, Math.ceil((graphMeta.width || 480) + 8))
    const totalH = Math.max(76, Math.ceil((graphMeta.height || 100) + 8))

    const positionedNodes: Array<PositionedNode> = rawGraph.nodes.map((n) => {
      const pos = g.node(n.id)
      const kind = inferNodeKind(n)
      const metricVisits = Number(n.metrics?.visits || 0)
      const visits = Math.max(visitsMap[n.id] || 0, metricVisits)
      return {
        id: n.id,
        label: shortenLabel(n.label),
        subtitle: activeWorkflow
          ? stateWord(n.state)
          : kind === 'human_gate'
            ? 'Gate'
            : kind === 'terminal'
              ? 'Terminal'
              : 'Ready',
        detail: n.role,
        kind,
        state: n.state || 'idle',
        visits,
        x: pos.x,
        y: pos.y,
        width: pos.width,
        height: pos.height,
      }
    })

    const positionedEdges: Array<PositionedEdge> = rawGraph.edges.map((e) => {
      const dagreEdge = g.edge(e.source, e.target, e.id)
      const pts: Array<{ x: number; y: number }> = dagreEdge.points
      const mid = pts[Math.floor(pts.length / 2)] || { x: 0, y: 0 }
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label || '',
        active: Boolean(e.active),
        isBackEdge: Boolean(e.is_back_edge),
        points: pts,
        labelPos: mid,
      }
    })

    return {
      width: totalW,
      height: totalH,
      nodes: positionedNodes,
      edges: positionedEdges,
    }
  }, [activeWorkflow, empty, rankdir, rawGraph])

  const gateNodeSelected =
    selectedNodeId === 'ChiefReviewSink' ||
    selectedNodeId === 'ChiefEscalationSink'

  const currentGateRoundKey = activeWorkflow
    ? `${activeWorkflow.id}:r${activeWorkflow.round || 1}`
    : ''

  const showGateReviewPanel = Boolean(
    activeWorkflow &&
      ((activeWorkflow.state === 'waiting_gate' &&
        dismissedGateRoundKey !== currentGateRoundKey) ||
        (gateNodeSelected && detail?.queue_item)),
  )

  const selectedNode = useMemo(
    () => layoutResult.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [layoutResult.nodes, selectedNodeId],
  )

  const selectedNodeEvents = useMemo(() => {
    if (!activeWorkflow?.events.length || !selectedNode) return []
    return activeWorkflow.events.filter((ev) => ev.node_id === selectedNode.id)
  }, [activeWorkflow, selectedNode])

  useEffect(() => {
    setRevertPreview(null)
  }, [activeWfId, activeWfRound])

  const handleTrajectoryRevert = async (
    toIndex: number,
    previewOnly: boolean,
  ) => {
    if (!activeWorkflow) return
    setRevertBusy(true)
    setGateError('')
    try {
      const res = await fetch(
        `/api/autoplan/planai/workflows/${activeWorkflow.id}/trajectory/revert`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            to_index: toIndex,
            preview_only: previewOnly,
          }),
        },
      )
      const data = (await res.json()) as {
        success?: boolean
        error?: string
        preview?: TrajectoryRevertPreview
      }
      if (!res.ok || !data.success) {
        setGateError(data.error || 'Trajectory revert request failed.')
        return
      }
      if (previewOnly && data.preview) {
        setRevertPreview(data.preview)
      } else {
        setRevertPreview(null)
        await fetchWorkflowDetail(activeWorkflow.id)
      }
    } catch (err) {
      setGateError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setRevertBusy(false)
    }
  }

  const submitGateEvent = async (
    event: 'APPROVE' | 'FORCE_REVISION' | 'ABORT',
  ) => {
    if (!activeWorkflow) return
    if (event === 'FORCE_REVISION' && !revisionNote.trim()) {
      setGateError('Enter revision feedback before requesting changes.')
      return
    }
    setGateBusy(true)
    setGateError('')
    try {
      const res = await fetch(
        `/api/autoplan/planai/workflows/${activeWorkflow.id}/gate`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            event,
            note: event === 'FORCE_REVISION' ? revisionNote.trim() : '',
            reset_branch:
              event === 'FORCE_REVISION' ? resetBranchOnRevision : false,
          }),
        },
      )
      const data = (await res.json()) as {
        success?: boolean
        error?: string
      }
      if (!res.ok || !data.success) {
        setGateError(data.error || `Gate transition ${event} failed.`)
        return
      }
      setRevisionOpen(false)
      setRevisionNote('')
      setResetBranchOnRevision(false)
      setConfirmAbort(false)
      await refreshWorkflows()
      await fetchWorkflowDetail(activeWorkflow.id)
      window.dispatchEvent(new CustomEvent('autoplan:event'))
    } catch (err) {
      setGateError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setGateBusy(false)
    }
  }

  const handleNodeClick = (node: PositionedNode) => {
    setGateError('')
    setConfirmAbort(false)
    if (
      node.kind === 'human_gate' &&
      activeWorkflow &&
      dismissedGateRoundKey === currentGateRoundKey
    ) {
      setDismissedGateRoundKey('')
      setSelectedNodeId(node.id)
      return
    }
    setSelectedNodeId((prev) => (prev === node.id ? '' : node.id))
  }

  const stateMachineSvg = (
    <div
      ref={containerRef}
      data-testid="planai-dag-canvas"
      className="w-full overflow-x-auto"
    >
      <div className="flex justify-center">
        <svg
          role="img"
          aria-label="Workflow state machine graph"
          data-testid="planai-state-machine-svg"
          viewBox={`0 0 ${layoutResult.width} ${layoutResult.height}`}
          style={{
            width: `${layoutResult.width}px`,
            maxWidth: '100%',
            height: 'auto',
            minHeight: empty ? '104px' : '84px',
          }}
          className="overflow-visible"
        >
          <defs>
            <marker
              id="planai-arrow-muted"
              viewBox="0 0 10 10"
              refX="8.5"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path
                d="M 0 1.5 L 10 5 L 0 8.5 z"
                fill="var(--color-primary-500)"
              />
            </marker>
            <marker
              id="planai-arrow-active"
              viewBox="0 0 10 10"
              refX="8.5"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="#38bdf8" />
            </marker>
            <marker
              id="planai-arrow-back"
              viewBox="0 0 10 10"
              refX="8.5"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="#f59e0b" />
            </marker>
          </defs>

          {layoutResult.edges.map((edge) => {
            const backLit =
              edge.isBackEdge &&
              (edge.active || (activeWorkflow?.round || 1) > 1)
            const strokeColor = edge.active
              ? '#38bdf8'
              : backLit
                ? '#f59e0b'
                : 'var(--color-primary-400)'
            const marker = edge.active
              ? 'url(#planai-arrow-active)'
              : backLit
                ? 'url(#planai-arrow-back)'
                : 'url(#planai-arrow-muted)'
            return (
              <g
                key={edge.id}
                data-testid={`planai-edge-${edge.id}`}
                data-back-edge={edge.isBackEdge ? 'true' : 'false'}
              >
                <path
                  d={edgeBezierPath(edge.points)}
                  fill="none"
                  stroke={strokeColor}
                  strokeWidth={edge.active || backLit ? 1.75 : 1.25}
                  strokeDasharray={edge.isBackEdge ? '6,4' : undefined}
                  markerEnd={marker}
                />
                {edge.label ? (
                  <text
                    x={edge.labelPos.x}
                    y={edge.labelPos.y - 4}
                    textAnchor="middle"
                    fontSize="8.5"
                    fill={backLit ? '#f59e0b' : 'var(--color-primary-600)'}
                    className="pointer-events-none font-mono"
                  >
                    {edge.label}
                  </text>
                ) : null}
              </g>
            )
          })}

          {layoutResult.nodes.map((node) => {
            const isSelected = selectedNodeId === node.id
            const palette = nodeColors(node.state, isSelected)
            const outerPath =
              node.kind === 'deterministic'
                ? hexagonPath(node.x, node.y, node.width, node.height)
                : node.kind === 'human_gate'
                  ? diamondPath(node.x, node.y, node.width, node.height)
                  : roundedRectPath(
                      node.x,
                      node.y,
                      node.width,
                      node.height,
                      node.kind === 'terminal' ? 6 : 8,
                    )
            const badgeX =
              node.x +
              (node.kind === 'human_gate' ? node.width * 0.42 : node.width / 2 - 3)
            const badgeY =
              node.y -
              (node.kind === 'human_gate' ? node.height * 0.48 : node.height / 2 - 2)

            return (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                aria-label={`${node.label}: ${node.subtitle}`}
                data-testid={`planai-node-${node.id}`}
                data-node-kind={node.kind}
                onClick={() => handleNodeClick(node)}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault()
                    handleNodeClick(node)
                  }
                }}
                className="cursor-pointer focus:outline-none"
              >
                <path
                  d={outerPath}
                  fill={palette.fill}
                  stroke={palette.stroke}
                  strokeWidth={
                    isSelected ||
                    node.state === 'running' ||
                    node.state === 'waiting_gate'
                      ? 1.9
                      : 1.25
                  }
                />
                {node.kind === 'terminal' &&
                node.width > 16 &&
                node.height > 14 ? (
                  <path
                    d={roundedRectPath(
                      node.x,
                      node.y,
                      node.width - 7,
                      node.height - 7,
                      4,
                    )}
                    fill="none"
                    stroke={palette.stroke}
                    strokeWidth="1"
                    opacity="0.75"
                  />
                ) : null}

                <text
                  x={node.x}
                  y={node.y - 4}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize="10.5"
                  fontWeight="600"
                  fill={palette.title}
                >
                  {node.label}
                </text>
                <text
                  x={node.x}
                  y={node.y + 9}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize="9"
                  fill={palette.sub}
                  data-testid={`planai-node-state-${node.id}`}
                  className="tabular-nums"
                >
                  {node.subtitle}
                </text>

                {node.visits > 1 ? (
                  <g data-testid={`planai-node-visits-${node.id}`}>
                    <circle
                      cx={badgeX}
                      cy={badgeY}
                      r="8.5"
                      fill="#f59e0b"
                      stroke="var(--color-surface)"
                      strokeWidth="1.2"
                    />
                    <text
                      x={badgeX}
                      y={badgeY + 0.5}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fontSize="8.5"
                      fontWeight="700"
                      fill="#002028"
                    >
                      {`×${node.visits}`}
                    </text>
                  </g>
                ) : null}
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )

  const qItem = detail?.item || detail?.queue_item || null
  const changedFiles = detail?.changed_files || []
  const diffText = detail?.diff_text || ''
  const testReport = detail?.test_report
  const realityScan = detail?.reality_scan
  const secretScan = detail?.secret_scan
  const policyGuardian = detail?.policy_guardian
  const trajectory = detail?.trajectory
  const isWaitingAtGate = activeWorkflow?.state === 'waiting_gate'

  const gateReviewPanel = showGateReviewPanel ? (
    <div
      data-testid="planai-gate-review-panel"
      className="mt-2 rounded-lg border border-amber-500/40 bg-primary-100/70 p-3 text-xs select-text"
    >
      <div className="flex items-center justify-between gap-2 border-b border-primary-200 pb-2">
        <div className="min-w-0">
          <div className="truncate font-semibold text-primary-950">
            {isWaitingAtGate ? 'Human Gate — Action Required' : 'Gate Artifact'}{' '}
            {qItem?.title ? `· ${qItem.title}` : ''}
          </div>
          <div className="truncate font-mono text-[11px] text-primary-600">
            {`Round ${activeWorkflow?.round || 1}/${activeWorkflow?.max_rounds || 3}`}
            {qItem?.branch ? ` · ${qItem.branch} → ${qItem.target_branch || 'main'}` : ''}
          </div>
        </div>
        <button
          type="button"
          aria-label="Dismiss gate panel"
          onClick={() => {
            if (isWaitingAtGate && currentGateRoundKey) {
              setDismissedGateRoundKey(currentGateRoundKey)
            }
            setSelectedNodeId('')
          }}
          className="shrink-0 rounded px-1.5 py-0.5 text-primary-500 hover:bg-primary-200 hover:text-primary-950"
        >
          ×
        </button>
      </div>

      <div
        role="tablist"
        aria-label="Gate artifact tabs"
        className="mt-2 flex items-center gap-1 border-b border-primary-200 pb-1.5"
      >
        {(
          [
            ['diff', `Diff & Files (${changedFiles.length})`],
            ['summary', 'Summary'],
            ['checks', 'Checks'],
          ] as const
        ).map(([tabKey, tabLabel]) => (
          <button
            key={tabKey}
            type="button"
            role="tab"
            aria-selected={gateTab === tabKey}
            data-testid={`gate-tab-${tabKey}`}
            onClick={() => setGateTab(tabKey)}
            className={cn(
              'rounded px-2 py-1 text-[11px] font-medium transition-colors',
              gateTab === tabKey
                ? 'bg-primary-200 text-primary-950'
                : 'text-primary-600 hover:bg-primary-200/50 hover:text-primary-900',
            )}
          >
            {tabLabel}
          </button>
        ))}
      </div>

      <div className="mt-2 max-h-44 overflow-y-auto">
        {gateTab === 'diff' ? (
          <div className="space-y-1.5">
            {changedFiles.length > 0 ? (
              <div
                data-testid="gate-changed-files"
                className="font-mono text-[11px] text-primary-700"
              >
                {changedFiles.join(', ')}
              </div>
            ) : null}
            {diffText ? (
              <pre
                data-testid="gate-diff-viewer"
                className="overflow-x-auto rounded border border-primary-200 bg-surface p-2 font-mono text-[11px] leading-relaxed text-primary-900"
              >
                {diffText}
              </pre>
            ) : (
              <div className="text-primary-600">
                {qItem?.branch
                  ? `Branch ${qItem.branch} ready for review.`
                  : 'Task output ready for review (no git file diff).'}
              </div>
            )}
          </div>
        ) : null}

        {gateTab === 'summary' ? (
          <div
            data-testid="gate-summary-body"
            className="whitespace-pre-wrap text-primary-800 leading-relaxed"
          >
            {qItem?.body || activeWorkflow?.goal || 'Awaiting operator decision.'}
          </div>
        ) : null}

        {gateTab === 'checks' ? (
          <div data-testid="gate-checks-body" className="space-y-1 text-primary-800">
            <div>
              <span className="font-medium text-primary-950">Tests: </span>
              {testReport?.configured
                ? testReport.passed
                  ? `Passed (${testReport.command || 'exit 0'})`
                  : `Failed (exit ${testReport.exit_code ?? 1})`
                : 'No project test command configured'}
            </div>
            <div>
              <span className="font-medium text-primary-950">
                Law-2 Reality Scan:{' '}
              </span>
              {realityScan?.passed === false
                ? `Flagged (${realityScan.violations?.length || 1} unauthorized mock markers)`
                : 'Clean (0 mock/placeholder markers)'}
            </div>
            <div>
              <span className="font-medium text-primary-950">Secret Scan: </span>
              {secretScan?.passed === false
                ? `Blocked (${secretScan.redacted_hits_count || 1} credential patterns)`
                : 'Clean (0 leaked tokens)'}
            </div>
            <div data-testid="gate-policy-guardian">
              <span className="font-medium text-primary-950">
                PolicyGuardian:{' '}
              </span>
              {policyGuardian?.allowed === false
                ? `Denied · severity ${policyGuardian.severity ?? 0} (${(policyGuardian.risk_signals || []).map((r) => `${r.code}: ${r.label}`).join(', ') || 'policy violation'})`
                : `Allowed · severity ${policyGuardian?.severity ?? 0} (${policyGuardian?.checks_run ?? 0} checks)`}
            </div>
            {detail?.critic_review?.verdict ? (
              <div data-testid="gate-critic-review">
                <span className="font-medium text-primary-950">
                  Adversarial Critic:{' '}
                </span>
                {`${detail.critic_review.verdict}${detail.critic_review.notes ? ` · ${detail.critic_review.notes}` : ''}`}
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-2">
              <div data-testid="gate-trajectory-summary">
                <span className="font-medium text-primary-950">Trajectory: </span>
                {`${trajectory?.step_count ?? 0} recorded steps${
                  trajectory?.board_messages?.length
                    ? ` · ${trajectory.board_messages.length} swarm board posts`
                    : ''
                }`}
              </div>
              {(trajectory?.steps?.length ?? 0) > 0 ? (
                <button
                  type="button"
                  data-testid="gate-trajectory-toggle"
                  onClick={() => {
                    setTrajectoryExpanded((prev) => !prev)
                    setRevertPreview(null)
                  }}
                  className="rounded px-1.5 py-0.5 text-[11px] font-medium text-primary-700 hover:bg-primary-200 hover:text-primary-950"
                >
                  {trajectoryExpanded ? 'Hide steps' : 'Inspect steps'}
                </button>
              ) : null}
            </div>
            {trajectoryExpanded && (trajectory?.steps?.length ?? 0) > 0 ? (
              <div
                data-testid="gate-trajectory-list"
                className="mt-1 divide-y divide-primary-200 border-y border-primary-200"
              >
                {(trajectory?.steps || []).map((step) => (
                  <div
                    key={step.index}
                    data-testid={`trajectory-step-${step.index}`}
                    className="flex items-center justify-between gap-2 py-1 text-[11px]"
                  >
                    <span className="truncate font-mono text-primary-900">
                      {`#${step.index} ${step.type}${step.tool_name ? ` · ${step.tool_name}` : ''}`}
                    </span>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <span className="text-primary-600">
                        {step.reversible === false
                          ? `${step.status} · locked`
                          : step.status}
                      </span>
                      {isWaitingAtGate &&
                      step.index < (trajectory?.steps?.length ?? 0) - 1 ? (
                        <button
                          type="button"
                          data-testid={`trajectory-preview-btn-${step.index}`}
                          disabled={revertBusy}
                          onClick={() =>
                            void handleTrajectoryRevert(step.index, true)
                          }
                          className="rounded border border-primary-300 px-1.5 py-0.5 text-[10px] font-medium text-primary-800 hover:bg-primary-200 disabled:opacity-40"
                        >
                          Preview revert
                        </button>
                      ) : null}
                    </div>
                  </div>
                ))}
                {revertPreview ? (
                  <div
                    data-testid="trajectory-revert-preview"
                    className="flex items-center justify-between gap-2 py-1.5 text-[11px]"
                  >
                    <span className="text-primary-900">
                      {revertPreview.safe_to_revert
                        ? `Revert to #${revertPreview.target_index}: drops ${revertPreview.steps_removed} step(s)`
                        : `Blocked by irreversible step(s): #${revertPreview.irreversible_among_removed.join(', #')}`}
                    </span>
                    {revertPreview.safe_to_revert ? (
                      <button
                        type="button"
                        data-testid="trajectory-confirm-revert-btn"
                        disabled={revertBusy}
                        onClick={() =>
                          void handleTrajectoryRevert(
                            revertPreview.target_index,
                            false,
                          )
                        }
                        className="rounded bg-amber-500 px-2 py-0.5 text-[10px] font-semibold text-slate-950 hover:bg-amber-400 disabled:opacity-40"
                      >
                        {revertBusy
                          ? 'Reverting…'
                          : `Revert to #${revertPreview.target_index}`}
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {gateError ? (
        <div
          data-testid="gate-error-banner"
          className="mt-2 rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-[11px] text-red-400"
        >
          {gateError}
        </div>
      ) : null}

      {isWaitingAtGate ? (
        <div className="mt-2.5 space-y-2 border-t border-primary-200 pt-2">
          {revisionOpen ? (
            <div className="space-y-1.5">
              <textarea
                rows={2}
                data-testid="gate-revision-input"
                value={revisionNote}
                onChange={(e) => setRevisionNote(e.target.value)}
                placeholder="Describe exact changes for the next revision round on this branch…"
                className="w-full rounded border border-primary-300 bg-surface px-2 py-1.5 text-xs text-primary-950 placeholder:text-primary-500 focus:border-primary-500 focus:outline-none"
              />
              <label className="flex items-center gap-1.5 text-[11px] text-primary-700">
                <input
                  type="checkbox"
                  data-testid="gate-revision-reset-branch"
                  checked={resetBranchOnRevision}
                  onChange={(e) => setResetBranchOnRevision(e.target.checked)}
                  className="rounded border-primary-300"
                />
                Reset branch to target before next round
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="gate-revision-submit"
                  disabled={gateBusy || !revisionNote.trim()}
                  onClick={() => void submitGateEvent('FORCE_REVISION')}
                  className="rounded bg-amber-500 px-2.5 py-1 text-[11px] font-semibold text-slate-950 hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {gateBusy ? 'Dispatching…' : 'Send Revision'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setRevisionOpen(false)
                    setGateError('')
                  }}
                  className="rounded border border-primary-300 px-2 py-1 text-[11px] text-primary-700 hover:bg-primary-200"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="gate-approve-button"
                disabled={gateBusy}
                onClick={() => void submitGateEvent('APPROVE')}
                className="rounded bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {gateBusy ? 'Merging…' : 'Approve & Merge'}
              </button>
              {detail?.can_force_revision !== false &&
              (activeWorkflow?.round || 1) < (activeWorkflow?.max_rounds || 3) ? (
                <button
                  type="button"
                  data-testid="gate-revision-toggle"
                  disabled={gateBusy}
                  onClick={() => {
                    setRevisionOpen((prev) => !prev)
                    setConfirmAbort(false)
                  }}
                  className="rounded border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-400 hover:bg-amber-500/20 disabled:opacity-40"
                >
                  Request Revision
                </button>
              ) : null}
            </div>

            {confirmAbort ? (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  data-testid="gate-abort-confirm"
                  disabled={gateBusy}
                  onClick={() => void submitGateEvent('ABORT')}
                  className="rounded bg-red-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-red-500 disabled:opacity-40"
                >
                  Confirm Abort
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmAbort(false)}
                  className="rounded border border-primary-300 px-2 py-1 text-[11px] text-primary-700 hover:bg-primary-200"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                data-testid="gate-abort-button"
                disabled={gateBusy}
                onClick={() => {
                  setConfirmAbort(true)
                  setRevisionOpen(false)
                }}
                className="rounded border border-red-500/40 px-2 py-1 text-[11px] text-red-400 hover:bg-red-500/10 disabled:opacity-40"
              >
                Abort
              </button>
            )}
          </div>
        </div>
      ) : null}
    </div>
  ) : null

  const nodeInspector =
    selectedNode && (!gateNodeSelected || !showGateReviewPanel) ? (
      <div
        data-testid="planai-node-inspector"
        className="mt-2 flex items-start justify-between gap-3 rounded-lg border border-primary-200 bg-primary-100/55 px-3 py-2 text-xs select-text"
      >
        <div className="min-w-0 space-y-1">
          <div className="font-medium text-primary-950">
            {selectedNode.label}{' '}
            <span className="font-mono text-[11px] font-normal text-primary-500">
              {`${selectedNode.id} [${selectedNode.kind}]`}
            </span>
          </div>
          {selectedNodeEvents.length > 0 ? (
            <div className="space-y-0.5 text-primary-800">
              {selectedNodeEvents.slice(-3).map((ev, i) => (
                <div key={`${ev.ts}-${i}`}>{ev.summary || ev.detail}</div>
              ))}
            </div>
          ) : (
            <p className="text-primary-600 text-pretty">{selectedNode.detail}</p>
          )}
        </div>
        <button
          type="button"
          aria-label="Close stage details"
          onClick={() => setSelectedNodeId('')}
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
        <div className="flex w-full max-w-[780px] flex-col items-center gap-3">
          <div className="text-xs text-primary-600">
            {activeProjectName ? `${activeProjectName} · ` : ''}
            {showTeamTopology
              ? 'PlanAI Multi-Agent State-Machine Graph'
              : 'PlanAI Isolated Branch State-Machine Graph'}
          </div>
          {stateMachineSvg}
          {gateReviewPanel ? (
            <div className="w-full max-w-[680px]">{gateReviewPanel}</div>
          ) : null}
          {nodeInspector ? (
            <div className="w-full max-w-[640px]">{nodeInspector}</div>
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
        {stateMachineSvg}
        {gateReviewPanel}
        {nodeInspector}
      </div>
    </section>
  )
}
