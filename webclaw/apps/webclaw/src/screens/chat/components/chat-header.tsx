import { memo } from 'react'
import { Link } from '@tanstack/react-router'
import { Menu, PanelLeft, PanelRight } from 'lucide-react'
import { Badge } from '@astryxdesign/core/Badge'
import { Button } from '@astryxdesign/core/Button'
import { IconButton } from '@astryxdesign/core/IconButton'
import { ExportMenu } from '@/components/export-menu'
import { WebClawIconBig } from '@/components/icons/webclaw-big'
import { ThemeAppearanceMenu } from '@/components/theme-appearance-menu'
import { ContextMeter } from './context-meter'

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
  inspectorOpen?: boolean
  onToggleInspector?: () => void
}

function ChatHeaderComponent({
  activeTitle,
  activeProjectName,
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
      className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border bg-surface px-3 text-primary"
    >
      <div className="flex min-w-0 items-center gap-2">
        {isSidebarCollapsed && !showSidebarButton ? (
          <div className="flex items-center gap-1.5">
            <Link
              to="/chat/$sessionKey"
              params={{ sessionKey: 'new' }}
              data-testid="desktop-brand-link"
              className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-sm font-semibold tracking-tight text-primary transition-colors hover:bg-muted"
            >
              <WebClawIconBig className="size-4.5 rounded-sm" />
              <span>autobot</span>
            </Link>
            {onToggleSidebarCollapse ? (
              <IconButton
                variant="ghost"
                size="sm"
                label="Expand sidebar"
                tooltip="Expand sidebar"
                icon={<PanelLeft className="size-4" />}
                onClick={onToggleSidebarCollapse}
              />
            ) : null}
          </div>
        ) : null}

        {showSidebarButton ? (
          <div className="flex items-center gap-1.5">
            <IconButton
              variant="ghost"
              size="sm"
              label="Open navigation"
              icon={<Menu className="size-4" />}
              onClick={onOpenSidebar}
            />
            <Link
              to="/chat/$sessionKey"
              params={{ sessionKey: 'new' }}
              data-testid="desktop-brand-link"
              className="flex items-center gap-1.5 text-sm font-semibold tracking-tight text-primary"
            >
              <WebClawIconBig className="size-4 rounded-sm" />
              <span>autobot</span>
            </Link>
          </div>
        ) : null}

        {activeProjectName ? (
          <Badge
            variant="neutral"
            data-testid="header-active-project"
            label={activeProjectName}
          />
        ) : null}

        <span
          data-testid="desktop-session-title"
          className="min-w-0 truncate text-xs font-medium text-secondary"
        >
          {activeTitle}
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <ContextMeter usedTokens={usedTokens} maxTokens={maxTokens} />
        {showExport ? (
          <ExportMenu onExport={onExport} disabled={exportDisabled} />
        ) : null}
        <ThemeAppearanceMenu />

        {onToggleInspector ? (
          <Button
            data-testid="toggle-inspector"
            variant={inspectorOpen ? 'secondary' : 'ghost'}
            size="sm"
            icon={<PanelRight className="size-3.5" />}
            label="Review"
            aria-label={inspectorOpen ? 'Hide review panel' : 'Show review panel'}
            aria-pressed={inspectorOpen}
            onClick={onToggleInspector}
            endContent={
              needsReviewCount > 0 ? (
                <Badge
                  data-testid="orchestrator-review-badge"
                  variant="warning"
                  label={`${needsReviewCount}`}
                />
              ) : null
            }
          />
        ) : null}
      </div>
    </header>
  )
}

const MemoizedChatHeader = memo(ChatHeaderComponent)

export { MemoizedChatHeader as ChatHeader }
