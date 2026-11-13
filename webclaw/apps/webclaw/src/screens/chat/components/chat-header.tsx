import { memo } from 'react'
import { Link } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { Menu01Icon, SidebarLeft01Icon } from '@hugeicons/core-free-icons'
import { ContextMeter } from './context-meter'
import type { AgentServiceInfo } from './autoplan-inspector'
import { Button } from '@/components/ui/button'
import { ExportMenu } from '@/components/export-menu'
import { WebClawIconBig } from '@/components/icons/webclaw-big'
import { cn } from '@/lib/utils'

type ExportFormat = 'markdown' | 'json' | 'text'

type ChatHeaderProps = {
  activeTitle: string
  wrapperRef?: React.Ref<HTMLDivElement>
  showSidebarButton?: boolean
  onOpenSidebar?: () => void
  isSidebarCollapsed?: boolean
  onToggleSidebarCollapse?: () => void
  usedTokens?: number
  maxTokens?: number
  onExport: (format: ExportFormat) => void
  exportDisabled?: boolean
  showExport?: boolean
  services?: Array<AgentServiceInfo>
  selectedService?: string
  onSelectService?: (service: string) => void
  chiefLlmConfigured?: boolean
  chiefLlmStatus?: string
  needsReviewCount?: number
  onFocusOrchestratorQueue?: () => void
  onRunSimpleTask?: () => void
  runningSimpleTask?: boolean
  inspectorOpen?: boolean
  onToggleInspector?: () => void
}

function PanelToggleGlyph({ active }: { active?: boolean }) {
  return (
    <svg
      viewBox="0 0 18 18"
      className="size-3.5 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      aria-hidden="true"
    >
      <rect x="2.25" y="3" width="13.5" height="12" rx="2.25" />
      <path d="M11.25 3v12" />
      {active ? (
        <rect
          x="11.75"
          y="3.5"
          width="3.5"
          height="11"
          rx="1"
          fill="currentColor"
          stroke="none"
          opacity="0.35"
        />
      ) : null}
    </svg>
  )
}

function ChatHeaderComponent({
  activeTitle,
  wrapperRef,
  showSidebarButton = false,
  onOpenSidebar,
  isSidebarCollapsed = false,
  onToggleSidebarCollapse,
  usedTokens,
  maxTokens,
  onExport,
  exportDisabled = false,
  showExport = true,
  services = [],
  selectedService = '',
  onSelectService,
  chiefLlmConfigured = false,
  chiefLlmStatus = '',
  needsReviewCount = 0,
  onFocusOrchestratorQueue,
  onRunSimpleTask,
  runningSimpleTask = false,
  inspectorOpen = true,
  onToggleInspector,
}: ChatHeaderProps) {
  const activeSvcInfo = services.find((s) => s.service === selectedService)
  const canDispatchSelected = activeSvcInfo ? activeSvcInfo.dispatch_ready : true
  const chiefModeLabel = chiefLlmConfigured ? 'live' : 'triage'

  return (
    <header
      ref={wrapperRef}
      data-testid="desktop-top-app-bar"
      className="flex h-11 shrink-0 items-stretch border-b border-primary-200 bg-surface text-xs text-primary-900 select-none"
    >
      {/* Segment 1: Brand & Sessions Sidebar Rail (pixel-aligned to sidebar width) */}
      {onToggleSidebarCollapse ? (
        <div
          className={cn(
            'flex shrink-0 items-center border-r border-primary-200 bg-primary-100 transition-[width] duration-150',
            isSidebarCollapsed
              ? 'w-12 justify-center px-1'
              : 'w-[300px] justify-between px-2.5',
          )}
        >
          {!isSidebarCollapsed ? (
            <Link
              to="/new"
              data-testid="desktop-brand-link"
              className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-sm font-semibold tracking-tight text-primary-950 hover:bg-primary-200/70 transition-colors"
            >
              <WebClawIconBig className="size-6 rounded-md" />
              <span>autobot</span>
            </Link>
          ) : null}
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onToggleSidebarCollapse}
            aria-label={isSidebarCollapsed ? 'Open Sidebar' : 'Close Sidebar'}
            title={isSidebarCollapsed ? 'Open Sidebar' : 'Close Sidebar'}
            className="text-primary-700 hover:bg-primary-200/70 hover:text-primary-950"
          >
            <HugeiconsIcon icon={SidebarLeft01Icon} size={18} strokeWidth={1.6} />
          </Button>
        </div>
      ) : null}

      {/* Segment 2: Active Session Scope + Segmented Orchestrator & Lead-Agent Strip */}
      <div className="flex min-w-0 flex-1 items-center justify-between gap-3 px-3">
        <div className="flex min-w-0 items-center gap-2">
          {showSidebarButton ? (
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={onOpenSidebar}
              className="mr-0.5 text-primary-800 hover:bg-primary-100"
              aria-label="Open sidebar"
            >
              <HugeiconsIcon icon={Menu01Icon} size={16} strokeWidth={1.6} />
            </Button>
          ) : null}
          {isSidebarCollapsed ? (
            <Link
              to="/new"
              data-testid="desktop-brand-link"
              aria-label="autobot"
              className="flex shrink-0 items-center gap-1.5 rounded-lg px-1.5 py-1 text-sm font-semibold tracking-tight text-primary-950 hover:bg-primary-100"
            >
              <WebClawIconBig className="size-5 rounded" />
              <span>autobot</span>
            </Link>
          ) : null}
          <span
            data-testid="desktop-session-title"
            className="truncate text-[13px] font-medium text-primary-900"
          >
            {activeTitle}
          </span>
        </div>

        <div
          data-testid="desktop-orchestrator-segment"
          className="flex shrink-0 items-center gap-1 rounded-xl border border-primary-200 bg-primary-100 p-0.5"
        >
          <button
            type="button"
            data-testid="orchestrator-role-chip"
            onClick={onFocusOrchestratorQueue}
            title={`Chief of Staff orchestrator (${chiefLlmStatus || 'deterministic triage'}) — open review queue`}
            className="flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-primary-900 hover:bg-primary-200/80 transition-colors"
          >
            <span
              className={cn(
                'size-2 shrink-0 rounded-full',
                chiefLlmConfigured ? 'bg-[#268bd2]' : 'bg-[#7aae66]',
              )}
              aria-hidden="true"
            />
            <span className="text-primary-950">Chief</span>
            <span className="text-[11px] text-primary-600">{chiefModeLabel}</span>
            {needsReviewCount > 0 ? (
              <span
                data-testid="orchestrator-review-badge"
                className="ml-0.5 rounded-full bg-[#268bd2]/20 px-1.5 py-px font-mono text-[10px] font-semibold text-primary-950 tabular-nums"
              >
                {needsReviewCount}
              </span>
            ) : null}
          </button>

          {services.length > 0 && onSelectService ? (
            <>
              <span className="h-4 w-px bg-primary-200" aria-hidden="true" />
              <div className="relative flex h-7 items-center rounded-lg px-2 hover:bg-primary-200/70 transition-colors">
                <span
                  className={cn(
                    'size-2 shrink-0 rounded-full',
                    canDispatchSelected ? 'bg-[#7aae66]' : 'bg-primary-500',
                  )}
                  aria-hidden="true"
                />
                <select
                  aria-label="Lead agent service"
                  data-testid="agent-service-selector"
                  value={selectedService}
                  onChange={(e) => onSelectService(e.target.value)}
                  className="h-full cursor-pointer appearance-none bg-transparent pl-1.5 pr-5 text-xs font-medium text-primary-950 outline-none"
                >
                  {services.map((svc) => (
                    <option
                      key={svc.service}
                      value={svc.service}
                      className="bg-surface text-primary-900"
                    >
                      {svc.display_name}
                      {svc.mode === 'observe_only' ? ' (observe)' : ''}
                    </option>
                  ))}
                </select>
                <svg
                  viewBox="0 0 16 16"
                  className="pointer-events-none absolute right-1.5 size-3.5 text-primary-600"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.75}
                  aria-hidden="true"
                >
                  <path d="M4 6l4 4 4-4" />
                </svg>
              </div>
            </>
          ) : null}

          {onRunSimpleTask ? (
            <>
              <span className="h-4 w-px bg-primary-200" aria-hidden="true" />
              <button
                type="button"
                data-testid="header-run-simple-task"
                disabled={!canDispatchSelected || runningSimpleTask}
                onClick={onRunSimpleTask}
                title={
                  canDispatchSelected
                    ? 'Spin up a real isolated agent run and route commit to Chief review queue'
                    : activeSvcInfo?.auth_status ||
                      'Selected service is observe-only'
                }
                className="flex h-7 items-center rounded-lg border border-[#268bd2]/40 bg-[#268bd2]/15 px-2.5 text-xs font-medium text-primary-950 hover:bg-[#268bd2]/25 transition-colors disabled:opacity-35 disabled:pointer-events-none"
              >
                {runningSimpleTask ? 'Spinning up…' : '+ Simple Task'}
              </button>
            </>
          ) : null}
        </div>
      </div>

      {/* Segment 3: Session Telemetry, Export & Detail Panel Toggle */}
      <div className="flex shrink-0 items-center gap-1.5 border-l border-primary-200 px-2.5">
        <ContextMeter usedTokens={usedTokens} maxTokens={maxTokens} />
        {showExport ? (
          <ExportMenu onExport={onExport} disabled={exportDisabled} />
        ) : null}
        {onToggleInspector ? (
          <button
            type="button"
            data-testid="toggle-inspector"
            aria-pressed={inspectorOpen}
            onClick={onToggleInspector}
            className={cn(
              'relative flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors',
              inspectorOpen
                ? 'border-primary-300 bg-primary-100 text-primary-950'
                : 'border-transparent text-primary-700 hover:bg-primary-100 hover:text-primary-950',
            )}
          >
            <PanelToggleGlyph active={inspectorOpen} />
            <span>Inspector</span>
            {!inspectorOpen && needsReviewCount > 0 ? (
              <span className="size-1.5 rounded-full bg-[#268bd2]" />
            ) : null}
          </button>
        ) : null}
      </div>
    </header>
  )
}

const MemoizedChatHeader = memo(ChatHeaderComponent)

export { MemoizedChatHeader as ChatHeader }
