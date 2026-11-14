import { memo } from 'react'
import { Link } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { Menu01Icon, SidebarLeft01Icon } from '@hugeicons/core-free-icons'
import type { WorkspaceViewMode } from '../chat-ui'
import { ContextMeter } from './context-meter'
import { Button } from '@/components/ui/button'
import { ExportMenu } from '@/components/export-menu'
import { WebClawIconBig } from '@/components/icons/webclaw-big'
import { cn } from '@/lib/utils'

type ExportFormat = 'markdown' | 'json' | 'text'

type ChatHeaderProps = {
  activeTitle: string
  activeProjectName?: string
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
  needsReviewCount?: number
  chiefLlmConfigured?: boolean
  chiefLlmStatus?: string
  onFocusOrchestratorQueue?: () => void
  workspaceView?: WorkspaceViewMode
  onChangeWorkspaceView?: (mode: WorkspaceViewMode) => void
  inspectorOpen?: boolean
  onToggleInspector?: () => void
}

function PanelToggleGlyph({ active }: { active?: boolean }) {
  return (
    <svg
      viewBox="0 0 18 18"
      className="size-4 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      aria-hidden="true"
    >
      <rect x="2.25" y="3" width="13.5" height="12" rx="2" />
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
  activeProjectName = '',
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
  needsReviewCount = 0,
  workspaceView = 'workbench',
  onChangeWorkspaceView,
  inspectorOpen = true,
  onToggleInspector,
}: ChatHeaderProps) {
  const isPlanActive = workspaceView === 'graph' || workspaceView === 'split'

  return (
    <header
      ref={wrapperRef}
      data-testid="desktop-top-app-bar"
      className="flex h-10 shrink-0 items-stretch border-b border-primary-200 bg-surface text-xs text-primary-900 select-none"
    >
      {onToggleSidebarCollapse ? (
        <div
          className={cn(
            'flex shrink-0 items-center border-r border-primary-200 bg-primary-100',
            isSidebarCollapsed
              ? 'w-12 justify-center px-1'
              : 'w-[272px] justify-between px-2.5',
          )}
        >
          {!isSidebarCollapsed ? (
            <Link
              to="/new"
              data-testid="desktop-brand-link"
              className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm font-semibold text-primary-950 hover:bg-primary-200/60 transition-colors"
            >
              <WebClawIconBig className="size-5" />
              <span>autobot</span>
            </Link>
          ) : null}
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onToggleSidebarCollapse}
            aria-label={isSidebarCollapsed ? 'Open sidebar' : 'Collapse sidebar'}
            className="text-primary-700 hover:bg-primary-200/60 hover:text-primary-950"
          >
            <HugeiconsIcon icon={SidebarLeft01Icon} size={17} strokeWidth={1.6} />
          </Button>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 items-center justify-between gap-3 px-3.5">
        <div className="flex min-w-0 items-center gap-1.5">
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
              className="flex shrink-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-sm font-semibold text-primary-950 hover:bg-primary-100"
            >
              <WebClawIconBig className="size-5" />
              <span>autobot</span>
            </Link>
          ) : null}
          {activeProjectName ? (
            <>
              <span
                data-testid="header-active-project"
                className="shrink-0 text-[13px] text-primary-600"
              >
                {activeProjectName}
              </span>
              <span className="text-primary-400" aria-hidden="true">
                /
              </span>
            </>
          ) : null}
          <span
            data-testid="desktop-session-title"
            className="truncate text-[13px] font-medium text-primary-950"
          >
            {activeTitle}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {onChangeWorkspaceView ? (
            <div
              data-testid="workspace-view-switcher"
              role="group"
              aria-label="View"
              className="flex items-center rounded-md bg-primary-100 p-0.5"
            >
              <button
                type="button"
                data-testid="view-mode-workbench"
                aria-pressed={!isPlanActive}
                onClick={() => onChangeWorkspaceView('workbench')}
                className={cn(
                  'rounded px-2.5 py-1 text-xs font-medium transition-colors',
                  !isPlanActive
                    ? 'bg-surface text-primary-950 shadow-2xs'
                    : 'text-primary-600 hover:text-primary-900',
                )}
              >
                Chat
              </button>
              <button
                type="button"
                data-testid="view-mode-graph"
                aria-pressed={isPlanActive}
                onClick={() => onChangeWorkspaceView('graph')}
                className={cn(
                  'rounded px-2.5 py-1 text-xs font-medium transition-colors',
                  isPlanActive
                    ? 'bg-surface text-primary-950 shadow-2xs'
                    : 'text-primary-600 hover:text-primary-900',
                )}
              >
                Plan
              </button>
            </div>
          ) : null}

          <ContextMeter usedTokens={usedTokens} maxTokens={maxTokens} />
          {showExport ? (
            <ExportMenu onExport={onExport} disabled={exportDisabled} />
          ) : null}

          {onToggleInspector ? (
            <button
              type="button"
              data-testid="toggle-inspector"
              aria-label={inspectorOpen ? 'Hide review panel' : 'Show review panel'}
              aria-pressed={inspectorOpen}
              onClick={onToggleInspector}
              className={cn(
                'flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium transition-colors',
                inspectorOpen
                  ? 'bg-primary-100 text-primary-950'
                  : 'text-primary-600 hover:bg-primary-100 hover:text-primary-950',
              )}
            >
              <PanelToggleGlyph active={inspectorOpen} />
              {needsReviewCount > 0 ? (
                <span
                  data-testid="orchestrator-review-badge"
                  className="rounded-full bg-[#268bd2]/20 px-1.5 py-px text-[10px] font-semibold text-primary-950 tabular-nums"
                >
                  {needsReviewCount}
                </span>
              ) : null}
            </button>
          ) : null}
        </div>
      </div>
    </header>
  )
}

const MemoizedChatHeader = memo(ChatHeaderComponent)

export { MemoizedChatHeader as ChatHeader }
