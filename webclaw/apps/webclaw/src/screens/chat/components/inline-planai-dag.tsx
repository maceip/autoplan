import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import dagre from '@dagrejs/dagre'
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Maximize2,
  MessageSquarePlus,
  Minimize2,
  Trash2,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
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

export type GuidedChapter = {
  id: string
  index_label?: string
  title: string
  rationale: string
  files: Array<{
    path: string
    additions: number
    deletions: number
    diff_chunk: string
  }>
  handoffs: Array<{
    from_node?: string
    to_node?: string
    task_type?: string
    payload?: Record<string, unknown>
  }>
  metadata?: Record<string, unknown>
  gates?: Record<string, unknown>
  reviewed: boolean
}

export type WorkflowAnnotation = {
  id: string
  workflow_id: string
  project_id: string
  round_num: number
  kind: 'comment' | 'deletion' | 'must_change'
  target_type: string
  target_id: string
  file_path: string
  line_range: string
  selected_text: string
  comment_text: string
  resolved: boolean
  author: string
  created_at: number
  updated_at: number
}

export type RoundHistoryEntry = {
  round_num: number
  handoffs_count: number
  handoff_types?: Array<string>
  decisions?: Array<Record<string, unknown>>
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
  chapters?: Array<GuidedChapter>
  round_history?: Array<RoundHistoryEntry>
  annotations?: Array<WorkflowAnnotation>
  compiled_annotations_markdown?: string
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
      fill: 'var(--color-info-muted)',
      stroke: 'var(--color-info)',
      title: 'var(--color-text-primary)',
      sub: 'var(--color-text-info)',
    }
  }
  if (state === 'waiting_gate') {
    return {
      fill: 'var(--color-warning-muted)',
      stroke: 'var(--color-warning)',
      title: 'var(--color-text-primary)',
      sub: 'var(--color-text-warning)',
    }
  }
  if (state === 'succeeded') {
    return {
      fill: 'var(--color-success-muted)',
      stroke: 'var(--color-success)',
      title: 'var(--color-text-primary)',
      sub: 'var(--color-text-success)',
    }
  }
  if (state === 'failed' || state === 'aborted') {
    return {
      fill: 'var(--color-error-muted)',
      stroke: 'var(--color-error)',
      title: 'var(--color-text-primary)',
      sub: 'var(--color-text-error)',
    }
  }
  return {
    fill: selected
      ? 'var(--color-background-muted)'
      : 'var(--color-background-card)',
    stroke: selected
      ? 'var(--color-border-emphasized)'
      : 'var(--color-border)',
    title: 'var(--color-text-primary)',
    sub: 'var(--color-text-secondary)',
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
  const [gateTab, setGateTab] = useState<
    'diff' | 'chapters' | 'summary' | 'checks'
  >('diff')
  const [svgZoom, setSvgZoom] = useState<number>(1)
  const [graphCollapsed, setGraphCollapsed] = useState<boolean>(false)
  const [activeChapterIdx, setActiveChapterIdx] = useState<number>(0)
  const [chapterBusyId, setChapterBusyId] = useState<string>('')
  const [annotComposerOpen, setAnnotComposerOpen] = useState<boolean>(false)
  const [annotKind, setAnnotKind] = useState<
    'comment' | 'must_change' | 'deletion'
  >('must_change')
  const [annotFilePath, setAnnotFilePath] = useState<string>('')
  const [annotLineRange, setAnnotLineRange] = useState<string>('')
  const [annotText, setAnnotText] = useState<string>('')
  const [annotBusy, setAnnotBusy] = useState<boolean>(false)
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
    const baseW = compact ? 116 : 132
    const baseH = compact ? 38 : 42

    for (const n of rawGraph.nodes) {
      const kind = inferNodeKind(n)
      const w =
        kind === 'human_gate'
          ? Math.round(baseW * 1.08)
          : kind === 'terminal'
            ? Math.round(baseW * 0.88)
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
    setActiveChapterIdx(0)
    setAnnotComposerOpen(false)
  }, [activeWfId, activeWfRound])

  const chapters = detail?.chapters || []
  const annotations = detail?.annotations || []
  const openAnnotations = useMemo(
    () => annotations.filter((a) => !a.resolved),
    [annotations],
  )
  const compiledAnnotationsMd = detail?.compiled_annotations_markdown || ''

  const handleToggleChapterReviewed = async (
    chapterId: string,
    reviewed: boolean,
  ) => {
    if (!activeWorkflow) return
    setChapterBusyId(chapterId)
    setGateError('')
    setDetail((prev) =>
      prev
        ? {
            ...prev,
            chapters: (prev.chapters || []).map((ch) =>
              ch.id === chapterId ? { ...ch, reviewed } : ch,
            ),
          }
        : prev,
    )
    try {
      const res = await fetch(
        `/api/autoplan/planai/workflows/${activeWorkflow.id}/chapters`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ chapter_id: chapterId, reviewed }),
        },
      )
      if (!res.ok) {
        setDetail((prev) =>
          prev
            ? {
                ...prev,
                chapters: (prev.chapters || []).map((ch) =>
                  ch.id === chapterId ? { ...ch, reviewed: !reviewed } : ch,
                ),
              }
            : prev,
        )
        const errData = (await res.json().catch(() => ({}))) as {
          error?: string
        }
        setGateError(errData.error || 'Failed to update chapter progress.')
        return
      }
      await fetchWorkflowDetail(activeWorkflow.id)
    } catch (err) {
      setDetail((prev) =>
        prev
          ? {
              ...prev,
              chapters: (prev.chapters || []).map((ch) =>
                ch.id === chapterId ? { ...ch, reviewed: !reviewed } : ch,
              ),
            }
          : prev,
      )
      setGateError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setChapterBusyId('')
    }
  }

  const handleCreateAnnotation = async () => {
    if (!activeWorkflow) return
    const trimmed = annotText.trim()
    if (!trimmed && annotKind !== 'deletion') {
      setGateError('Enter an annotation note first.')
      return
    }
    setAnnotBusy(true)
    setGateError('')
    try {
      const res = await fetch(
        `/api/autoplan/planai/workflows/${activeWorkflow.id}/annotations`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            kind: annotKind,
            target_type: annotFilePath ? 'diff_file' : 'summary',
            target_id: annotFilePath || activeWorkflow.id,
            file_path: annotFilePath,
            line_range: annotLineRange.trim(),
            comment_text: trimmed,
          }),
        },
      )
      const data = (await res.json().catch(() => ({}))) as {
        success?: boolean
        error?: string
      }
      if (!res.ok || !data.success) {
        setGateError(data.error || 'Failed to save annotation.')
        return
      }
      setAnnotText('')
      setAnnotLineRange('')
      setAnnotComposerOpen(false)
      await fetchWorkflowDetail(activeWorkflow.id)
    } catch (err) {
      setGateError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setAnnotBusy(false)
    }
  }

  const handleToggleAnnotationResolved = async (
    annId: string,
    resolved: boolean,
  ) => {
    if (!activeWorkflow) return
    try {
      await fetch(
        `/api/autoplan/planai/workflows/${activeWorkflow.id}/annotations/${annId}`,
        {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ resolved }),
        },
      )
      await fetchWorkflowDetail(activeWorkflow.id)
    } catch {
      // ignore transient error
    }
  }

  const handleDeleteAnnotation = async (annId: string) => {
    if (!activeWorkflow) return
    try {
      await fetch(
        `/api/autoplan/planai/workflows/${activeWorkflow.id}/annotations/${annId}`,
        { method: 'DELETE' },
      )
      await fetchWorkflowDetail(activeWorkflow.id)
    } catch {
      // ignore transient error
    }
  }

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
    if (
      event === 'FORCE_REVISION' &&
      !revisionNote.trim() &&
      openAnnotations.length === 0
    ) {
      setGateError(
        'Enter revision feedback or add an annotation before requesting changes.',
      )
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
            include_annotations: event === 'FORCE_REVISION',
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
      className="w-full rounded-xl border border-border bg-card/85 p-2 shadow-sm"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
        <span className="text-[11px] font-medium text-secondary">
          {activeWorkflow
            ? `${activeWorkflow.title || 'Execution Graph'} · Round ${activeWorkflow.round || 1}/${activeWorkflow.max_rounds || 3}`
            : showTeamTopology
              ? 'Multi-Agent Execution Graph'
              : 'Isolated Branch Execution Graph'}
        </span>
        <div className="flex items-center gap-1">
          {!graphCollapsed ? (
            <>
              <button
                type="button"
                aria-label="Zoom out graph"
                onClick={() =>
                  setSvgZoom((z) => Math.max(0.8, Number((z - 0.1).toFixed(2))))
                }
                className="flex size-6 items-center justify-center rounded-md text-secondary hover:bg-muted hover:text-primary"
              >
                <ZoomOut className="size-3.5" />
              </button>
              <button
                type="button"
                aria-label="Reset graph zoom"
                onClick={() => setSvgZoom(1)}
                className="rounded-md px-1.5 py-0.5 text-[10px] font-medium text-secondary hover:bg-muted hover:text-primary tabular-nums"
              >
                {Math.round(svgZoom * 100)}%
              </button>
              <button
                type="button"
                aria-label="Zoom in graph"
                onClick={() =>
                  setSvgZoom((z) =>
                    Math.min(1.35, Number((z + 0.1).toFixed(2))),
                  )
                }
                className="flex size-6 items-center justify-center rounded-md text-secondary hover:bg-muted hover:text-primary"
              >
                <ZoomIn className="size-3.5" />
              </button>
            </>
          ) : null}
          <button
            type="button"
            aria-label={graphCollapsed ? 'Expand graph' : 'Collapse graph'}
            onClick={() => setGraphCollapsed((prev) => !prev)}
            className="flex size-6 items-center justify-center rounded-md text-secondary hover:bg-muted hover:text-primary"
          >
            {graphCollapsed ? (
              <Maximize2 className="size-3.5" />
            ) : (
              <Minimize2 className="size-3.5" />
            )}
          </button>
        </div>
      </div>

      {!graphCollapsed ? (
        <div className="flex justify-center overflow-x-auto">
          <svg
            role="img"
            aria-label="Workflow state machine graph"
            data-testid="planai-state-machine-svg"
            viewBox={`0 0 ${layoutResult.width} ${layoutResult.height}`}
            style={{
              width: `${Math.round(layoutResult.width * svgZoom)}px`,
              maxWidth: svgZoom > 1 ? 'none' : '100%',
              height: 'auto',
              minHeight: empty ? '108px' : '88px',
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
                  fill="var(--color-text-disabled)"
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
                <path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="var(--color-info)" />
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
                <path
                  d="M 0 1.5 L 10 5 L 0 8.5 z"
                  fill="var(--color-warning)"
                />
              </marker>
            </defs>

            {layoutResult.edges.map((edge) => {
              const backLit =
                edge.isBackEdge &&
                (edge.active || (activeWorkflow?.round || 1) > 1)
              const strokeColor = edge.active
                ? 'var(--color-info)'
                : backLit
                  ? 'var(--color-warning)'
                  : 'var(--color-border-emphasized)'
              const marker = edge.active
                ? 'url(#planai-arrow-active)'
                : backLit
                  ? 'url(#planai-arrow-back)'
                  : 'url(#planai-arrow-muted)'
              const pillW = edge.label ? Math.max(36, edge.label.length * 5.6 + 10) : 0
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
                    strokeWidth={edge.active || backLit ? 1.85 : 1.3}
                    strokeDasharray={edge.isBackEdge ? '6,4' : undefined}
                    markerEnd={marker}
                  />
                  {edge.label ? (
                    <g className="pointer-events-none">
                      <rect
                        x={edge.labelPos.x - pillW / 2}
                        y={edge.labelPos.y - 12}
                        width={pillW}
                        height={13}
                        rx={4}
                        fill="var(--color-background-card)"
                        stroke="var(--color-border)"
                        strokeWidth={0.75}
                      />
                      <text
                        x={edge.labelPos.x}
                        y={edge.labelPos.y - 3.5}
                        textAnchor="middle"
                        fontSize="8.5"
                        fill={
                          backLit
                            ? 'var(--color-text-warning)'
                            : 'var(--color-text-secondary)'
                        }
                        className="font-mono"
                      >
                        {edge.label}
                      </text>
                    </g>
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
                        node.kind === 'terminal' ? 7 : 10,
                      )
              const badgeX =
                node.x +
                (node.kind === 'human_gate'
                  ? node.width * 0.42
                  : node.width / 2 - 4)
              const badgeY =
                node.y -
                (node.kind === 'human_gate'
                  ? node.height * 0.48
                  : node.height / 2 - 3)

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
                        5,
                      )}
                      fill="none"
                      stroke={palette.stroke}
                      strokeWidth="1"
                      opacity="0.7"
                    />
                  ) : null}

                  <text
                    x={node.x}
                    y={node.y - 4.5}
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
                        fill="var(--color-warning)"
                        stroke="var(--color-background-surface)"
                        strokeWidth="1.2"
                      />
                      <text
                        x={badgeX}
                        y={badgeY + 0.5}
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize="8.5"
                        fontWeight="700"
                        fill="var(--color-on-warning)"
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
      ) : null}
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

  const safeChapterIdx =
    chapters.length > 0 ? Math.min(activeChapterIdx, chapters.length - 1) : 0
  const activeChapter = chapters[safeChapterIdx] || null
  const reviewedChaptersCount = chapters.filter((ch) => ch.reviewed).length

  const gateReviewPanel = showGateReviewPanel ? (
    <div
      data-testid="planai-gate-review-panel"
      className={cn(
        'mt-2.5 rounded-xl border p-3.5 text-xs select-text shadow-sm transition-colors',
        isWaitingAtGate
          ? 'border-warning/50 bg-warning-muted/20'
          : 'border-border bg-card',
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border pb-2.5">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-primary">
            {isWaitingAtGate ? 'Human Gate — Action Required' : 'Gate Artifact'}{' '}
            {qItem?.title ? `· ${qItem.title}` : ''}
          </div>
          <div className="truncate font-mono text-[11px] text-secondary">
            {`Round ${activeWorkflow?.round || 1}/${activeWorkflow?.max_rounds || 3}`}
            {qItem?.branch ? ` · ${qItem.branch} → ${qItem.target_branch || 'main'}` : ''}
            {openAnnotations.length > 0
              ? ` · ${openAnnotations.length} open notes`
              : ''}
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
          className="shrink-0 rounded-md px-1.5 py-0.5 text-secondary hover:bg-muted hover:text-primary"
        >
          ×
        </button>
      </div>

      <div
        role="tablist"
        aria-label="Gate artifact tabs"
        className="mt-2.5 flex flex-wrap items-center gap-1 border-b border-border pb-2"
      >
        {(
          [
            ['diff', `Diff & Files (${changedFiles.length})`],
            [
              'chapters',
              chapters.length > 0
                ? `Guided Chapters (${reviewedChaptersCount}/${chapters.length})`
                : 'Guided Chapters',
            ],
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
              'rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors',
              gateTab === tabKey
                ? 'bg-muted text-primary shadow-xs'
                : 'text-secondary hover:bg-muted/60 hover:text-primary',
            )}
          >
            {tabLabel}
          </button>
        ))}
      </div>

      <div className="mt-2.5 max-h-64 overflow-y-auto pr-0.5">
        {gateTab === 'diff' ? (
          <div className="space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              {changedFiles.length > 0 ? (
                <div
                  data-testid="gate-changed-files"
                  className="min-w-0 flex-1 truncate font-mono text-[11px] text-secondary"
                >
                  {changedFiles.join(', ')}
                </div>
              ) : (
                <span className="text-[11px] text-secondary">
                  {qItem?.branch
                    ? `Branch ${qItem.branch} ready for review.`
                    : 'No git file diff recorded yet.'}
                </span>
              )}
              <button
                type="button"
                data-testid="gate-add-annotation-btn"
                onClick={() => {
                  setAnnotFilePath((prev) => prev || changedFiles[0] || '')
                  setAnnotComposerOpen((prev) => !prev)
                }}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-[11px] font-medium text-primary hover:bg-muted"
              >
                <MessageSquarePlus className="size-3" />
                <span>+ Annotate</span>
              </button>
            </div>

            {annotComposerOpen ? (
              <div
                data-testid="gate-annotation-composer"
                className="space-y-2 rounded-lg border border-border bg-surface p-2.5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    aria-label="Annotation kind"
                    value={annotKind}
                    onChange={(e) =>
                      setAnnotKind(
                        e.target.value as 'comment' | 'must_change' | 'deletion',
                      )
                    }
                    className="h-7 rounded-md border border-border bg-card px-2 text-[11px] text-primary outline-none"
                  >
                    <option value="must_change">Must change</option>
                    <option value="comment">Comment</option>
                    <option value="deletion">Delete / Remove</option>
                  </select>
                  <select
                    aria-label="Target file"
                    value={annotFilePath}
                    onChange={(e) => setAnnotFilePath(e.target.value)}
                    className="h-7 max-w-[220px] truncate rounded-md border border-border bg-card px-2 font-mono text-[11px] text-primary outline-none"
                  >
                    <option value="">General Plan</option>
                    {changedFiles.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={annotLineRange}
                    onChange={(e) => setAnnotLineRange(e.target.value)}
                    placeholder="Lines (e.g. 12-24)"
                    className="h-7 w-28 rounded-md border border-border bg-card px-2 font-mono text-[11px] text-primary placeholder:text-disabled outline-none"
                  />
                </div>
                <textarea
                  rows={2}
                  data-testid="gate-annotation-input"
                  value={annotText}
                  onChange={(e) => setAnnotText(e.target.value)}
                  placeholder="Write specific review instruction for the agent…"
                  className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-primary placeholder:text-disabled outline-none"
                />
                <div className="flex items-center justify-end gap-1.5">
                  <button
                    type="button"
                    onClick={() => setAnnotComposerOpen(false)}
                    className="rounded-md px-2 py-1 text-[11px] text-secondary hover:bg-muted hover:text-primary"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    data-testid="gate-annotation-save-btn"
                    disabled={
                      annotBusy || (!annotText.trim() && annotKind !== 'deletion')
                    }
                    onClick={() => void handleCreateAnnotation()}
                    className="rounded-md bg-accent-bg px-2.5 py-1 text-[11px] font-medium text-on-accent disabled:opacity-40"
                  >
                    {annotBusy ? 'Saving…' : 'Save annotation'}
                  </button>
                </div>
              </div>
            ) : null}

            {annotations.length > 0 ? (
              <div
                data-testid="gate-annotations-list"
                className="space-y-1.5"
              >
                {annotations.map((ann) => (
                  <div
                    key={ann.id}
                    data-testid={`gate-annotation-item-${ann.id}`}
                    className={cn(
                      'flex items-start justify-between gap-2 rounded-lg border px-2.5 py-2',
                      ann.resolved
                        ? 'border-border bg-muted/40 opacity-70'
                        : 'border-border bg-surface',
                    )}
                  >
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex items-center gap-1.5 text-[11px]">
                        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-primary">
                          {ann.kind.replace('_', ' ')}
                        </span>
                        <span className="truncate font-mono text-secondary">
                          {ann.file_path || 'General Plan'}
                          {ann.line_range ? `:${ann.line_range}` : ''}
                        </span>
                      </div>
                      <p className="text-xs text-primary">{ann.comment_text}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        aria-label={
                          ann.resolved ? 'Reopen annotation' : 'Resolve annotation'
                        }
                        onClick={() =>
                          void handleToggleAnnotationResolved(
                            ann.id,
                            !ann.resolved,
                          )
                        }
                        className="rounded p-1 text-secondary hover:bg-muted hover:text-primary"
                      >
                        <Check className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        aria-label="Delete annotation"
                        onClick={() => void handleDeleteAnnotation(ann.id)}
                        className="rounded p-1 text-secondary hover:bg-muted hover:text-error"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            {diffText ? (
              <pre
                data-testid="gate-diff-viewer"
                className="overflow-x-auto rounded-lg border border-border bg-surface p-2.5 font-mono text-[11px] leading-relaxed text-primary"
              >
                {diffText}
              </pre>
            ) : null}
          </div>
        ) : null}

        {gateTab === 'chapters' ? (
          <div className="space-y-3">
            {chapters.length === 0 ? (
              <div className="rounded-lg border border-border bg-surface p-3 text-secondary">
                Guided chapters appear once a workflow reaches review.
              </div>
            ) : activeChapter ? (
              <>
                <div
                  data-testid="guided-chapter-switcher"
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface px-2.5 py-2"
                >
                  <div className="flex flex-wrap items-center gap-1">
                    {chapters.map((ch, idx) => (
                      <button
                        key={ch.id}
                        type="button"
                        onClick={() => setActiveChapterIdx(idx)}
                        className={cn(
                          'inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors',
                          idx === safeChapterIdx
                            ? 'bg-accent-bg text-on-accent'
                            : ch.reviewed
                              ? 'bg-success-muted text-success'
                              : 'bg-muted text-secondary hover:text-primary',
                        )}
                      >
                        <span>{ch.index_label?.split(' / ')[0] || idx + 1}</span>
                        {ch.reviewed ? <Check className="size-3" /> : null}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      data-testid="chapter-prev-btn"
                      disabled={safeChapterIdx <= 0}
                      onClick={() =>
                        setActiveChapterIdx((idx) => Math.max(0, idx - 1))
                      }
                      className="flex size-6 items-center justify-center rounded border border-border text-secondary hover:bg-muted hover:text-primary disabled:opacity-40"
                    >
                      <ChevronLeft className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      data-testid="chapter-next-btn"
                      disabled={safeChapterIdx >= chapters.length - 1}
                      onClick={() =>
                        setActiveChapterIdx((idx) =>
                          Math.min(chapters.length - 1, idx + 1),
                        )
                      }
                      className="flex size-6 items-center justify-center rounded border border-border text-secondary hover:bg-muted hover:text-primary disabled:opacity-40"
                    >
                      <ChevronRight className="size-3.5" />
                    </button>
                  </div>
                </div>

                <div className="space-y-2 rounded-lg border border-border bg-surface p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-primary">
                        {activeChapter.index_label
                          ? `${activeChapter.index_label} · ${activeChapter.title}`
                          : activeChapter.title}
                      </div>
                      <p className="mt-0.5 text-[11px] text-secondary">
                        {activeChapter.rationale}
                      </p>
                    </div>
                    <label className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-primary">
                      <input
                        type="checkbox"
                        data-testid={`chapter-reviewed-${activeChapter.id}`}
                        checked={Boolean(activeChapter.reviewed)}
                        disabled={chapterBusyId === activeChapter.id}
                        onChange={(e) =>
                          void handleToggleChapterReviewed(
                            activeChapter.id,
                            e.target.checked,
                          )
                        }
                      />
                      <span>Reviewed</span>
                    </label>
                  </div>

                  {activeChapter.handoffs.length > 0 ? (
                    <div className="space-y-1 pt-1">
                      {activeChapter.handoffs.map((h, i) => (
                        <div
                          key={`${activeChapter.id}-h-${i}`}
                          className="rounded border border-border bg-card px-2 py-1.5 font-mono text-[11px] text-secondary"
                        >
                          {h.from_node || '?'} → {h.to_node || '?'} ·{' '}
                          {h.task_type || 'Handoff'}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {activeChapter.files.length > 0 ? (
                    <div className="space-y-1.5 pt-1">
                      {activeChapter.files.map((f) => (
                        <div
                          key={f.path}
                          className="rounded border border-border bg-card p-2"
                        >
                          <div className="flex items-center justify-between gap-2 font-mono text-[11px]">
                            <span className="truncate font-medium text-primary">
                              {f.path}
                            </span>
                            <span className="shrink-0 text-secondary tabular-nums">
                              +{f.additions} / -{f.deletions}
                            </span>
                          </div>
                          {f.diff_chunk ? (
                            <pre className="mt-1.5 max-h-32 overflow-x-auto font-mono text-[10px] leading-relaxed text-secondary">
                              {f.diff_chunk}
                            </pre>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>
        ) : null}

        {gateTab === 'summary' ? (
          <div data-testid="gate-summary-body" className="space-y-2.5">
            <div className="whitespace-pre-wrap rounded-lg border border-border bg-surface p-2.5 text-primary leading-relaxed">
              {qItem?.body || activeWorkflow?.goal || 'Awaiting operator decision.'}
            </div>
            {(detail?.round_history?.length ?? 0) > 0 ? (
              <div className="space-y-1.5">
                {detail?.round_history?.map((rh) => (
                  <div
                    key={rh.round_num}
                    className="rounded-lg border border-border bg-surface px-2.5 py-2 text-[11px]"
                  >
                    <div className="font-semibold text-primary">
                      Round {rh.round_num} · {rh.handoffs_count} handoffs
                    </div>
                    {rh.handoff_types && rh.handoff_types.length > 0 ? (
                      <div className="mt-1 font-mono text-[10px] text-secondary">
                        {rh.handoff_types.join(' · ')}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {gateTab === 'checks' ? (
          <div data-testid="gate-checks-body" className="space-y-1.5 text-primary">
            <div>
              <span className="font-medium text-primary">Tests: </span>
              {testReport?.configured
                ? testReport.passed
                  ? `Passed (${testReport.command || 'exit 0'})`
                  : `Failed (exit ${testReport.exit_code ?? 1})`
                : 'No project test command configured'}
            </div>
            <div>
              <span className="font-medium text-primary">
                Law-2 Reality Scan:{' '}
              </span>
              {realityScan?.passed === false
                ? `Flagged (${realityScan.violations?.length || 1} unauthorized mock markers)`
                : 'Clean (0 mock/placeholder markers)'}
            </div>
            <div>
              <span className="font-medium text-primary">Secret Scan: </span>
              {secretScan?.passed === false
                ? `Blocked (${secretScan.redacted_hits_count || 1} credential patterns)`
                : 'Clean (0 leaked tokens)'}
            </div>
            <div data-testid="gate-policy-guardian">
              <span className="font-medium text-primary">
                PolicyGuardian:{' '}
              </span>
              {policyGuardian?.allowed === false
                ? `Denied · severity ${policyGuardian.severity ?? 0} (${(policyGuardian.risk_signals || []).map((r) => `${r.code}: ${r.label}`).join(', ') || 'policy violation'})`
                : `Allowed · severity ${policyGuardian?.severity ?? 0} (${policyGuardian?.checks_run ?? 0} checks)`}
            </div>
            {detail?.critic_review?.verdict ? (
              <div data-testid="gate-critic-review">
                <span className="font-medium text-primary">
                  Adversarial Critic:{' '}
                </span>
                {`${detail.critic_review.verdict}${detail.critic_review.notes ? ` · ${detail.critic_review.notes}` : ''}`}
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-2 pt-1">
              <div data-testid="gate-trajectory-summary">
                <span className="font-medium text-primary">Trajectory: </span>
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
                  className="rounded-md px-2 py-0.5 text-[11px] font-medium text-secondary hover:bg-muted hover:text-primary"
                >
                  {trajectoryExpanded ? 'Hide steps' : 'Inspect steps'}
                </button>
              ) : null}
            </div>
            {trajectoryExpanded && (trajectory?.steps?.length ?? 0) > 0 ? (
              <div
                data-testid="gate-trajectory-list"
                className="mt-1 divide-y divide-border border-y border-border"
              >
                {(trajectory?.steps || []).map((step) => (
                  <div
                    key={step.index}
                    data-testid={`trajectory-step-${step.index}`}
                    className="flex items-center justify-between gap-2 py-1 text-[11px]"
                  >
                    <span className="truncate font-mono text-primary">
                      {`#${step.index} ${step.type}${step.tool_name ? ` · ${step.tool_name}` : ''}`}
                    </span>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <span className="text-secondary">
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
                          className="rounded border border-border px-1.5 py-0.5 text-[10px] font-medium text-primary hover:bg-muted disabled:opacity-40"
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
                    <span className="text-primary">
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
                        className="rounded bg-warning px-2 py-0.5 text-[10px] font-semibold text-on-warning disabled:opacity-40"
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
          className="mt-2 rounded-md border border-error/40 bg-error-muted px-2.5 py-1.5 text-[11px] text-error"
        >
          {gateError}
        </div>
      ) : null}

      {isWaitingAtGate ? (
        <div className="mt-2.5 space-y-2 border-t border-border pt-2.5">
          {revisionOpen ? (
            <div className="space-y-2">
              {openAnnotations.length > 0 ? (
                <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-[11px]">
                  <span className="text-secondary">
                    {openAnnotations.length} unresolved review annotation(s)
                  </span>
                  <button
                    type="button"
                    data-testid="gate-compile-annotations-btn"
                    onClick={() => {
                      const md =
                        compiledAnnotationsMd ||
                        openAnnotations
                          .map((a) => `- [${a.kind}] ${a.file_path}: ${a.comment_text}`)
                          .join('\n')
                      setRevisionNote((prev) =>
                        prev.trim() ? `${prev.trim()}\n\n${md}` : md,
                      )
                    }}
                    className="rounded border border-border bg-card px-2 py-0.5 font-medium text-primary hover:bg-muted"
                  >
                    Insert compiled annotations
                  </button>
                </div>
              ) : null}
              <textarea
                rows={2}
                data-testid="gate-revision-input"
                value={revisionNote}
                onChange={(e) => setRevisionNote(e.target.value)}
                placeholder="Describe exact changes for the next revision round on this branch…"
                className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-primary placeholder:text-disabled focus:border-border-strong focus:outline-none"
              />
              <label className="flex items-center gap-1.5 text-[11px] text-secondary">
                <input
                  type="checkbox"
                  data-testid="gate-revision-reset-branch"
                  checked={resetBranchOnRevision}
                  onChange={(e) => setResetBranchOnRevision(e.target.checked)}
                  className="rounded border-border"
                />
                Reset branch to target before next round
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="gate-revision-submit"
                  disabled={
                    gateBusy ||
                    (!revisionNote.trim() && openAnnotations.length === 0)
                  }
                  onClick={() => void submitGateEvent('FORCE_REVISION')}
                  className="rounded-md bg-warning px-2.5 py-1 text-[11px] font-semibold text-on-warning disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {gateBusy ? 'Dispatching…' : 'Send Revision'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setRevisionOpen(false)
                    setGateError('')
                  }}
                  className="rounded-md border border-border px-2 py-1 text-[11px] text-secondary hover:bg-muted hover:text-primary"
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
                className="rounded-md bg-success px-2.5 py-1 text-[11px] font-semibold text-on-success disabled:cursor-not-allowed disabled:opacity-40"
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
                  className="rounded-md border border-warning/50 bg-warning-muted px-2.5 py-1 text-[11px] font-medium text-warning hover:opacity-90 disabled:opacity-40"
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
                  className="rounded-md bg-error px-2 py-1 text-[11px] font-semibold text-on-error disabled:opacity-40"
                >
                  Confirm Abort
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmAbort(false)}
                  className="rounded-md border border-border px-2 py-1 text-[11px] text-secondary hover:bg-muted"
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
                className="rounded-md border border-error/40 px-2 py-1 text-[11px] text-error hover:bg-error-muted disabled:opacity-40"
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
        className="mt-2 flex items-start justify-between gap-3 rounded-xl border border-border bg-card px-3 py-2 text-xs select-text shadow-sm"
      >
        <div className="min-w-0 space-y-1">
          <div className="font-medium text-primary">
            {selectedNode.label}{' '}
            <span className="font-mono text-[11px] font-normal text-secondary">
              {`${selectedNode.id} [${selectedNode.kind}]`}
            </span>
          </div>
          {selectedNodeEvents.length > 0 ? (
            <div className="space-y-0.5 text-secondary">
              {selectedNodeEvents.slice(-3).map((ev, i) => (
                <div key={`${ev.ts}-${i}`}>{ev.summary || ev.detail}</div>
              ))}
            </div>
          ) : (
            <p className="text-secondary text-pretty">{selectedNode.detail}</p>
          )}
        </div>
        <button
          type="button"
          aria-label="Close stage details"
          onClick={() => setSelectedNodeId('')}
          className="shrink-0 rounded px-1.5 py-0.5 text-secondary hover:bg-muted hover:text-primary"
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
          <div className="text-xs text-secondary">
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
              className="mt-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-primary shadow-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
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
      className="shrink-0 border-b border-border bg-surface px-4 py-2.5 select-none"
    >
      <div className="mx-auto flex max-w-[920px] flex-col">
        {stateMachineSvg}
        {gateReviewPanel}
        {nodeInspector}
      </div>
    </section>
  )
}
