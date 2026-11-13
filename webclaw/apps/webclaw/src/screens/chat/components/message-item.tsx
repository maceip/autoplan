import { memo } from 'react'
import {
  getMessageTimestamp,
  getToolCallsFromMessage,
  textFromMessage,
} from '../utils'
import { MessageActionsBar } from './message-actions-bar'
import type {
  GatewayMessage,
  MessageContent as MessageContentPart,
  ToolCallContent,
} from '../types'
import type { ToolPart } from '@/components/prompt-kit/tool'
import { Message, MessageContent } from '@/components/prompt-kit/message'
import { Thinking } from '@/components/prompt-kit/thinking'
import { Tool } from '@/components/prompt-kit/tool'
import { useChatSettings } from '@/hooks/use-chat-settings'
import { cn } from '@/lib/utils'

type MessageItemProps = {
  message: GatewayMessage
  toolResultsByCallId?: Map<string, GatewayMessage>
  forceActionsVisible?: boolean
  wrapperRef?: React.RefObject<HTMLDivElement | null>
  wrapperClassName?: string
  wrapperScrollMarginTop?: number
}

function mapToolCallToToolPart(
  toolCall: ToolCallContent,
  resultMessage: GatewayMessage | undefined,
): ToolPart {
  const hasResult = resultMessage !== undefined
  const isError = resultMessage?.isError ?? false

  let state: ToolPart['state']
  if (!hasResult) {
    state = 'input-available'
  } else if (isError) {
    state = 'output-error'
  } else {
    state = 'output-available'
  }

  const resultText = toolResultText(resultMessage)

  // Extract error text from result message content
  let errorText: string | undefined
  if (isError) {
    errorText = resultText || 'Unknown error'
  }

  const output =
    resultMessage?.details && typeof resultMessage.details === 'object'
      ? resultMessage.details
      : resultText
        ? { text: resultText }
        : undefined

  return {
    type: toolCall.name || 'unknown',
    state,
    input: toolCall.arguments,
    output,
    toolCallId: toolCall.id,
    errorText,
  }
}

function toolResultText(resultMessage: GatewayMessage | undefined): string {
  if (!resultMessage) return ''
  const content = Array.isArray(resultMessage.content) ? resultMessage.content : []
  return content
    .map((part) => (part.type === 'text' ? String(part.text ?? '') : ''))
    .join('')
    .trim()
}

export function mapStandaloneToolResultToToolPart(message: GatewayMessage): ToolPart {
  const isError = Boolean(message.isError)
  const text = toolResultText(message)
  const output =
    message.details && typeof message.details === 'object'
      ? message.details
      : text
        ? { text }
        : undefined

  return {
    type:
      typeof message.toolName === 'string' && message.toolName.trim().length > 0
        ? message.toolName
        : 'tool',
    state: isError ? 'output-error' : 'output-available',
    output,
    toolCallId:
      typeof message.toolCallId === 'string' ? message.toolCallId : undefined,
    errorText: isError ? text || 'Unknown error' : undefined,
  }
}

export function assistantPartRenderOrder(
  message: GatewayMessage,
  showReasoningBlocks: boolean,
  showToolMessages: boolean,
): Array<'thinking' | 'text' | 'toolCall'> {
  const content = Array.isArray(message.content) ? message.content : []
  const order: Array<'thinking' | 'text' | 'toolCall'> = []
  for (const part of content) {
    if (part.type === 'thinking') {
      const thinking = String(part.thinking ?? '').trim()
      if (showReasoningBlocks && thinking) {
        order.push('thinking')
      }
      continue
    }
    if (part.type === 'text') {
      const text = String(part.text ?? '').trim()
      if (text) {
        order.push('text')
      }
      continue
    }
    if (showToolMessages) {
      order.push('toolCall')
    }
  }
  return order
}

function toolCallsSignature(message: GatewayMessage): string {
  const toolCalls = getToolCallsFromMessage(message)
  return toolCalls
    .map((toolCall) => {
      const id = toolCall.id ?? ''
      const name = toolCall.name ?? ''
      const partialJson = toolCall.partialJson ?? ''
      const args = toolCall.arguments ? JSON.stringify(toolCall.arguments) : ''
      return `${id}|${name}|${partialJson}|${args}`
    })
    .join('||')
}

function toolResultSignature(result: GatewayMessage | undefined): string {
  if (!result) return 'missing'
  const content = Array.isArray(result.content) ? result.content : []
  const text = content
    .map((part) => (part.type === 'text' ? String(part.text ?? '') : ''))
    .join('')
    .trim()
  const details = result.details ? JSON.stringify(result.details) : ''
  return `${result.toolCallId ?? ''}|${result.toolName ?? ''}|${result.isError ? '1' : '0'}|${text}|${details}`
}

function toolResultsSignature(
  message: GatewayMessage,
  toolResultsByCallId: Map<string, GatewayMessage> | undefined,
): string {
  if (!toolResultsByCallId) return ''
  const toolCalls = getToolCallsFromMessage(message)
  if (toolCalls.length === 0) return ''
  return toolCalls
    .map((toolCall) => {
      if (!toolCall.id) return 'missing'
      return toolResultSignature(toolResultsByCallId.get(toolCall.id))
    })
    .join('||')
}

function normalizeTimestamp(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (value < 1_000_000_000_000) return value * 1000
    return value
  }
  if (typeof value === 'string') {
    const parsed = Date.parse(value)
    if (!Number.isNaN(parsed)) return parsed
  }
  return null
}

function rawTimestamp(message: GatewayMessage): number | null {
  const candidates = [
    (message as any).createdAt,
    (message as any).created_at,
    (message as any).timestamp,
    (message as any).time,
    (message as any).ts,
  ]
  for (const candidate of candidates) {
    const normalized = normalizeTimestamp(candidate)
    if (normalized) return normalized
  }
  return null
}

function thinkingFromMessage(msg: GatewayMessage): string | null {
  const parts = Array.isArray(msg.content) ? msg.content : []
  const thinkingPart = parts.find((part) => part.type === 'thinking')
  if (thinkingPart && 'thinking' in thinkingPart) {
    return String(thinkingPart.thinking ?? '')
  }
  return null
}

/**
 * Represents an image attachment in message content.
 */
type ImagePart = {
  type: 'image'
  source: {
    type: 'base64'
    media_type: string
    data: string
  }
}

/**
 * Extracts image attachments from a gateway message.
 * @param msg - The gateway message to extract images from
 * @returns Array of image parts with base64 data
 */
function imagesFromMessage(msg: GatewayMessage): Array<ImagePart> {
  const parts = Array.isArray(msg.content) ? msg.content : []
  const images: Array<ImagePart> = []
  for (const part of parts) {
    const partType = (part as { type?: string }).type
    const imagePart = part as unknown as ImagePart
    if (
      partType === 'image' &&
      'source' in part &&
      typeof imagePart.source.data === 'string'
    ) {
      images.push(imagePart)
    }
  }
  return images
}

function MessageItemComponent({
  message,
  toolResultsByCallId,
  forceActionsVisible = false,
  wrapperRef,
  wrapperClassName,
  wrapperScrollMarginTop,
}: MessageItemProps) {
  const { settings } = useChatSettings()
  const role = message.role || 'assistant'
  const text = textFromMessage(message)
  const images = imagesFromMessage(message)
  const isUser = role === 'user'
  const isToolResult = role === 'toolResult'
  const isAssistant = role === 'assistant'
  const timestamp = getMessageTimestamp(message)
  const standaloneToolPart = isToolResult
    ? mapStandaloneToolResultToToolPart(message)
    : null

  const assistantParts = Array.isArray(message.content) ? message.content : []

  function renderAssistantPart(part: MessageContentPart, index: number) {
    if (part.type === 'thinking') {
      const thinking = String(part.thinking ?? '')
      if (!thinking || !settings.showReasoningBlocks) return null
      return (
        <div key={`thinking-${index}`} className="w-full max-w-[900px]">
          <Thinking content={thinking} />
        </div>
      )
    }

    if (part.type === 'text') {
      const chunk = String(part.text ?? '')
      if (!chunk.trim()) return null
      return (
        <Message key={`text-${index}`}>
          <MessageContent markdown className="text-primary-900 bg-transparent w-full">
            {chunk}
          </MessageContent>
        </Message>
      )
    }

    if (!settings.showToolMessages) return null
    const resultMessage = part.id ? toolResultsByCallId?.get(part.id) : undefined
    const toolPart = mapToolCallToToolPart(part, resultMessage)
    return (
      <div key={`tool-${part.id || index}`} className="w-full max-w-[900px] mt-1">
        <Tool toolPart={toolPart} defaultOpen={false} />
      </div>
    )
  }

  return (
    <div
      ref={wrapperRef}
      style={
        typeof wrapperScrollMarginTop === 'number'
          ? { scrollMarginTop: `${wrapperScrollMarginTop}px` }
          : undefined
      }
      className={cn(
        'group flex flex-col gap-1',
        wrapperClassName,
        isUser ? 'items-end' : 'items-start',
      )}
    >
      {/* Render images if present */}
      {isUser && images.length > 0 && (
        <div className={cn('flex flex-wrap gap-2 mb-2', 'justify-end')}>
          {images.map((img, idx) => (
            <img
              key={idx}
              src={`data:${img.source.media_type};base64,${img.source.data}`}
              alt={`Attachment ${idx + 1}`}
              className="max-w-[300px] max-h-[300px] rounded-lg object-cover"
            />
          ))}
        </div>
      )}
      {isUser && (
        <Message className="flex-row-reverse">
          <MessageContent
            markdown={false}
            className={cn('text-primary-900', 'bg-primary-100 px-4 py-2.5 max-w-[85%]')}
          >
            {text}
          </MessageContent>
        </Message>
      )}

      {isToolResult && settings.showToolMessages && standaloneToolPart && (
        <div className="w-full max-w-[900px] mt-2 flex flex-col gap-3">
          <Tool toolPart={standaloneToolPart} defaultOpen={false} />
        </div>
      )}

      {isAssistant && assistantParts.map(renderAssistantPart)}

      {isAssistant && (
        <MessageActionsBar
          text={text}
          timestamp={timestamp}
          align="start"
          forceVisible={forceActionsVisible}
        />
      )}

      {isUser && (
        <MessageActionsBar
          text={text}
          timestamp={timestamp}
          align="end"
          forceVisible={forceActionsVisible}
        />
      )}
    </div>
  )
}

function areMessagesEqual(
  prevProps: MessageItemProps,
  nextProps: MessageItemProps,
): boolean {
  if (prevProps.forceActionsVisible !== nextProps.forceActionsVisible) {
    return false
  }
  if (prevProps.wrapperClassName !== nextProps.wrapperClassName) return false
  if (prevProps.wrapperRef !== nextProps.wrapperRef) return false
  if (prevProps.wrapperScrollMarginTop !== nextProps.wrapperScrollMarginTop) {
    return false
  }
  if (
    (prevProps.message.role || 'assistant') !==
    (nextProps.message.role || 'assistant')
  ) {
    return false
  }
  if (
    textFromMessage(prevProps.message) !== textFromMessage(nextProps.message)
  ) {
    return false
  }
  if (
    thinkingFromMessage(prevProps.message) !==
    thinkingFromMessage(nextProps.message)
  ) {
    return false
  }
  if (
    toolCallsSignature(prevProps.message) !==
    toolCallsSignature(nextProps.message)
  ) {
    return false
  }
  if (
    toolResultsSignature(prevProps.message, prevProps.toolResultsByCallId) !==
    toolResultsSignature(nextProps.message, nextProps.toolResultsByCallId)
  ) {
    return false
  }
  if (
    (prevProps.message.role === 'toolResult' ||
      nextProps.message.role === 'toolResult') &&
    toolResultSignature(prevProps.message) !== toolResultSignature(nextProps.message)
  ) {
    return false
  }
  if (rawTimestamp(prevProps.message) !== rawTimestamp(nextProps.message)) {
    return false
  }
  // No need to check settings here as the hook will cause a re-render
  // and areMessagesEqual is for props only.
  // However, memo components with hooks will re-render if the hook state changes.
  return true
}

const MemoizedMessageItem = memo(MessageItemComponent, areMessagesEqual)

export { MemoizedMessageItem as MessageItem }
