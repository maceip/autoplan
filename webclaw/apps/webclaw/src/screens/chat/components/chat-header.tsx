import { memo } from 'react'
import { Link } from '@tanstack/react-router'
import { HugeiconsIcon } from '@hugeicons/react'
import { Menu01Icon, SidebarLeft01Icon } from '@hugeicons/core-free-icons'
import { ContextMeter } from './context-meter'
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
  needsReviewCount?: number
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
  needsReviewCount = 0,
  inspectorOpen = true,
  onToggleInspector,
}: ChatHeaderProps) {
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
              <WebClawIconBig className="size-6" />
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

      {/* Segment 2: Active Session Reading Header */}
      <div className="flex min-w-0 flex-1 items-center gap-2 px-3.5">
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
            <WebClawIconBig className="size-5" />
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
