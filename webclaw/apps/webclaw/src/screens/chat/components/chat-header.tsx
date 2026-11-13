import { memo } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { Menu01Icon } from '@hugeicons/core-free-icons'
import { ContextMeter } from './context-meter'
import type { AgentServiceInfo } from './autoplan-inspector'
import { Button } from '@/components/ui/button'
import { ExportMenu } from '@/components/export-menu'

type ExportFormat = 'markdown' | 'json' | 'text'

type ChatHeaderProps = {
  activeTitle: string
  wrapperRef?: React.Ref<HTMLDivElement>
  showSidebarButton?: boolean
  onOpenSidebar?: () => void
  usedTokens?: number
  maxTokens?: number
  onExport: (format: ExportFormat) => void
  exportDisabled?: boolean
  showExport?: boolean
  services?: Array<AgentServiceInfo>
  selectedService?: string
  onSelectService?: (service: string) => void
  onRunSimpleTask?: () => void
  runningSimpleTask?: boolean
  inspectorOpen?: boolean
  onToggleInspector?: () => void
}

function ChatHeaderComponent({
  activeTitle,
  wrapperRef,
  showSidebarButton = false,
  onOpenSidebar,
  usedTokens,
  maxTokens,
  onExport,
  exportDisabled = false,
  showExport = true,
  services = [],
  selectedService = '',
  onSelectService,
  onRunSimpleTask,
  runningSimpleTask = false,
  inspectorOpen = true,
  onToggleInspector,
}: ChatHeaderProps) {
  const activeSvcInfo = services.find((s) => s.service === selectedService)
  const canDispatchSelected = activeSvcInfo ? activeSvcInfo.dispatch_ready : true

  return (
    <div
      ref={wrapperRef}
      className="border-b border-primary-200 px-3 h-10 flex items-center bg-surface gap-2"
    >
      {showSidebarButton ? (
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={onOpenSidebar}
          className="mr-1 text-primary-800 hover:bg-primary-100"
          aria-label="Open sidebar"
        >
          <HugeiconsIcon icon={Menu01Icon} size={16} strokeWidth={1.6} />
        </Button>
      ) : null}
      <div className="flex-1 min-w-0 text-xs font-medium truncate">
        {activeTitle}
      </div>
      <div className="flex items-center gap-1.5 shrink-0 text-xs">
        {services.length > 0 && onSelectService ? (
          <select
            aria-label="Lead agent service"
            data-testid="agent-service-selector"
            value={selectedService}
            onChange={(e) => onSelectService(e.target.value)}
            className="h-7 border border-primary-300 bg-surface px-2 font-mono text-xs text-primary-900"
          >
            {services.map((svc) => (
              <option key={svc.service} value={svc.service}>
                {svc.display_name}
                {svc.mode === 'observe_only' ? ' (observe)' : ''}
              </option>
            ))}
          </select>
        ) : null}

        {onRunSimpleTask ? (
          <button
            type="button"
            data-testid="header-run-simple-task"
            disabled={!canDispatchSelected || runningSimpleTask}
            onClick={onRunSimpleTask}
            title={
              canDispatchSelected
                ? 'Spin up a real isolated agent run and route commit to Chief review queue'
                : activeSvcInfo?.auth_status || 'Selected service is observe-only'
            }
            className="h-7 border border-primary-800 bg-primary-900 px-2.5 font-medium text-surface disabled:opacity-35"
          >
            {runningSimpleTask ? 'Spinning up…' : 'Run Simple Task'}
          </button>
        ) : null}

        {showExport ? (
          <ExportMenu onExport={onExport} disabled={exportDisabled} />
        ) : null}
        <ContextMeter usedTokens={usedTokens} maxTokens={maxTokens} />

        {onToggleInspector ? (
          <button
            type="button"
            data-testid="toggle-inspector"
            aria-pressed={inspectorOpen}
            onClick={onToggleInspector}
            className={`h-7 border px-2 font-medium ${
              inspectorOpen
                ? 'border-primary-800 bg-primary-100 text-primary-900'
                : 'border-primary-300 text-primary-700 hover:bg-primary-50'
            }`}
          >
            Inspector
          </button>
        ) : null}
      </div>
    </div>
  )
}

const MemoizedChatHeader = memo(ChatHeaderComponent)

export { MemoizedChatHeader as ChatHeader }
