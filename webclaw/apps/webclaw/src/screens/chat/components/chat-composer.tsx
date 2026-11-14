import { memo, useCallback, useRef, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { ArrowUp02Icon } from '@hugeicons/core-free-icons'
import type { Ref } from 'react'

import type { AgentServiceInfo } from './autoplan-inspector'
import type { AttachmentFile } from '@/components/attachment-button'
import {
  PromptInput,
  PromptInputAction,
  PromptInputActions,
  PromptInputTextarea,
} from '@/components/prompt-kit/prompt-input'
import { Button } from '@/components/ui/button'
import { AttachmentButton } from '@/components/attachment-button'
import { AttachmentPreviewList } from '@/components/attachment-preview'
import { cn } from '@/lib/utils'
import { TooltipProvider } from '@/components/ui/tooltip'

type ChatComposerProps = {
  onSubmit: (value: string, helpers: ChatComposerHelpers) => void
  isLoading: boolean
  disabled: boolean
  wrapperRef?: Ref<HTMLDivElement>
  services?: Array<AgentServiceInfo>
  selectedService?: string
  onSelectService?: (service: string) => void
  sessionMode?: 'single' | 'team'
  onSelectMode?: (mode: 'single' | 'team') => void
  activeProjectName?: string
}

type ChatComposerHelpers = {
  reset: () => void
  setValue: (value: string) => void
  attachments?: Array<AttachmentFile>
}

function ChatComposerComponent({
  onSubmit,
  isLoading,
  disabled,
  wrapperRef,
  services = [],
  selectedService = '',
  onSelectService,
  sessionMode = 'single',
  onSelectMode,
  activeProjectName: _activeProjectName = '',
}: ChatComposerProps) {
  const [attachments, setAttachments] = useState<Array<AttachmentFile>>([])
  const promptRef = useRef<HTMLTextAreaElement | null>(null)
  const valueRef = useRef('')
  const setValueRef = useRef<((value: string) => void) | null>(null)

  const activeSvcInfo = services.find((s) => s.service === selectedService)
  const canDispatchSelected = activeSvcInfo ? activeSvcInfo.dispatch_ready : true

  const focusPrompt = useCallback(() => {
    if (typeof window === 'undefined') return
    window.requestAnimationFrame(() => {
      promptRef.current?.focus()
    })
  }, [])

  const reset = useCallback(() => {
    if (setValueRef.current) {
      setValueRef.current('')
    }
    setAttachments((prev) => {
      prev.forEach((attachment) => {
        if (attachment.preview) {
          URL.revokeObjectURL(attachment.preview)
        }
      })
      return []
    })
    focusPrompt()
  }, [focusPrompt])

  const handleFileSelect = useCallback((file: AttachmentFile) => {
    setAttachments((prev) => [...prev, file])
  }, [])

  const handleRemoveAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const removed = prev.find((attachment) => attachment.id === id)
      if (removed?.preview) {
        URL.revokeObjectURL(removed.preview)
      }
      return prev.filter((attachment) => attachment.id !== id)
    })
  }, [])

  const setComposerValue = useCallback(
    (nextValue: string) => {
      if (setValueRef.current) {
        setValueRef.current(nextValue)
      }
      focusPrompt()
    },
    [focusPrompt],
  )

  const handleSubmit = useCallback(() => {
    if (disabled) return
    const body = valueRef.current.trim()
    const validAttachments = attachments.filter((a) => !a.error && a.base64)
    if (body.length === 0 && validAttachments.length === 0) return
    onSubmit(body, {
      reset,
      setValue: setComposerValue,
      attachments: validAttachments,
    })
    focusPrompt()
  }, [disabled, focusPrompt, onSubmit, reset, setComposerValue, attachments])

  const submitDisabled = disabled

  return (
    <div
      className="mx-auto w-full max-w-full px-4 sm:px-5 sm:max-w-[760px] min-w-0 relative pb-3"
      ref={wrapperRef}
    >
      <TooltipProvider>
        <PromptInput
          valueRef={valueRef}
          setValueRef={setValueRef}
          onSubmit={handleSubmit}
          isLoading={isLoading}
          disabled={disabled}
        >
          <AttachmentPreviewList
            attachments={attachments}
            onRemove={handleRemoveAttachment}
          />
          <PromptInputTextarea
            placeholder={
              sessionMode === 'team'
                ? 'Describe a goal to split across parallel agents…'
                : 'Ask anything, or assign a task…'
            }
            inputRef={promptRef}
          />
          <PromptInputActions className="justify-between gap-2 px-2.5">
            <div className="flex min-w-0 items-center gap-2">
              <PromptInputAction
                tooltip="Attach file"
                render={(triggerProps) => (
                  <AttachmentButton
                    onFileSelect={handleFileSelect}
                    disabled={disabled}
                    buttonProps={{
                      ...triggerProps,
                      className: cn('rounded-full', triggerProps.className),
                    }}
                  />
                )}
              />

              {services.length > 0 && onSelectService ? (
                <div className="relative flex h-7 items-center rounded-md px-1.5 hover:bg-primary-100 transition-colors">
                  <span
                    className={cn(
                      'size-1.5 shrink-0 rounded-full',
                      canDispatchSelected ? 'bg-[#7aae66]' : 'bg-primary-500',
                    )}
                    aria-hidden="true"
                  />
                  <select
                    aria-label="Model"
                    data-testid="agent-service-selector"
                    value={selectedService}
                    onChange={(e) => onSelectService(e.target.value)}
                    className="h-full max-w-[168px] cursor-pointer truncate appearance-none bg-transparent pl-1.5 pr-4 text-xs font-medium text-primary-800 hover:text-primary-950 outline-none"
                  >
                    {services.map((svc) => (
                      <option
                        key={svc.service}
                        value={svc.service}
                        className="bg-surface text-primary-900"
                      >
                        {svc.display_name}
                        {svc.mode === 'observe_only' ? ' (read-only)' : ''}
                      </option>
                    ))}
                  </select>
                  <svg
                    viewBox="0 0 16 16"
                    className="pointer-events-none absolute right-1 size-3 text-primary-500"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.75}
                    aria-hidden="true"
                  >
                    <path d="M4 6l4 4 4-4" />
                  </svg>
                </div>
              ) : null}

              {onSelectMode ? (
                <div
                  data-testid="composer-mode-toggle"
                  role="group"
                  aria-label="Execution mode"
                  className="flex h-6 items-center rounded-md bg-primary-100 p-0.5 text-[11px]"
                >
                  <button
                    type="button"
                    data-testid="mode-single-btn"
                    aria-pressed={sessionMode === 'single'}
                    onClick={() => onSelectMode('single')}
                    className={cn(
                      'rounded px-2 py-0.5 font-medium transition-colors',
                      sessionMode === 'single'
                        ? 'bg-surface text-primary-950 shadow-2xs'
                        : 'text-primary-600 hover:text-primary-900',
                    )}
                  >
                    Single
                  </button>
                  <button
                    type="button"
                    data-testid="mode-team-btn"
                    aria-pressed={sessionMode === 'team'}
                    onClick={() => onSelectMode('team')}
                    className={cn(
                      'rounded px-2 py-0.5 font-medium transition-colors',
                      sessionMode === 'team'
                        ? 'bg-surface text-primary-950 shadow-2xs'
                        : 'text-primary-600 hover:text-primary-900',
                    )}
                  >
                    Team
                  </button>
                </div>
              ) : null}
            </div>

            <div className="flex items-center shrink-0">
              <PromptInputAction
                tooltip="Send"
                render={(triggerProps) => (
                  <Button
                    {...triggerProps}
                    onClick={(event) => {
                      triggerProps.onClick?.(event)
                      handleSubmit()
                    }}
                    disabled={submitDisabled || triggerProps.disabled}
                    size="icon-sm"
                    variant="default"
                    className={cn('rounded-full', triggerProps.className)}
                    aria-label="Send message"
                  >
                    <HugeiconsIcon
                      icon={ArrowUp02Icon}
                      size={18}
                      strokeWidth={1.6}
                    />
                  </Button>
                )}
              />
            </div>
          </PromptInputActions>
        </PromptInput>
      </TooltipProvider>
    </div>
  )
}

const MemoizedChatComposer = memo(ChatComposerComponent)

export { MemoizedChatComposer as ChatComposer }
export type { ChatComposerHelpers }
