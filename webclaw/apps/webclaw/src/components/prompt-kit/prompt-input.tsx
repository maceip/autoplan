'use client'

import React, {
  createContext,
  memo,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  TooltipContent,
  TooltipRoot,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

type PromptInputValueContextType = {
  value: string
  setValue: (value: string) => void
  maxHeight: number | string
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
}

type PromptInputUiContextType = {
  isLoading: boolean
  onSubmit?: () => void
  disabled?: boolean
}

const PromptInputValueContext = createContext<PromptInputValueContextType>({
  value: '',
  setValue: () => {},
  maxHeight: 240,
  textareaRef: React.createRef<HTMLTextAreaElement>(),
})

const PromptInputUiContext = createContext<PromptInputUiContextType>({
  isLoading: false,
  onSubmit: undefined,
  disabled: false,
})

let globalPromptTarget: HTMLTextAreaElement | null = null
let isGlobalListenerBound = false

function bindGlobalPromptListener() {
  if (isGlobalListenerBound || typeof window === 'undefined') return
  isGlobalListenerBound = true
  window.addEventListener('keydown', (event) => {
    if (event.defaultPrevented) return
    if (event.metaKey || event.ctrlKey || event.altKey) return
    const target = event.target as HTMLElement | null
    if (!target) return
    const tag = target.tagName.toLowerCase()
    if (
      tag === 'input' ||
      tag === 'textarea' ||
      tag === 'select' ||
      target.isContentEditable
    ) {
      return
    }
    const isPrintable = event.key.length === 1
    const isEditKey = event.key === 'Backspace'
    if (!isPrintable && !isEditKey) return
    if (!globalPromptTarget || globalPromptTarget.disabled) return
    globalPromptTarget.focus()
  })
}

function usePromptInputValue() {
  return useContext(PromptInputValueContext)
}

function usePromptInputUi() {
  return useContext(PromptInputUiContext)
}

export type PromptInputProps = {
  isLoading?: boolean
  value?: string
  onValueChange?: (value: string) => void
  valueRef?: React.MutableRefObject<string>
  setValueRef?: React.MutableRefObject<((value: string) => void) | null>
  maxHeight?: number | string
  onSubmit?: () => void
  children: React.ReactNode
  className?: string
  disabled?: boolean
} & React.ComponentProps<'div'>

function PromptInput({
  className,
  isLoading = false,
  maxHeight = 240,
  value,
  onValueChange,
  valueRef,
  setValueRef,
  onSubmit,
  children,
  disabled = false,
  onClick,
  ...props
}: PromptInputProps) {
  const [internalValue, setInternalValue] = useState(value || '')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  bindGlobalPromptListener()

  function handleChange(newValue: string) {
    setInternalValue(newValue)
    onValueChange?.(newValue)
  }

  if (setValueRef) {
    setValueRef.current = function setValue(nextValue: string) {
      setInternalValue(nextValue)
      onValueChange?.(nextValue)
    }
  }

  if (valueRef) {
    valueRef.current = value ?? internalValue
  }

  function handleClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!disabled) textareaRef.current?.focus()
    onClick?.(e)
  }

  const valueContext = useMemo(
    () => ({
      value: value ?? internalValue,
      setValue: onValueChange ?? handleChange,
      maxHeight,
      textareaRef,
    }),
    [value, internalValue, onValueChange, maxHeight],
  )

  const uiContext = useMemo(
    () => ({
      isLoading,
      onSubmit,
      disabled,
    }),
    [disabled, isLoading, onSubmit],
  )

  return (
    <PromptInputUiContext.Provider value={uiContext}>
      <PromptInputValueContext.Provider value={valueContext}>
        <div
          onClick={handleClick}
          className={cn(
            'bg-surface cursor-text rounded-[22px] outline outline-ink/10 shadow-[0px_12px_32px_0px_rgba(0,0,0,0.05)] py-3 gap-3 flex flex-col',
            disabled && 'cursor-not-allowed opacity-60',
            className,
          )}
          {...props}
        >
          {children}
        </div>
      </PromptInputValueContext.Provider>
    </PromptInputUiContext.Provider>
  )
}

export type PromptInputTextareaProps = {
  disableAutosize?: boolean
  inputRef?: React.Ref<HTMLTextAreaElement>
} & React.ComponentProps<'textarea'>

function PromptInputTextarea({
  className,
  onKeyDown,
  disableAutosize = false,
  inputRef,
  ...props
}: PromptInputTextareaProps) {
  const { value, setValue, maxHeight, textareaRef } = usePromptInputValue()
  const { onSubmit, disabled } = usePromptInputUi()

  function adjustHeight(el: HTMLTextAreaElement | null) {
    if (!el || disableAutosize) return

    el.style.height = 'auto'
    const minHeight = 28
    const measured = Math.max(minHeight, el.scrollHeight)

    if (typeof maxHeight === 'number') {
      el.style.height = `${Math.min(measured, maxHeight)}px`
    } else {
      el.style.height = `min(${measured}px, ${maxHeight})`
    }
  }

  function handleRef(el: HTMLTextAreaElement | null) {
    textareaRef.current = el
    if (typeof inputRef === 'function') {
      inputRef(el)
    } else if (inputRef && 'current' in inputRef) {
      inputRef.current = el
    }
    if (el) {
      globalPromptTarget = el
    } else if (globalPromptTarget === el) {
      globalPromptTarget = null
    }
    adjustHeight(el)
  }

  useLayoutEffect(() => {
    if (!textareaRef.current || disableAutosize) return

    const el = textareaRef.current
    el.style.height = 'auto'
    const minHeight = 28
    const measured = Math.max(minHeight, el.scrollHeight)

    if (typeof maxHeight === 'number') {
      el.style.height = `${Math.min(measured, maxHeight)}px`
    } else {
      el.style.height = `min(${measured}px, ${maxHeight})`
    }
  }, [value, maxHeight, disableAutosize])

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    adjustHeight(e.target)
    setValue(e.target.value)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSubmit?.()
    }
    onKeyDown?.(e)
  }

  return (
    <textarea
      ref={handleRef}
      value={value}
      onChange={handleChange}
      onKeyDown={handleKeyDown}
      className={cn(
        'text-primary-950 min-h-[28px] w-full resize-none border-none bg-transparent shadow-none outline-none focus-visible:ring-0 pl-4 pr-1 text-[15px] leading-[22px] placeholder:text-primary-500',
        className,
      )}
      rows={1}
      readOnly={disabled}
      aria-disabled={disabled}
      {...props}
    />
  )
}

export type PromptInputActionsProps = React.HTMLAttributes<HTMLDivElement>

function PromptInputActions({
  children,
  className,
  ...props
}: PromptInputActionsProps) {
  return (
    <div className={cn('flex items-center gap-2', className)} {...props}>
      {children}
    </div>
  )
}

export type PromptInputActionProps = {
  className?: string
  tooltip: React.ReactNode
  render: (props: React.ComponentProps<'button'>) => React.ReactElement
  side?: 'top' | 'bottom' | 'left' | 'right'
} & React.ComponentProps<typeof TooltipRoot>

function PromptInputAction({
  tooltip,
  render,
  className,
  side = 'top',
  ...props
}: PromptInputActionProps) {
  const { disabled } = usePromptInputUi()

  return (
    <TooltipRoot {...props}>
      <TooltipTrigger
        render={(triggerProps) =>
          render({
            ...triggerProps,
            onClick: (event) => {
              triggerProps.onClick?.(event)
              event.stopPropagation()
            },
            disabled,
            className: undefined,
          })
        }
      />
      <TooltipContent side={side} className={className}>
        {tooltip}
      </TooltipContent>
    </TooltipRoot>
  )
}

const MemoizedPromptInputAction = memo(PromptInputAction)
MemoizedPromptInputAction.displayName = 'PromptInputAction'

export {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  MemoizedPromptInputAction as PromptInputAction,
}
