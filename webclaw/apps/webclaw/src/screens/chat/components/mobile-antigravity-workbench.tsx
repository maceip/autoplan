import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useChatSettings as useSidebarSettings } from '../hooks/use-chat-settings'
import { SettingsDialog } from './settings-dialog'
import { ChatMessageList } from './chat-message-list'
import type { AgentServiceInfo } from './autoplan-inspector'
import type { ChatComposerHelpers } from './chat-composer'
import type { GatewayMessage, SessionMeta } from '../types'
import type { AttachmentFile } from '@/components/attachment-button'
import { AttachmentButton } from '@/components/attachment-button'
import { AttachmentPreviewList } from '@/components/attachment-preview'
import { usePinnedSessions } from '@/hooks/use-pinned-sessions'
import { cn } from '@/lib/utils'

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

const DECISION_ALLOWED: Record<string, Array<string>> = {
  approve: ['needs_review'],
  reject: ['needs_review', 'queued', 'triaged', 'in_progress'],
  snooze: ['needs_review', 'queued', 'triaged'],
}

export type MobileStageView = 'sessions' | 'session'

type MobileAntigravityWorkbenchProps = {
  sessions: Array<SessionMeta>
  activeFriendlyId: string
  activeTitle: string
  activeCanonicalKey: string
  isNewChat: boolean
  creatingSession: boolean
  services: Array<AgentServiceInfo>
  selectedService: string
  chiefLlmConfigured?: boolean
  chiefLlmStatus: string
  displayMessages: Array<GatewayMessage>
  historyLoading: boolean
  historyEmpty: boolean
  gatewayNotice: React.ReactNode
  waitingForResponse: boolean
  pinToTop: boolean
  pinGroupMinHeight: number
  headerHeight: number
  stableContentStyle: React.CSSProperties
  sending: boolean
  dispatchError: string
  onDismissError: () => void
  busyDemoService: string | null
  onSelectService: (service: string) => Promise<void> | void
  onRunSimpleTask: (service?: string) => Promise<void>
  onCreateSessionForService: (service: string) => Promise<void>
  onSendMessage: (body: string, helpers: ChatComposerHelpers) => void
  onExportMarkdown: () => void
  onRefreshAll: () => void
  onRefreshHistory: () => void
  onRunFinished: (runId: string) => void
  mobileView: MobileStageView
  onChangeMobileView: (view: MobileStageView) => void
  mobileDetailOpen: boolean
  onChangeMobileDetailOpen: (open: boolean) => void
}

function formatCompactAge(updatedAt?: number): string {
  if (!updatedAt || !Number.isFinite(updatedAt)) return ''
  const ms = updatedAt < 1_000_000_000_000 ? updatedAt * 1000 : updatedAt
  const diffSec = Math.max(0, Math.floor((Date.now() - ms) / 1000))
  if (diffSec < 60) return 'now'
  const mins = Math.floor(diffSec / 60)
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d`
}

function sessionDisplayTitle(session: SessionMeta): string {
  return (
    session.label?.trim() ||
    session.title?.trim() ||
    session.derivedTitle?.trim() ||
    session.friendlyId
  )
}

function AutobotBrandMark({ size = 'md' }: { size?: 'sm' | 'md' }) {
  return (
    <img
      src="/autobot-icon.png?v=2"
      alt=""
      aria-hidden="true"
      data-testid="mobile-autobot-icon"
      className={cn(
        'shrink-0 object-contain',
        size === 'sm' ? 'size-5' : 'size-6',
      )}
    />
  )
}

function PanelFooterIcon({ active }: { active?: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      className="size-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      aria-hidden="true"
    >
      <rect x="2.75" y="3.25" width="14.5" height="13.5" rx="2.25" />
      <line x1="2.75" y1="12.75" x2="17.25" y2="12.75" />
      {active ? (
        <rect
          x="3.5"
          y="13.25"
          width="13"
          height="2.75"
          rx="1"
          fill="currentColor"
          stroke="none"
        />
      ) : null}
    </svg>
  )
}

export function MobileAntigravityWorkbench({
  sessions,
  activeFriendlyId,
  activeTitle,
  activeCanonicalKey,
  creatingSession,
  services,
  selectedService,
  chiefLlmConfigured = false,
  chiefLlmStatus,
  displayMessages,
  historyLoading,
  historyEmpty,
  gatewayNotice,
  waitingForResponse,
  pinToTop,
  pinGroupMinHeight,
  headerHeight,
  stableContentStyle,
  sending,
  dispatchError,
  onDismissError,
  busyDemoService,
  onSelectService,
  onRunSimpleTask,
  onCreateSessionForService,
  onSendMessage,
  onExportMarkdown,
  onRefreshAll,
  onRefreshHistory,
  onRunFinished,
  mobileView,
  onChangeMobileView,
  mobileDetailOpen,
  onChangeMobileDetailOpen,
}: MobileAntigravityWorkbenchProps) {
  const navigate = useNavigate()
  const { pinnedSessionKeys, togglePinnedSession } = usePinnedSessions()
  const {
    settingsOpen,
    setSettingsOpen,
    pathsLoading,
    pathsError,
    paths,
    handleOpenSettings,
    closeSettings,
    copySessionsDir,
    copyStorePath,
  } = useSidebarSettings()

  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [pinnedExpanded, setPinnedExpanded] = useState(true)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)

  // Composer state for Sessions Home & Session View
  const [homeDraft, setHomeDraft] = useState('')
  const [sessionDraft, setSessionDraft] = useState('')
  const [attachments, setAttachments] = useState<Array<AttachmentFile>>([])

  // Live AutoPlan detail sheet state (real backend Queue, Runs, Scanned Sessions)
  const [detailTab, setDetailTab] = useState<'overview' | 'queue' | 'runs'>(
    'overview',
  )
  const [openSection, setOpenSection] = useState<
    'queue' | 'runs' | 'agents' | 'observed' | null
  >(null)
  const [queueFilter, setQueueFilter] = useState<string>('')
  const [items, setItems] = useState<Array<QueueItem>>([])
  const [runs, setRuns] = useState<Array<AgentRun>>([])
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const [scannedSessions, setScannedSessions] = useState<
    Record<string, Array<ScannedSession>>
  >({})
  const [expandedHomeObservedSvc, setExpandedHomeObservedSvc] = useState<
    string | null
  >(null)
  const [sheetError, setSheetError] = useState('')
  const prevRunStatesRef = useRef<Record<string, string> | null>(null)

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
            onRunFinished(run.id)
          }
        }
      }
      prevRunStatesRef.current = nextStates
      if (shouldRefreshChat) {
        onRefreshHistory()
      }
      setItems(nextItems)
      setRuns(nextRuns)
      setSelectedItemId((prev) => {
        if (prev && nextItems.some((it) => it.id === prev)) return prev
        return nextItems.length > 0 ? nextItems[0].id : null
      })
      setSheetError('')
    } catch (err) {
      setSheetError(err instanceof Error ? err.message : String(err))
    }
  }, [onRefreshHistory, onRunFinished, queueFilter])

  useEffect(() => {
    void refreshQueueAndRuns()
    const interval = window.setInterval(() => {
      void refreshQueueAndRuns()
    }, 3000)
    const onLiveEvent = () => {
      void refreshQueueAndRuns()
    }
    window.addEventListener('autoplan:event', onLiveEvent)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('autoplan:event', onLiveEvent)
    }
  }, [refreshQueueAndRuns])

  const loadObservedForService = useCallback(async (serviceName: string) => {
    try {
      const res = await fetch(
        `/api/autoplan/agents/${encodeURIComponent(serviceName)}/sessions?limit=8`,
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
        [serviceName]: payload.sessions || [],
      }))
    } catch (err) {
      setSheetError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  async function decideQueueItem(itemId: string, action: string) {
    try {
      const res = await fetch(`/api/autoplan/queue/items/${itemId}/decision`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ action, actor: 'webclaw-mobile-operator' }),
      })
      const payload = (await res.json()) as { success?: boolean; error?: string }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Decision HTTP ${res.status}`)
      }
      await refreshQueueAndRuns()
    } catch (err) {
      setSheetError(err instanceof Error ? err.message : String(err))
    }
  }

  async function wakeQueueItem(itemId: string) {
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
      setSheetError(err instanceof Error ? err.message : String(err))
    }
  }

  async function stopAgentRun(runId: string) {
    try {
      const res = await fetch(`/api/autoplan/agents/runs/${runId}/stop`, {
        method: 'POST',
      })
      const payload = (await res.json()) as { success?: boolean; error?: string }
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || `Stop HTTP ${res.status}`)
      }
      await refreshQueueAndRuns()
    } catch (err) {
      setSheetError(err instanceof Error ? err.message : String(err))
    }
  }

  const activeSvcInfo = useMemo(
    () => services.find((s) => s.service === selectedService),
    [selectedService, services],
  )
  const canDispatchSelected = activeSvcInfo ? activeSvcInfo.dispatch_ready : true

  const filteredSessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return sessions
    return sessions.filter((s) => {
      const title = sessionDisplayTitle(s).toLowerCase()
      const svc = (s.service || '').toLowerCase()
      return title.includes(q) || svc.includes(q)
    })
  }, [searchQuery, sessions])

  const pinnedSessions = useMemo(
    () => filteredSessions.filter((s) => pinnedSessionKeys.includes(s.key)),
    [filteredSessions, pinnedSessionKeys],
  )

  const groupedByService = useMemo(() => {
    const serviceOrder =
      services.length > 0
        ? services.map((s) => s.service)
        : ['antigravity', 'xiaomi-mimo', 'minimax']
    const buckets = new Map<string, Array<SessionMeta>>()
    for (const svc of serviceOrder) {
      buckets.set(svc, [])
    }
    for (const session of filteredSessions) {
      const svc = session.service || serviceOrder[0] || 'antigravity'
      const existing = buckets.get(svc)
      if (existing) {
        existing.push(session)
      } else {
        buckets.set(svc, [session])
      }
    }
    return Array.from(buckets.entries()).map(([svcName, list]) => {
      const info = services.find((s) => s.service === svcName)
      return {
        service: svcName,
        displayName: info?.display_name || svcName,
        mode: info?.mode || 'dispatch',
        dispatchReady: info ? info.dispatch_ready : true,
        observedCount: info?.observed_sessions_count ?? 0,
        sessions: list,
      }
    })
  }, [filteredSessions, services])

  const needsReviewCount = useMemo(
    () => items.filter((it) => it.status === 'needs_review').length,
    [items],
  )
  const activeRunCount = useMemo(
    () =>
      runs.filter((r) => r.state === 'running' || r.state === 'queued').length,
    [runs],
  )
  const totalObservedCount = useMemo(
    () =>
      services.reduce((acc, s) => acc + (s.observed_sessions_count || 0), 0),
    [services],
  )
  const selectedQueueItem = useMemo(
    () => items.find((it) => it.id === selectedItemId) ?? items[0] ?? null,
    [items, selectedItemId],
  )

  function handleOpenSession(session: SessionMeta) {
    setMoreMenuOpen(false)
    onChangeMobileDetailOpen(false)
    onChangeMobileView('session')
    void navigate({
      to: '/chat/$sessionKey',
      params: { sessionKey: session.friendlyId },
    })
  }

  function handleSubmitFromHome() {
    const text = homeDraft.trim()
    if (!text || sending) return
    onChangeMobileDetailOpen(false)
    onChangeMobileView('session')
    onSendMessage(text, {
      reset: () => setHomeDraft(''),
      setValue: (v) => setHomeDraft(v),
    })
  }

  function handleSubmitFromSession() {
    const text = sessionDraft.trim()
    const validAttachments = attachments.filter((a) => !a.error && a.base64)
    if ((text.length === 0 && validAttachments.length === 0) || sending) return
    onSendMessage(text, {
      reset: () => {
        setSessionDraft('')
        setAttachments((prev) => {
          prev.forEach((a) => {
            if (a.preview) URL.revokeObjectURL(a.preview)
          })
          return []
        })
      },
      setValue: (v) => setSessionDraft(v),
      attachments: validAttachments,
    })
  }

  async function handleQuickDemoTask(targetSvc?: string) {
    onChangeMobileView('session')
    await onRunSimpleTask(targetSvc || selectedService)
  }

  const isCurrentSessionPinned = pinnedSessionKeys.includes(activeCanonicalKey)

  // ───────────────────────────────────────────────────────────────────────────
  // STAGE 1: FULL-SCREEN ALL SESSIONS VIEW (Antigravity Mobile Home)
  // ───────────────────────────────────────────────────────────────────────────
  if (mobileView === 'sessions') {
    return (
      <div
        data-testid="mobile-sessions-screen"
        className="flex h-dvh w-full flex-col overflow-hidden bg-[#002b36] text-[#c9d8db]"
      >
        <header
          data-testid="mobile-top-app-bar"
          className="shrink-0 border-b border-[#133b45] bg-[#002b36]"
        >
          <div className="flex h-12 items-center justify-between gap-2 px-3">
            <div
              data-testid="mobile-brand"
              className="flex min-w-0 items-center gap-2"
            >
              <AutobotBrandMark size="md" />
              <span className="truncate text-[15px] font-semibold tracking-tight text-[#e6f0f2]">
                autobot
              </span>
            </div>

            <div className="flex shrink-0 items-center gap-0.5 rounded-xl border border-[#133b45] bg-[#0c3540]/80 p-0.5">
              <button
                type="button"
                data-testid="mobile-search-toggle"
                aria-label="Search sessions"
                aria-pressed={searchOpen}
                onClick={() => setSearchOpen((prev) => !prev)}
                className={cn(
                  'flex size-8 items-center justify-center rounded-lg text-[#839496]',
                  searchOpen
                    ? 'bg-[#133b45] text-[#e6f0f2]'
                    : 'active:bg-[#133b45]',
                )}
              >
                <svg
                  viewBox="0 0 20 20"
                  className="size-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.6}
                  aria-hidden="true"
                >
                  <circle cx="9" cy="9" r="5.5" />
                  <path d="M13.2 13.2L17 17" strokeLinecap="round" />
                </svg>
              </button>

              <button
                type="button"
                data-testid="mobile-settings-button"
                aria-label="Open settings"
                onClick={handleOpenSettings}
                className="flex size-8 items-center justify-center rounded-lg text-[#839496] active:bg-[#133b45]"
              >
                <svg
                  viewBox="0 0 20 20"
                  className="size-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.6}
                  aria-hidden="true"
                >
                  <circle cx="10" cy="10" r="2.75" />
                  <path
                    d="M10 2.75v1.75M10 15.5v1.75M2.75 10h1.75M15.5 10h1.75M4.87 4.87l1.24 1.24M13.89 13.89l1.24 1.24M15.13 4.87l-1.24 1.24M6.11 13.89l-1.24 1.24"
                    strokeLinecap="round"
                  />
                </svg>
              </button>

              <button
                type="button"
                data-testid="mobile-refresh-button"
                aria-label="Refresh sessions and agents"
                onClick={() => {
                  onRefreshAll()
                  void refreshQueueAndRuns()
                }}
                className="flex size-8 items-center justify-center rounded-lg text-[#839496] active:bg-[#133b45]"
              >
                <svg
                  viewBox="0 0 20 20"
                  className="size-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.6}
                  aria-hidden="true"
                >
                  <path
                    d="M16 10a6 6 0 1 1-1.6-4.08"
                    strokeLinecap="round"
                  />
                  <path
                    d="M16 3.5v3.25h-3.25"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>

              <button
                type="button"
                data-testid="mobile-home-detail-button"
                aria-label="Open queue and runs detail panel"
                onClick={() => {
                  setDetailTab('overview')
                  onChangeMobileView('session')
                  onChangeMobileDetailOpen(true)
                }}
                className="relative flex size-8 items-center justify-center rounded-lg text-[#839496] active:bg-[#133b45]"
              >
                <PanelFooterIcon />
                {needsReviewCount > 0 || activeRunCount > 0 ? (
                  <span className="absolute right-1 top-1 size-1.5 rounded-full bg-[#268bd2]" />
                ) : null}
              </button>
            </div>
          </div>
        </header>

        {searchOpen ? (
          <div className="px-4 pt-2 pb-1">
            <input
              type="search"
              data-testid="mobile-search-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter sessions or lead agents…"
              className="h-9 w-full rounded-xl border border-[#1e444e] bg-[#0c3540] px-3 text-sm text-[#c9d8db] placeholder:text-[#586e75] outline-none"
            />
          </div>
        ) : null}

        <div className="flex-1 min-h-0 overflow-y-auto px-4 pt-3 pb-3">
          {/* Top of Sessions List: Orchestrator & Lead-Agent Routing Strip */}
          <div
            data-testid="mobile-sessions-routing-strip"
            className="mb-3 flex items-center gap-1.5 rounded-2xl border border-[#133b45] bg-[#06303b]/85 p-1.5"
          >
            <button
              type="button"
              data-testid="mobile-orchestrator-chip"
              onClick={() => {
                setDetailTab('queue')
                onChangeMobileView('session')
                onChangeMobileDetailOpen(true)
              }}
              className="flex h-8 shrink-0 items-center gap-1.5 rounded-xl border border-[#1e444e] bg-[#0c3540] px-2.5 text-xs font-medium text-[#e6f0f2] active:bg-[#133b45]"
            >
              <span
                className={cn(
                  'size-2 shrink-0 rounded-full',
                  chiefLlmConfigured ? 'bg-[#268bd2]' : 'bg-[#7aae66]',
                )}
                aria-hidden="true"
              />
              <span>Chief</span>
              {needsReviewCount > 0 ? (
                <span className="rounded-full bg-[#268bd2]/25 px-1.5 py-px font-mono text-[10px] font-semibold text-[#e6f0f2] tabular-nums">
                  {needsReviewCount}
                </span>
              ) : (
                <span className="text-[11px] text-[#6b8184]">
                  {chiefLlmConfigured ? 'live' : 'triage'}
                </span>
              )}
            </button>

            <div className="relative flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-xl border border-[#1e444e] bg-[#0c3540] pl-2.5 pr-6">
              <span
                className={cn(
                  'size-2 shrink-0 rounded-full',
                  canDispatchSelected ? 'bg-[#7aae66]' : 'bg-[#586e75]',
                )}
                aria-hidden="true"
              />
              <select
                aria-label="Active lead agent service"
                data-testid="mobile-home-service-select"
                value={selectedService}
                onChange={(e) => void onSelectService(e.target.value)}
                className="w-full min-w-0 truncate appearance-none bg-transparent text-xs font-medium text-[#e6f0f2] outline-none"
              >
                {services.map((svc) => (
                  <option
                    key={svc.service}
                    value={svc.service}
                    className="bg-[#002b36] text-[#c9d8db]"
                  >
                    {svc.display_name}
                    {svc.mode === 'observe_only' ? ' (observe)' : ''}
                  </option>
                ))}
              </select>
              <svg
                viewBox="0 0 16 16"
                className="pointer-events-none absolute right-2 size-3.5 text-[#6b8184]"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.75}
                aria-hidden="true"
              >
                <path d="M4 6l4 4 4-4" />
              </svg>
            </div>

            <button
              type="button"
              data-testid="mobile-top-run-task"
              disabled={!canDispatchSelected || busyDemoService !== null}
              onClick={() => void handleQuickDemoTask(selectedService)}
              className="flex h-8 shrink-0 items-center rounded-xl border border-[#268bd2]/40 bg-[#268bd2]/15 px-2.5 text-xs font-medium text-[#e6f0f2] active:bg-[#268bd2]/25 disabled:opacity-35"
            >
              {busyDemoService ? 'Running…' : '+ Task'}
            </button>
          </div>
          {pinnedSessions.length > 0 ? (
            <section className="mb-4">
              <button
                type="button"
                onClick={() => setPinnedExpanded((prev) => !prev)}
                className="flex w-full items-center gap-1.5 py-2 text-xs font-medium text-[#586e75]"
              >
                <span>Pinned Conversations</span>
                <span aria-hidden="true">{pinnedExpanded ? '▾' : '▸'}</span>
              </button>
              {pinnedExpanded ? (
                <div className="flex flex-col gap-0.5">
                  {pinnedSessions.map((session) => (
                    <button
                      key={`pinned-${session.key}`}
                      type="button"
                      data-testid={`mobile-pinned-session-${session.friendlyId}`}
                      onClick={() => handleOpenSession(session)}
                      className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-2 py-2 text-left active:bg-[#0c3540]"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[15px] text-[#839496]">
                          {sessionDisplayTitle(session)}
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-[#586e75]">
                          <span>{session.service || 'antigravity'}</span>
                        </div>
                      </div>
                      <span className="shrink-0 text-xs text-[#586e75] tabular-nums">
                        {formatCompactAge(session.updatedAt)}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}

          <div className="flex items-center justify-between py-2">
            <span className="text-xs font-medium text-[#586e75]">
              Projects & Agents
            </span>
            <button
              type="button"
              data-testid="mobile-new-session-top"
              disabled={creatingSession}
              aria-label="Create new session"
              onClick={() => void onCreateSessionForService(selectedService)}
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[#839496] active:bg-[#0c3540] disabled:opacity-40"
            >
              <span>+ New</span>
            </button>
          </div>

          <div className="flex flex-col gap-3">
            {groupedByService.map((group) => {
              const isObservedExpanded = expandedHomeObservedSvc === group.service
              const observedList = scannedSessions[group.service] || []
              return (
                <section
                  key={group.service}
                  data-testid={`mobile-service-group-${group.service}`}
                  className="flex flex-col"
                >
                  <div className="flex h-10 items-center justify-between px-1">
                    <div className="flex min-w-0 items-center gap-2.5 text-[#6b8184]">
                      <svg
                        viewBox="0 0 20 20"
                        className="size-4 shrink-0 text-[#586e75]"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={1.5}
                        aria-hidden="true"
                      >
                        <path d="M2.75 5.5A1.75 1.75 0 0 1 4.5 3.75h3.3l1.6 1.75h6.1a1.75 1.75 0 0 1 1.75 1.75v7.25a1.75 1.75 0 0 1-1.75 1.75h-11A1.75 1.75 0 0 1 2.75 14.5v-9Z" />
                      </svg>
                      <span className="truncate text-[15px] font-normal text-[#6b8184]">
                        {group.service}
                      </span>
                      {group.mode === 'observe_only' ? (
                        <span className="rounded bg-[#0c3540] px-1.5 py-0.5 text-[10px] text-[#586e75]">
                          observe
                        </span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      data-testid={`mobile-group-new-${group.service}`}
                      disabled={creatingSession}
                      aria-label={`New session with ${group.displayName}`}
                      onClick={() => void onCreateSessionForService(group.service)}
                      className="flex size-8 items-center justify-center rounded-lg text-[#6b8184] active:bg-[#0c3540] disabled:opacity-40"
                    >
                      <span className="text-lg leading-none">+</span>
                    </button>
                  </div>

                  <div className="flex flex-col pl-4">
                    {group.sessions.map((session) => {
                      const isCurrent = session.friendlyId === activeFriendlyId
                      return (
                        <button
                          key={session.key}
                          type="button"
                          data-testid={`mobile-session-row-${session.friendlyId}`}
                          onClick={() => handleOpenSession(session)}
                          className={cn(
                            'flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-2.5 py-2 text-left transition-colors',
                            isCurrent
                              ? 'bg-[#0c3540]/70 text-[#c9d8db]'
                              : 'text-[#839496] active:bg-[#0c3540]',
                          )}
                        >
                          <span className="min-w-0 flex-1 truncate text-[15px]">
                            {sessionDisplayTitle(session)}
                          </span>
                          {isCurrent && waitingForResponse ? (
                            <span
                              className="size-2.5 shrink-0 rounded-full bg-[#268bd2]"
                              aria-label="Running"
                            />
                          ) : (
                            <span className="shrink-0 text-xs text-[#586e75] tabular-nums">
                              {formatCompactAge(session.updatedAt) || 'open'}
                            </span>
                          )}
                        </button>
                      )
                    })}

                    {group.observedCount > 0 ? (
                      <div className="mt-0.5">
                        <button
                          type="button"
                          data-testid={`mobile-observed-toggle-${group.service}`}
                          onClick={() => {
                            if (isObservedExpanded) {
                              setExpandedHomeObservedSvc(null)
                            } else {
                              setExpandedHomeObservedSvc(group.service)
                              void loadObservedForService(group.service)
                            }
                          }}
                          className="flex min-h-9 w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs text-[#586e75] active:bg-[#0c3540]"
                        >
                          <span>
                            Local CLI history ({group.observedCount})
                          </span>
                          <span aria-hidden="true">
                            {isObservedExpanded ? '▾' : '▸'}
                          </span>
                        </button>
                        {isObservedExpanded ? (
                          <div className="flex flex-col gap-1 py-1 pl-2">
                            {observedList.map((obs) => (
                              <div
                                key={obs.session_id}
                                className="rounded-lg border border-[#133b45] bg-[#06303b] px-2.5 py-2 text-xs text-[#839496]"
                              >
                                <div className="line-clamp-2 text-pretty text-[#93a1a1]">
                                  {obs.preview || obs.session_id}
                                </div>
                                <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-[#586e75]">
                                  <span className="truncate">{obs.cwd || obs.service}</span>
                                  <span className="shrink-0 tabular-nums">
                                    {formatCompactAge(obs.updated_at)}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </section>
              )
            })}
          </div>
        </div>

        {/* Bottom Antigravity Composer Card on Home */}
        <div className="shrink-0 px-3 pt-1 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div className="rounded-[24px] border border-[#1e444e] bg-[#0c3540] px-3.5 pt-3 pb-2.5">
            <textarea
              rows={1}
              data-testid="mobile-home-composer"
              value={homeDraft}
              onChange={(e) => setHomeDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSubmitFromHome()
                }
              }}
              placeholder="Ask anything, or dispatch a task…"
              className="min-h-[26px] max-h-28 w-full resize-none bg-transparent text-[15px] leading-[22px] text-[#c9d8db] placeholder:text-[#586e75] outline-none"
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <button
                  type="button"
                  data-testid="mobile-home-run-simple-task"
                  disabled={!canDispatchSelected || busyDemoService !== null}
                  aria-label="Spin up simple demo task"
                  onClick={() => void handleQuickDemoTask(selectedService)}
                  className="flex size-7 shrink-0 items-center justify-center rounded-full text-lg text-[#839496] active:bg-[#133b45] disabled:opacity-35"
                  title="Spin up simple agent task"
                >
                  +
                </button>
                <select
                  aria-label="Composer agent model"
                  data-testid="mobile-home-composer-service"
                  value={selectedService}
                  onChange={(e) => void onSelectService(e.target.value)}
                  className="min-w-0 truncate bg-transparent text-xs font-medium text-[#839496] outline-none"
                >
                  {services.map((svc) => (
                    <option
                      key={svc.service}
                      value={svc.service}
                      className="bg-[#002b36] text-[#c9d8db]"
                    >
                      {svc.display_name}{' '}
                      {svc.mode === 'dispatch' ? svc.default_model : '(observe)'}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                data-testid="mobile-home-send"
                disabled={!homeDraft.trim() || sending}
                aria-label="Send message"
                onClick={handleSubmitFromHome}
                className={cn(
                  'flex size-8 shrink-0 items-center justify-center rounded-full transition-colors',
                  homeDraft.trim() && !sending
                    ? 'bg-[#268bd2] text-[#002b36]'
                    : 'bg-[#133b45] text-[#586e75]',
                )}
              >
                <svg
                  viewBox="0 0 20 20"
                  className="size-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  aria-hidden="true"
                >
                  <path
                    d="M4.5 10h11M11 5.5L15.5 10 11 14.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <SettingsDialog
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          pathsLoading={pathsLoading}
          pathsError={pathsError}
          paths={paths}
          onClose={closeSettings}
          onCopySessionsDir={copySessionsDir}
          onCopyStorePath={copyStorePath}
        />
      </div>
    )
  }

  // ───────────────────────────────────────────────────────────────────────────
  // STAGE 2 & 3: FULL-SCREEN SESSION VIEW + FOOTER-TOGGLED DETAIL SHEET
  // ───────────────────────────────────────────────────────────────────────────
  return (
    <div
      data-testid="mobile-session-screen"
      className="relative flex h-dvh w-full flex-col overflow-hidden bg-[#002b36] text-[#c9d8db]"
    >
      {/* Top Session Segmented App Bar (matches Screenshot 3 & 4 + autobot & role chip) */}
      <header
        data-testid="mobile-session-top-bar"
        className={cn(
          'z-50 flex h-12 shrink-0 items-center gap-1.5 border-b border-[#133b45] px-2 transition-colors',
          mobileDetailOpen ? 'bg-[#002028]' : 'bg-[#002b36]',
        )}
      >
        <button
          type="button"
          data-testid="mobile-back-to-sessions"
          aria-label="Back to all sessions"
          onClick={() => {
            setMoreMenuOpen(false)
            onChangeMobileDetailOpen(false)
            onChangeMobileView('sessions')
          }}
          className="flex size-8 shrink-0 items-center justify-center rounded-lg text-[#839496] active:bg-[#0c3540]"
        >
          <svg
            viewBox="0 0 20 20"
            className="size-[18px]"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.7}
            aria-hidden="true"
          >
            <path
              d="M15.5 10H4.5M9 5.5L4.5 10 9 14.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        <AutobotBrandMark size="sm" />

        <div
          data-testid="mobile-session-header-title"
          className="min-w-0 flex-1 truncate px-0.5 text-[14px] font-medium text-[#c9d8db]"
        >
          {activeTitle}
        </div>

        <div className="relative flex shrink-0 items-center gap-0.5 rounded-xl border border-[#133b45] bg-[#0c3540]/80 p-0.5">
          <button
            type="button"
            data-testid="mobile-session-more-button"
            aria-label="Session actions"
            aria-expanded={moreMenuOpen}
            onClick={() => setMoreMenuOpen((prev) => !prev)}
            className="flex size-8 items-center justify-center rounded-lg text-[#839496] active:bg-[#133b45]"
          >
            <svg
              viewBox="0 0 20 20"
              className="size-4"
              fill="currentColor"
              aria-hidden="true"
            >
              <circle cx="10" cy="4.5" r="1.35" />
              <circle cx="10" cy="10" r="1.35" />
              <circle cx="10" cy="15.5" r="1.35" />
            </svg>
          </button>

          {moreMenuOpen ? (
            <div className="absolute right-10 top-10 z-50 w-52 rounded-xl border border-[#1e444e] bg-[#0c3540] p-1 shadow-xl">
              <button
                type="button"
                data-testid="mobile-menu-run-simple-task"
                disabled={!canDispatchSelected || busyDemoService !== null}
                onClick={() => {
                  setMoreMenuOpen(false)
                  void onRunSimpleTask(selectedService)
                }}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-[#c9d8db] active:bg-[#133b45] disabled:opacity-40"
              >
                <span>
                  {busyDemoService ? 'Spinning up…' : 'Run Simple Task'}
                </span>
                <span className="text-[#586e75]">{selectedService}</span>
              </button>
              <button
                type="button"
                data-testid="mobile-menu-pin-session"
                onClick={() => {
                  setMoreMenuOpen(false)
                  togglePinnedSession(activeCanonicalKey)
                }}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-[#c9d8db] active:bg-[#133b45]"
              >
                <span>
                  {isCurrentSessionPinned ? 'Unpin session' : 'Pin session'}
                </span>
              </button>
              <button
                type="button"
                data-testid="mobile-menu-export"
                disabled={displayMessages.length === 0}
                onClick={() => {
                  setMoreMenuOpen(false)
                  onExportMarkdown()
                }}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-[#c9d8db] active:bg-[#133b45] disabled:opacity-40"
              >
                <span>Export Markdown</span>
              </button>
            </div>
          ) : null}

          {/* The "Footer" Icon Button -> Toggles Detail Panel Sheet */}
          <button
            type="button"
            data-testid="mobile-footer-detail-button"
            aria-label="Toggle detail panel"
            aria-pressed={mobileDetailOpen}
            onClick={() => {
              setMoreMenuOpen(false)
              if (!mobileDetailOpen) {
                setDetailTab('overview')
              }
              onChangeMobileDetailOpen(!mobileDetailOpen)
            }}
            className={cn(
              'relative flex size-8 items-center justify-center rounded-lg transition-colors',
              mobileDetailOpen
                ? 'bg-[#1a414a] text-[#e6f0f2]'
                : 'text-[#839496] active:bg-[#133b45]',
            )}
          >
            <PanelFooterIcon active={mobileDetailOpen} />
            {!mobileDetailOpen && (needsReviewCount > 0 || activeRunCount > 0) ? (
              <span className="absolute right-1 top-1 size-1.5 rounded-full bg-[#268bd2]" />
            ) : null}
          </button>
        </div>
      </header>

      {dispatchError ? (
        <div
          data-testid="dispatch-error-banner"
          role="alert"
          className="flex shrink-0 items-center justify-between border-b border-red-500/40 bg-red-950/60 px-4 py-2 text-xs text-red-200"
        >
          <span className="min-w-0 flex-1 break-words">{dispatchError}</span>
          <button
            type="button"
            onClick={onDismissError}
            className="ml-3 shrink-0 underline"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {/* Full-Screen Session Message Stream */}
      <main className="flex flex-1 min-h-0 flex-col overflow-hidden">
        <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
          <ChatMessageList
            messages={displayMessages}
            loading={historyLoading}
            empty={historyEmpty}
            notice={gatewayNotice}
            noticePosition="end"
            waitingForResponse={waitingForResponse}
            sessionKey={activeCanonicalKey}
            pinToTop={pinToTop}
            pinGroupMinHeight={pinGroupMinHeight}
            headerHeight={headerHeight}
            contentStyle={stableContentStyle}
          />
        </div>

        {/* Bottom Antigravity Session Composer */}
        <div className="z-10 shrink-0 bg-[#002b36] px-3 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <div className="rounded-[24px] border border-[#1e444e] bg-[#0c3540] px-3.5 pt-2.5 pb-2.5">
            <AttachmentPreviewList
              attachments={attachments}
              onRemove={(id) =>
                setAttachments((prev) => prev.filter((a) => a.id !== id))
              }
            />
            <textarea
              rows={1}
              data-testid="mobile-session-composer"
              value={sessionDraft}
              onChange={(e) => setSessionDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSubmitFromSession()
                }
              }}
              placeholder="Ask anything…"
              className="min-h-[26px] max-h-32 w-full resize-none bg-transparent text-[15px] leading-[22px] text-[#c9d8db] placeholder:text-[#586e75] outline-none"
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-1.5">
                <AttachmentButton
                  onFileSelect={(file) =>
                    setAttachments((prev) => [...prev, file])
                  }
                  disabled={sending}
                  buttonProps={{
                    className:
                      'rounded-full text-[#839496] hover:bg-[#133b45] size-7',
                  }}
                />
                <select
                  aria-label="Session lead agent service"
                  data-testid="mobile-session-service-select"
                  value={selectedService}
                  onChange={(e) => void onSelectService(e.target.value)}
                  className="min-w-0 truncate bg-transparent text-xs font-medium text-[#839496] outline-none"
                >
                  {services.map((svc) => (
                    <option
                      key={svc.service}
                      value={svc.service}
                      className="bg-[#002b36] text-[#c9d8db]"
                    >
                      {svc.display_name}{' '}
                      {svc.mode === 'dispatch' ? svc.default_model : '(observe)'}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="button"
                data-testid="mobile-session-send"
                disabled={
                  (sessionDraft.trim().length === 0 &&
                    attachments.filter((a) => !a.error && a.base64).length ===
                      0) ||
                  sending
                }
                aria-label="Send message"
                onClick={handleSubmitFromSession}
                className={cn(
                  'flex size-8 shrink-0 items-center justify-center rounded-full transition-colors',
                  (sessionDraft.trim().length > 0 ||
                    attachments.some((a) => !a.error && a.base64)) &&
                    !sending
                    ? 'bg-[#268bd2] text-[#002b36]'
                    : 'bg-[#133b45] text-[#586e75]',
                )}
              >
                <svg
                  viewBox="0 0 20 20"
                  className="size-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  aria-hidden="true"
                >
                  <path
                    d="M4.5 10h11M11 5.5L15.5 10 11 14.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* STAGE 3: ANTIGRAVITY DETAIL PANEL SHEET (Screenshot 4) */}
      {mobileDetailOpen ? (
        <div
          data-testid="mobile-detail-sheet"
          className="absolute inset-x-0 top-12 bottom-0 z-40 flex flex-col bg-[#002028]/85"
        >
          <div className="flex flex-1 min-h-0 flex-col overflow-hidden rounded-t-2xl border-t border-[#1e444e] bg-[#002b36]">
            {/* Top Drag/Tap Handle */}
            <button
              type="button"
              data-testid="mobile-detail-close-handle"
              aria-label="Close detail panel"
              onClick={() => onChangeMobileDetailOpen(false)}
              className="flex w-full shrink-0 items-center justify-center py-2.5"
            >
              <span className="h-1 w-9 rounded-full bg-[#1e444e]" />
            </button>

            {/* Sheet Top Icon Toolbar + '+' Dispatch Action (Screenshot 4) */}
            <div className="flex shrink-0 items-center justify-between border-b border-[#133b45] px-3 pb-2.5">
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  data-testid="mobile-detail-tab-overview"
                  aria-label="Overview panel"
                  onClick={() => setDetailTab('overview')}
                  className={cn(
                    'flex size-8 items-center justify-center rounded-lg border transition-colors',
                    detailTab === 'overview'
                      ? 'border-[#27535e] bg-[#1a414a] text-[#e6f0f2]'
                      : 'border-transparent text-[#6b8184] active:bg-[#0c3540]',
                  )}
                >
                  <svg
                    viewBox="0 0 20 20"
                    className="size-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.6}
                    aria-hidden="true"
                  >
                    <rect x="3" y="3" width="14" height="14" rx="2.5" />
                    <path d="M6.5 7.5h7M6.5 10h7M6.5 12.5h4.5" strokeLinecap="round" />
                  </svg>
                </button>

                <button
                  type="button"
                  data-testid="mobile-detail-tab-queue"
                  aria-label="Chief review queue"
                  onClick={() => setDetailTab('queue')}
                  className={cn(
                    'flex size-8 items-center justify-center rounded-lg border transition-colors',
                    detailTab === 'queue'
                      ? 'border-[#27535e] bg-[#1a414a] text-[#e6f0f2]'
                      : 'border-transparent text-[#6b8184] active:bg-[#0c3540]',
                  )}
                >
                  <svg
                    viewBox="0 0 20 20"
                    className="size-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.6}
                    aria-hidden="true"
                  >
                    <path d="M5 3.5h7l3.5 3.5v9.5a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 16.5V5A1.5 1.5 0 0 1 5 3.5Z" />
                    <path d="M11.5 3.5V7H15" />
                  </svg>
                </button>

                <button
                  type="button"
                  data-testid="mobile-detail-tab-runs"
                  aria-label="Agent runs and terminals"
                  onClick={() => setDetailTab('runs')}
                  className={cn(
                    'flex size-8 items-center justify-center rounded-lg border transition-colors',
                    detailTab === 'runs'
                      ? 'border-[#27535e] bg-[#1a414a] text-[#e6f0f2]'
                      : 'border-transparent text-[#6b8184] active:bg-[#0c3540]',
                  )}
                >
                  <svg
                    viewBox="0 0 20 20"
                    className="size-4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.6}
                    aria-hidden="true"
                  >
                    <rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2" />
                    <path d="M6 8l2.5 2L6 12M10 12h4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </div>

              <button
                type="button"
                data-testid="mobile-detail-plus-task"
                disabled={!canDispatchSelected || busyDemoService !== null}
                aria-label="Run simple agent task"
                onClick={() => void onRunSimpleTask(selectedService)}
                className="flex size-8 items-center justify-center rounded-lg text-lg text-[#839496] active:bg-[#0c3540] disabled:opacity-35"
                title={
                  canDispatchSelected
                    ? `Run Simple Task (${selectedService})`
                    : `${selectedService} is observe-only`
                }
              >
                +
              </button>
            </div>

            {sheetError ? (
              <div className="border-b border-red-500/40 bg-red-950/50 px-4 py-2 text-xs text-red-200">
                {sheetError}
              </div>
            ) : null}

            {/* Sheet Body */}
            <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
              {detailTab === 'overview' ? (
                <div className="flex flex-col gap-3">
                  {/* Row 1: Lead Agents (Subagents equivalent) */}
                  <div>
                    <button
                      type="button"
                      data-testid="mobile-overview-agents-row"
                      onClick={() =>
                        setOpenSection((prev) =>
                          prev === 'agents' ? null : 'agents',
                        )
                      }
                      className="flex min-h-10 w-full items-center gap-2 text-left text-sm text-[#6b8184]"
                    >
                      <span>Lead Agents</span>
                      <span className="rounded-full bg-[#0b343f] px-2 py-0.5 text-xs text-[#839496] tabular-nums">
                        {services.length}
                      </span>
                      <span className="text-xs text-[#586e75]">
                        {openSection === 'agents' ? '▾' : '›'}
                      </span>
                    </button>
                    {openSection === 'agents' ? (
                      <div className="mt-1.5 flex flex-col gap-2 pl-1">
                        {services.map((svc) => (
                          <div
                            key={svc.service}
                            data-testid={`mobile-agent-card-${svc.service}`}
                            className="rounded-xl border border-[#133b45] bg-[#06303b] p-3 text-xs"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-[#c9d8db]">
                                {svc.display_name}
                              </span>
                              <span
                                data-testid={`mobile-agent-mode-${svc.service}`}
                                className="rounded bg-[#0c3540] px-1.5 py-0.5 font-mono text-[11px] text-[#839496]"
                              >
                                {svc.mode}
                              </span>
                            </div>
                            <div className="mt-1 text-[11px] text-[#6b8184]">
                              {svc.default_model || 'default'} ·{' '}
                              {svc.observed_sessions_count} local sessions
                            </div>
                            <div className="mt-2 flex items-center gap-2">
                              <button
                                type="button"
                                data-testid={`mobile-agent-demo-btn-${svc.service}`}
                                disabled={
                                  !svc.dispatch_ready || busyDemoService !== null
                                }
                                onClick={() => void onRunSimpleTask(svc.service)}
                                className="rounded-lg border border-[#27535e] bg-[#1a414a] px-2.5 py-1.5 font-medium text-[#e6f0f2] disabled:opacity-35"
                              >
                                {busyDemoService === svc.service
                                  ? 'Spinning up…'
                                  : 'Run Simple Task'}
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  {/* Row 2: Review Queue + inline filter pill (like Files Changed + Uncommitted pill) */}
                  <div>
                    <div className="flex min-h-10 items-center gap-2 text-sm text-[#6b8184]">
                      <button
                        type="button"
                        data-testid="mobile-overview-queue-row"
                        onClick={() =>
                          setOpenSection((prev) =>
                            prev === 'queue' ? null : 'queue',
                          )
                        }
                        className="flex items-center gap-2 text-left"
                      >
                        <span>Review Queue</span>
                        <span className="rounded-full bg-[#0b343f] px-2 py-0.5 text-xs text-[#839496] tabular-nums">
                          {items.length}
                        </span>
                        <span className="text-xs text-[#586e75]">
                          {openSection === 'queue' ? '▾' : '›'}
                        </span>
                      </button>
                      <select
                        aria-label="Filter queue status"
                        data-testid="mobile-queue-filter"
                        value={queueFilter}
                        onChange={(e) => setQueueFilter(e.target.value)}
                        className="ml-1 rounded-md border border-[#1e444e] bg-[#0c3540] px-2 py-1 text-xs text-[#93a1a1] outline-none"
                      >
                        <option value="">All items</option>
                        <option value="needs_review">Needs review</option>
                        <option value="queued">Queued</option>
                        <option value="landed">Landed</option>
                        <option value="done">Done</option>
                      </select>
                    </div>

                    {openSection === 'queue' ? (
                      <div className="mt-1.5 flex flex-col gap-2 pl-1">
                        {items.slice(0, 10).map((item) => {
                          const canApprove = DECISION_ALLOWED.approve.includes(
                            item.status,
                          )
                          const canReject = DECISION_ALLOWED.reject.includes(
                            item.status,
                          )
                          const canSnooze = DECISION_ALLOWED.snooze.includes(
                            item.status,
                          )
                          return (
                            <div
                              key={item.id}
                              data-testid={`mobile-queue-item-${item.id}`}
                              className="rounded-xl border border-[#133b45] bg-[#06303b] p-3 text-xs"
                            >
                              <div className="flex items-start justify-between gap-2">
                                <span className="font-medium text-[#c9d8db]">
                                  {item.title}
                                </span>
                                <span
                                  data-testid={`mobile-queue-status-${item.id}`}
                                  className="shrink-0 rounded bg-[#0c3540] px-1.5 py-0.5 font-mono text-[11px] text-[#93a1a1]"
                                >
                                  {item.status}
                                </span>
                              </div>
                              <div className="mt-1 text-[11px] text-[#6b8184] tabular-nums">
                                P{item.priority} · {item.kind} · {item.source_agent}
                              </div>
                              {item.result.test ? (
                                <div className="mt-1.5 font-mono text-[11px] text-[#839496]">
                                  Test exit {String(item.result.test.exit_code)} (
                                  {item.result.test.passed ? 'passed' : 'failed'})
                                </div>
                              ) : null}
                              {item.result.merged_commit ? (
                                <div className="mt-1 font-mono text-[11px] text-[#7aae66]">
                                  Landed: {item.result.merged_commit}
                                </div>
                              ) : null}
                              <div className="mt-2 flex flex-wrap gap-1.5">
                                <button
                                  type="button"
                                  data-testid={`mobile-approve-${item.id}`}
                                  disabled={!canApprove}
                                  onClick={() =>
                                    void decideQueueItem(item.id, 'approve')
                                  }
                                  className="rounded-lg bg-[#268bd2] px-2.5 py-1 font-medium text-[#002b36] disabled:opacity-30"
                                >
                                  Approve
                                </button>
                                <button
                                  type="button"
                                  disabled={!canReject}
                                  onClick={() =>
                                    void decideQueueItem(item.id, 'reject')
                                  }
                                  className="rounded-lg border border-[#1e444e] px-2.5 py-1 text-[#839496] disabled:opacity-30"
                                >
                                  Reject
                                </button>
                                {item.status === 'snoozed' ? (
                                  <button
                                    type="button"
                                    onClick={() => void wakeQueueItem(item.id)}
                                    className="rounded-lg border border-[#1e444e] px-2.5 py-1 text-[#839496]"
                                  >
                                    Wake
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    disabled={!canSnooze}
                                    onClick={() =>
                                      void decideQueueItem(item.id, 'snooze')
                                    }
                                    className="rounded-lg border border-[#1e444e] px-2.5 py-1 text-[#839496] disabled:opacity-30"
                                  >
                                    Snooze
                                  </button>
                                )}
                              </div>
                            </div>
                          )
                        })}
                        {items.length === 0 ? (
                          <div className="py-2 text-xs text-[#586e75]">
                            No queue items match this filter.
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>

                  {/* Row 3: Background Runs */}
                  <div>
                    <button
                      type="button"
                      data-testid="mobile-overview-runs-row"
                      onClick={() =>
                        setOpenSection((prev) =>
                          prev === 'runs' ? null : 'runs',
                        )
                      }
                      className="flex min-h-10 w-full items-center gap-2 text-left text-sm text-[#6b8184]"
                    >
                      <span>Background Runs</span>
                      <span className="rounded-full bg-[#0b343f] px-2 py-0.5 text-xs text-[#839496] tabular-nums">
                        {runs.length}
                      </span>
                      <span className="text-xs text-[#586e75]">
                        {openSection === 'runs' ? '▾' : '›'}
                      </span>
                    </button>
                    {openSection === 'runs' ? (
                      <div className="mt-1.5 flex flex-col gap-2 pl-1">
                        {runs.slice(0, 10).map((run) => (
                          <div
                            key={run.id}
                            data-testid={`mobile-run-card-${run.id}`}
                            className="rounded-xl border border-[#133b45] bg-[#06303b] p-3 text-xs"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono font-medium text-[#c9d8db]">
                                {run.service} · {run.id}
                              </span>
                              <span
                                data-testid={`mobile-run-state-${run.id}`}
                                className="rounded bg-[#0c3540] px-1.5 py-0.5 font-mono text-[11px] text-[#93a1a1]"
                              >
                                {run.state}
                              </span>
                            </div>
                            {run.branch ? (
                              <div className="mt-1 truncate font-mono text-[11px] text-[#6b8184]">
                                {run.branch}
                              </div>
                            ) : null}
                            {run.state === 'running' || run.state === 'queued' ? (
                              <button
                                type="button"
                                onClick={() => void stopAgentRun(run.id)}
                                className="mt-2 rounded-lg border border-[#1e444e] px-2.5 py-1 text-[#c9d8db]"
                              >
                                Stop run
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  {/* Row 4: Local Agent Stores (like Skills Used in Screenshot 4!) */}
                  <div>
                    <button
                      type="button"
                      data-testid="mobile-overview-stores-row"
                      onClick={() =>
                        setOpenSection((prev) =>
                          prev === 'observed' ? null : 'observed',
                        )
                      }
                      className="flex min-h-10 w-full items-center gap-2 text-left text-sm text-[#6b8184]"
                    >
                      <span>Connected Agent Stores</span>
                      <span className="rounded-full bg-[#0b343f] px-2 py-0.5 text-xs text-[#839496] tabular-nums">
                        {totalObservedCount}
                      </span>
                      <span className="text-xs text-[#586e75]">
                        {openSection === 'observed' ? '▾' : '›'}
                      </span>
                    </button>
                    <div className="mt-1 flex flex-col gap-2 pl-1">
                      {services.map((svc) => (
                        <div
                          key={`store-${svc.service}`}
                          className="flex items-center gap-2.5 text-sm"
                        >
                          <svg
                            viewBox="0 0 20 20"
                            className="size-4 shrink-0 text-[#586e75]"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth={1.5}
                            aria-hidden="true"
                          >
                            <path d="M5 3.5h7l3.5 3.5v9.5a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 16.5V5A1.5 1.5 0 0 1 5 3.5Z" />
                          </svg>
                          <span className="shrink-0 text-[#839496]">
                            {svc.service}
                          </span>
                          <span className="min-w-0 truncate text-xs text-[#586e75]">
                            {svc.store_path}
                          </span>
                        </div>
                      ))}
                      <div className="pt-1 text-[11px] text-[#586e75]">
                        Chief LLM: {chiefLlmStatus || 'deterministic'}
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}

              {detailTab === 'queue' ? (
                <div className="flex flex-col gap-2.5">
                  {items.map((item) => {
                    const isSel = selectedQueueItem?.id === item.id
                    const canApprove = DECISION_ALLOWED.approve.includes(
                      item.status,
                    )
                    return (
                      <div
                        key={item.id}
                        onClick={() => setSelectedItemId(item.id)}
                        className={cn(
                          'rounded-xl border p-3 text-xs',
                          isSel
                            ? 'border-[#27535e] bg-[#0c3540]'
                            : 'border-[#133b45] bg-[#06303b]',
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-medium text-[#c9d8db]">
                            {item.title}
                          </span>
                          <span className="rounded bg-[#002b36] px-1.5 py-0.5 font-mono text-[11px] text-[#93a1a1]">
                            {item.status}
                          </span>
                        </div>
                        {item.recommendation ? (
                          <div className="mt-1.5 text-[#839496]">
                            {item.recommendation}
                          </div>
                        ) : null}
                        {canApprove ? (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              void decideQueueItem(item.id, 'approve')
                            }}
                            className="mt-2 rounded-lg bg-[#268bd2] px-3 py-1 font-medium text-[#002b36]"
                          >
                            Approve & Land
                          </button>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              ) : null}

              {detailTab === 'runs' ? (
                <div className="flex flex-col gap-2.5">
                  {runs.map((run) => (
                    <div
                      key={run.id}
                      className="rounded-xl border border-[#133b45] bg-[#06303b] p-3 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono font-medium text-[#c9d8db]">
                          {run.service} · {run.id}
                        </span>
                        <span className="rounded bg-[#0c3540] px-1.5 py-0.5 font-mono text-[11px] text-[#93a1a1]">
                          {run.state}
                        </span>
                      </div>
                      <div className="mt-1 text-[11px] text-[#6b8184] tabular-nums">
                        {run.model || 'default'}
                        {typeof run.metadata.duration_s === 'number'
                          ? ` · ${run.metadata.duration_s}s`
                          : ''}
                        {run.queue_item_id ? ` · queue ${run.queue_item_id}` : ''}
                      </div>
                      {run.response_text ? (
                        <pre className="mt-2 max-h-28 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-[#133b45] bg-[#002b36] p-2 font-mono text-[11px] text-[#93a1a1]">
                          {run.response_text}
                        </pre>
                      ) : null}
                    </div>
                  ))}
                  {runs.length === 0 ? (
                    <div className="py-4 text-center text-xs text-[#586e75]">
                      No agent runs yet. Tap + in the top right to spin up a
                      simple task.
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
