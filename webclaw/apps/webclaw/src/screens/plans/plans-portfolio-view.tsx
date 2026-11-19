import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, Link } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  FolderGit2,
  Layers,
  LayoutGrid,
  List as ListIcon,
  Pin,
  PinOff,
  RefreshCw,
  Search,
} from 'lucide-react'
import { Badge } from '@astryxdesign/core/Badge'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Heading } from '@astryxdesign/core/Heading'
import { IconButton } from '@astryxdesign/core/IconButton'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@astryxdesign/core/SegmentedControl'
import { StatusDot } from '@astryxdesign/core/StatusDot'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'
import { ThemeAppearanceMenu } from '@/components/theme-appearance-menu'
import { useAstryxWorkbench } from '@/lib/astryx-theme'
import type { PlansViewMode } from '@/lib/astryx-theme'
import { cn } from '@/lib/utils'
import { ChatSidebar } from '../chat/components/chat-sidebar'
import { chatQueryKeys } from '../chat/chat-queries'
import { useChatSessions } from '../chat/hooks/use-chat-sessions'
import type { ProjectInfo } from '../chat/types'

export type PortfolioPlanCard = {
  id: string
  project_id: string
  project_name: string
  session_key: string
  session_friendly_id: string
  graph_type: string
  title: string
  goal: string
  state: string
  action_state: 'your_move' | 'working' | string
  status_line: string
  round: number
  max_rounds: number
  pinned: boolean
  preview_steps: Array<string>
  changed_files_count: number
  handoffs_count: number
  open_annotations_count: number
  created_at?: number
  updated_at?: number
}

export type PortfolioProjectGroup = {
  project: ProjectInfo
  collapsed: boolean
  plans: Array<PortfolioPlanCard>
  active_count: number
  gate_count: number
}

export type PortfolioResponse = {
  success: boolean
  now: Array<PortfolioPlanCard>
  pinned: Array<PortfolioPlanCard>
  by_project: Array<PortfolioProjectGroup>
  preferences: {
    theme_slug: string
    color_mode: string
    plans_view_mode: PlansViewMode
    pinned_plan_ids: Array<string>
    collapsed_project_ids: Array<string>
  }
}

type ProjectsApiResponse = {
  projects?: Array<ProjectInfo>
  default_project_id?: string
}

const INTERACTION_HOLD_MS = 4000

function badgeVariantForAction(
  actionState: string,
): 'warning' | 'info' | 'success' | 'error' | 'neutral' {
  if (actionState === 'your_move') return 'warning'
  if (actionState === 'working') return 'info'
  if (actionState === 'completed' || actionState === 'approved') return 'success'
  if (actionState === 'failed' || actionState === 'aborted') return 'error'
  return 'neutral'
}

function cardVariantForAction(
  actionState: string,
): 'orange' | 'blue' | 'default' {
  if (actionState === 'your_move') return 'orange'
  if (actionState === 'working') return 'blue'
  return 'default'
}

function statusDotForAction(
  actionState: string,
): 'warning' | 'accent' | 'success' | 'error' | 'neutral' {
  if (actionState === 'your_move') return 'warning'
  if (actionState === 'working') return 'accent'
  if (actionState === 'completed' || actionState === 'approved') return 'success'
  if (actionState === 'failed' || actionState === 'aborted') return 'error'
  return 'neutral'
}

export function PlansPortfolioView() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const {
    plansViewMode,
    pinnedPlanIds,
    collapsedProjectIds,
    setPlansViewMode,
    togglePinPlan,
    toggleCollapseProject,
  } = useAstryxWorkbench()

  const [searchQuery, setSearchQuery] = useState('')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [heldSnapshot, setHeldSnapshot] = useState<PortfolioResponse | null>(
    null,
  )
  const [heldCount, setHeldCount] = useState(0)
  const lastInteractionRef = useRef<number>(0)
  const flushTimerRef = useRef<number | null>(null)

  const { sessions, sessionsQuery } = useChatSessions({
    activeFriendlyId: 'main',
    isNewChat: false,
  })

  const projectsQuery = useQuery({
    queryKey: ['autoplan', 'projects'],
    queryFn: async (): Promise<ProjectsApiResponse> => {
      const res = await fetch('/api/autoplan/projects')
      if (!res.ok) throw new Error('Failed to load projects')
      return (await res.json()) as ProjectsApiResponse
    },
    refetchInterval: 10000,
  })

  const portfolioQuery = useQuery({
    queryKey: ['autoplan', 'portfolio'],
    queryFn: async (): Promise<PortfolioResponse> => {
      const res = await fetch('/api/autoplan/planai/portfolio')
      if (!res.ok) throw new Error('Failed to load plans portfolio')
      return (await res.json()) as PortfolioResponse
    },
    refetchInterval: 12000,
  })

  const applyHeldSnapshot = useCallback(() => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current)
      flushTimerRef.current = null
    }
    if (heldSnapshot) {
      queryClient.setQueryData(['autoplan', 'portfolio'], heldSnapshot)
    }
    setHeldSnapshot(null)
    setHeldCount(0)
  }, [heldSnapshot, queryClient])

  const markUserInteraction = useCallback(() => {
    lastInteractionRef.current = Date.now()
    if (heldCount > 0) {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current)
      }
      flushTimerRef.current = window.setTimeout(() => {
        applyHeldSnapshot()
      }, INTERACTION_HOLD_MS)
    }
  }, [applyHeldSnapshot, heldCount])

  useEffect(() => {
    if (typeof EventSource === 'undefined') return
    const source = new EventSource('/api/autoplan/events')
    const onLiveEvent = () => {
      void (async () => {
        try {
          const res = await fetch('/api/autoplan/planai/portfolio')
          if (!res.ok) return
          const fresh = (await res.json()) as PortfolioResponse
          const msSinceInteraction = Date.now() - lastInteractionRef.current
          if (msSinceInteraction < INTERACTION_HOLD_MS || searchQuery.trim()) {
            setHeldSnapshot(fresh)
            setHeldCount((prev) => prev + 1)
            if (flushTimerRef.current !== null) {
              window.clearTimeout(flushTimerRef.current)
            }
            flushTimerRef.current = window.setTimeout(() => {
              queryClient.setQueryData(['autoplan', 'portfolio'], fresh)
              setHeldSnapshot(null)
              setHeldCount(0)
            }, INTERACTION_HOLD_MS)
          } else {
            queryClient.setQueryData(['autoplan', 'portfolio'], fresh)
          }
        } catch {
          // Ignore transient SSE refresh failures
        }
      })()
    }
    for (const eventName of [
      'planai_workflow_updated',
      'queue_updated',
      'workflow_annotation_updated',
      'ui_preferences_updated',
    ]) {
      source.addEventListener(eventName, onLiveEvent)
    }
    return () => {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current)
      }
      source.close()
    }
  }, [queryClient, searchQuery])

  const projects = projectsQuery.data?.projects ?? []
  const defaultProjectId =
    projectsQuery.data?.default_project_id || projects[0]?.id || ''

  const portfolio = portfolioQuery.data
  const pinnedSet = useMemo(() => {
    const serverPins = portfolio?.preferences?.pinned_plan_ids ?? []
    return new Set([...serverPins, ...pinnedPlanIds])
  }, [pinnedPlanIds, portfolio?.preferences?.pinned_plan_ids])

  const collapsedSet = useMemo(() => {
    const serverCol = portfolio?.preferences?.collapsed_project_ids ?? []
    return new Set([...serverCol, ...collapsedProjectIds])
  }, [collapsedProjectIds, portfolio?.preferences?.collapsed_project_ids])

  const filterCard = useCallback(
    (card: PortfolioPlanCard) => {
      const q = searchQuery.trim().toLowerCase()
      if (!q) return true
      return (
        card.title.toLowerCase().includes(q) ||
        card.goal.toLowerCase().includes(q) ||
        card.project_name.toLowerCase().includes(q) ||
        card.status_line.toLowerCase().includes(q) ||
        card.preview_steps.some((step) => step.toLowerCase().includes(q))
      )
    },
    [searchQuery],
  )

  const filteredNow = useMemo(
    () => (portfolio?.now ?? []).filter(filterCard),
    [filterCard, portfolio?.now],
  )

  const allCards = useMemo(() => {
    const map = new Map<string, PortfolioPlanCard>()
    for (const c of portfolio?.now ?? []) map.set(c.id, c)
    for (const grp of portfolio?.by_project ?? []) {
      for (const c of grp.plans) map.set(c.id, c)
    }
    return Array.from(map.values())
  }, [portfolio])

  const filteredPinned = useMemo(() => {
    return allCards
      .filter((card) => pinnedSet.has(card.id))
      .filter(filterCard)
  }, [allCards, filterCard, pinnedSet])

  const filteredGroups = useMemo(() => {
    return (portfolio?.by_project ?? [])
      .map((grp) => ({
        ...grp,
        plans: grp.plans.filter(filterCard),
        collapsed: collapsedSet.has(grp.project.id),
      }))
      .filter(
        (grp) =>
          !searchQuery.trim() ||
          grp.plans.length > 0 ||
          grp.project.name.toLowerCase().includes(searchQuery.toLowerCase()),
      )
  }, [collapsedSet, filterCard, portfolio?.by_project, searchQuery])

  const openPlanSession = useCallback(
    (card: PortfolioPlanCard) => {
      const matched = sessions.find(
        (s) =>
          (card.session_key && s.key === card.session_key) ||
          (card.session_friendly_id &&
            s.friendlyId === card.session_friendly_id),
      )
      const targetFriendly =
        card.session_friendly_id || matched?.friendlyId || 'main'
      try {
        if (card.project_id) {
          window.sessionStorage.setItem(
            'autoplan-selected-project',
            card.project_id,
          )
        }
      } catch {
        // Ignore storage unavailability
      }
      void navigate({
        to: '/chat/$sessionKey',
        params: { sessionKey: targetFriendly },
      })
    },
    [navigate, sessions],
  )

  const handleCreateSessionInProject = useCallback(
    async (projectId: string) => {
      setCreatingSession(true)
      try {
        const res = await fetch('/api/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ projectId }),
        })
        if (!res.ok) return
        const created = (await res.json()) as { friendlyId?: string }
        await queryClient.invalidateQueries({ queryKey: chatQueryKeys.sessions })
        await sessionsQuery.refetch()
        if (created.friendlyId) {
          void navigate({
            to: '/chat/$sessionKey',
            params: { sessionKey: created.friendlyId },
          })
        }
      } finally {
        setCreatingSession(false)
      }
    },
    [navigate, queryClient, sessionsQuery],
  )

  const renderPlanItem = (card: PortfolioPlanCard) => {
    const isPinned = pinnedSet.has(card.id)
    const isRow = plansViewMode === 'rows'
    const metaRight =
      card.open_annotations_count > 0
        ? `${card.changed_files_count} files · ${card.open_annotations_count} notes`
        : `${card.changed_files_count} files · R${card.round}/${card.max_rounds}`

    if (isRow) {
      return (
        <Card
          key={card.id}
          variant={cardVariantForAction(card.action_state)}
          elevation="low"
          padding={3}
          data-testid={`portfolio-plan-card-${card.id}`}
          className="cursor-pointer transition-colors hover:border-border-strong"
          onClick={() => openPlanSession(card)}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <StatusDot
                variant={statusDotForAction(card.action_state)}
                label={card.action_state}
                isPulsing={card.action_state === 'working'}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-primary">
                  {card.title}
                </p>
                <p className="truncate text-xs text-secondary">
                  {card.project_name} · {metaRight}
                </p>
              </div>
            </div>
            <div
              className="flex shrink-0 items-center gap-2"
              onClick={(e) => e.stopPropagation()}
            >
              <Badge
                variant={badgeVariantForAction(card.action_state)}
                label={card.status_line}
              />
              <IconButton
                data-testid={`pin-plan-${card.id}`}
                variant="ghost"
                size="sm"
                label={isPinned ? 'Unpin plan' : 'Pin plan'}
                tooltip={isPinned ? 'Unpin plan' : 'Pin plan'}
                icon={
                  isPinned ? (
                    <PinOff className="size-3.5 text-accent" />
                  ) : (
                    <Pin className="size-3.5 text-secondary" />
                  )
                }
                onClick={() => {
                  void togglePinPlan(card.id)
                }}
              />
            </div>
          </div>
        </Card>
      )
    }

    return (
      <Card
        key={card.id}
        variant={cardVariantForAction(card.action_state)}
        elevation="low"
        padding={4}
        data-testid={`portfolio-plan-card-${card.id}`}
        className="flex cursor-pointer flex-col justify-between gap-3 transition-colors hover:border-border-strong"
        onClick={() => openPlanSession(card)}
      >
        <div className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <p className="line-clamp-2 text-sm font-semibold leading-snug text-primary">
                {card.title}
              </p>
              <p className="mt-0.5 truncate text-xs text-secondary">
                {card.project_name}
              </p>
            </div>
            <div
              className="shrink-0"
              onClick={(e) => e.stopPropagation()}
            >
              <IconButton
                data-testid={`pin-plan-${card.id}`}
                variant="ghost"
                size="sm"
                label={isPinned ? 'Unpin plan' : 'Pin plan'}
                tooltip={isPinned ? 'Unpin plan' : 'Pin plan'}
                icon={
                  isPinned ? (
                    <PinOff className="size-3.5 text-accent" />
                  ) : (
                    <Pin className="size-3.5 text-secondary" />
                  )
                }
                onClick={() => {
                  void togglePinPlan(card.id)
                }}
              />
            </div>
          </div>

          {card.preview_steps.length > 0 && (
            <ul className="space-y-1 pt-1">
              {card.preview_steps.slice(0, 3).map((step, idx) => (
                <li
                  key={`${card.id}-step-${idx}`}
                  className="flex items-start gap-2 text-xs text-secondary"
                >
                  <span
                    className="mt-1.5 size-1 shrink-0 rounded-full bg-secondary"
                    aria-hidden="true"
                  />
                  <span className="line-clamp-1">{step}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border pt-2.5">
          <Badge
            variant={badgeVariantForAction(card.action_state)}
            label={card.status_line}
          />
          <span className="text-xs text-secondary tabular-nums">
            {metaRight}
          </span>
        </div>
      </Card>
    )
  }

  return (
    <div className="h-screen overflow-hidden bg-body text-primary">
      <div className="grid h-full grid-cols-1 md:grid-cols-[auto_1fr]">
        <div className="hidden md:flex">
          <ChatSidebar
            sessions={sessions}
            projects={projects}
            activeProjectId={defaultProjectId}
            defaultProjectId={defaultProjectId}
            activeFriendlyId="main"
            creatingSession={creatingSession}
            onCreateSessionInProject={handleCreateSessionInProject}
            onProjectsChanged={() => void projectsQuery.refetch()}
            isCollapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <header
            data-testid="desktop-top-app-bar"
            className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border bg-surface px-4"
          >
            <div className="flex min-w-0 items-center gap-2.5">
              <Link
                to="/chat/$sessionKey"
                params={{ sessionKey: 'main' }}
                data-testid="desktop-brand-link"
                className="font-semibold tracking-tight text-primary hover:text-accent transition-colors"
              >
                autobot
              </Link>
              <span className="text-border" aria-hidden="true">
                /
              </span>
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-secondary">
                <Layers className="size-3.5" aria-hidden="true" />
                Plans Portfolio
              </span>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                icon={<ArrowLeft className="size-3.5" />}
                label="Workbench"
                onClick={() => {
                  void navigate({
                    to: '/chat/$sessionKey',
                    params: { sessionKey: 'main' },
                  })
                }}
              />
              <ThemeAppearanceMenu />
            </div>
          </header>

          <main
            data-testid="plans-portfolio-view"
            className="flex-1 overflow-y-auto px-4 py-6 md:px-8"
            onPointerMove={markUserInteraction}
            onWheel={markUserInteraction}
            onKeyDown={markUserInteraction}
          >
            <div className="mx-auto max-w-6xl space-y-8">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div className="space-y-1">
                  <Heading level={1} type="display-3">
                    Plans Across Products
                  </Heading>
                  <Text type="supporting" color="secondary" display="block">
                    Review active execution, pending human gates, and architectural plan history across your workspaces.
                  </Text>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {heldCount > 0 && (
                    <Button
                      data-testid="plans-held-updates-pill"
                      variant="secondary"
                      size="sm"
                      elevation="low"
                      icon={<RefreshCw className="size-3.5" />}
                      label={`${heldCount} live updates ready · Apply`}
                      onClick={applyHeldSnapshot}
                    />
                  )}
                  <div className="w-56 sm:w-64">
                    <TextInput
                      data-testid="plans-search-input"
                      label="Filter plans"
                      isLabelHidden
                      size="sm"
                      value={searchQuery}
                      hasClear
                      startIcon={<Search className="size-3.5" />}
                      placeholder="Filter plans or products..."
                      onChange={(val) => {
                        markUserInteraction()
                        setSearchQuery(val)
                      }}
                    />
                  </div>
                  <SegmentedControl
                    value={plansViewMode}
                    onChange={(val) => {
                      void setPlansViewMode(val as PlansViewMode)
                    }}
                    label="Portfolio view layout"
                    size="sm"
                  >
                    <SegmentedControlItem
                      value="cards"
                      label="Cards"
                      icon={<LayoutGrid className="size-3.5" />}
                      data-testid="plans-view-cards"
                    />
                    <SegmentedControlItem
                      value="rows"
                      label="List"
                      icon={<ListIcon className="size-3.5" />}
                      data-testid="plans-view-rows"
                    />
                  </SegmentedControl>
                </div>
              </div>

              {filteredPinned.length > 0 && (
                <section
                  data-testid="plans-pinned-section"
                  className="space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <Heading level={2} accessibilityLevel={2}>
                      Pinned Plans
                    </Heading>
                    <Badge
                      variant="neutral"
                      label={`${filteredPinned.length}`}
                    />
                  </div>
                  <div
                    className={cn(
                      plansViewMode === 'rows'
                        ? 'flex flex-col gap-2'
                        : 'grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3',
                    )}
                  >
                    {filteredPinned.map((card) => renderPlanItem(card))}
                  </div>
                </section>
              )}

              <section data-testid="plans-now-section" className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Heading level={2} accessibilityLevel={2}>
                      Now
                    </Heading>
                    <Badge
                      variant={filteredNow.length > 0 ? 'warning' : 'neutral'}
                      label={`${filteredNow.length} needing attention`}
                    />
                  </div>
                </div>
                {filteredNow.length === 0 ? (
                  <Card variant="muted" padding={5}>
                    <EmptyState
                      isCompact
                      title="No active gates or running plans right now"
                      description="Launch a plan in any workspace below or return to the workbench composer."
                    />
                  </Card>
                ) : (
                  <div
                    className={cn(
                      plansViewMode === 'rows'
                        ? 'flex flex-col gap-2'
                        : 'grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3',
                    )}
                  >
                    {filteredNow.map((card) => renderPlanItem(card))}
                  </div>
                )}
              </section>

              <section
                data-testid="plans-by-project-section"
                className="space-y-4 pb-8"
              >
                <div className="flex items-center justify-between">
                  <Heading level={2} accessibilityLevel={2}>
                    By Product
                  </Heading>
                  <Text type="supporting" color="secondary">
                    {filteredGroups.length} products
                  </Text>
                </div>

                {filteredGroups.length === 0 ? (
                  <Card variant="muted" padding={5}>
                    <EmptyState
                      isCompact
                      title="No products match this filter"
                      description="Clear your search query or add a workspace in the left sidebar."
                    />
                  </Card>
                ) : (
                  <div className="space-y-3">
                    {filteredGroups.map((group) => {
                      const pid = group.project.id
                      const isCollapsed = group.collapsed
                      const badgeText =
                        group.gate_count > 0
                          ? `${group.gate_count} gate · ${group.plans.length} plans`
                          : `${group.plans.length} plans`
                      return (
                        <Card
                          key={pid}
                          variant="default"
                          elevation="none"
                          padding={3}
                          data-testid={`portfolio-project-${pid}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <button
                              type="button"
                              data-testid={`toggle-collapse-project-${pid}`}
                              className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-muted"
                              onClick={() => {
                                void toggleCollapseProject(pid)
                              }}
                            >
                              {isCollapsed ? (
                                <ChevronRight className="size-4 shrink-0 text-secondary" />
                              ) : (
                                <ChevronDown className="size-4 shrink-0 text-secondary" />
                              )}
                              <FolderGit2 className="size-4 shrink-0 text-secondary" />
                              <span className="truncate text-sm font-semibold text-primary">
                                {group.project.name}
                              </span>
                            </button>
                            <div className="flex shrink-0 items-center gap-2">
                              <Badge
                                variant={
                                  group.gate_count > 0 ? 'warning' : 'neutral'
                                }
                                label={badgeText}
                              />
                              <Button
                                variant="ghost"
                                size="sm"
                                label="New session"
                                onClick={() => {
                                  void handleCreateSessionInProject(pid)
                                }}
                              />
                            </div>
                          </div>

                          {!isCollapsed && (
                            <div className="mt-3">
                              {group.plans.length === 0 ? (
                                <p className="px-2 py-2 text-xs text-secondary">
                                  No plans recorded yet for this product.
                                </p>
                              ) : (
                                <div
                                  className={cn(
                                    plansViewMode === 'rows'
                                      ? 'flex flex-col gap-2'
                                      : 'grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3',
                                  )}
                                >
                                  {group.plans.map((card) =>
                                    renderPlanItem(card),
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </Card>
                      )
                    })}
                  </div>
                )}
              </section>
            </div>
          </main>
        </div>
      </div>
    </div>
  )
}
