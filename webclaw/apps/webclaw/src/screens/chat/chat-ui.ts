import type { QueryClient } from '@tanstack/react-query'

export type ChatUiState = {
  isSidebarCollapsed: boolean
  isInspectorOpen: boolean
  mobileView: 'sessions' | 'session'
  mobileDetailOpen: boolean
}

const INSPECTOR_STORAGE_KEY = 'webclaw:inspector-open'

function readStoredInspectorOpen(): boolean {
  if (typeof window === 'undefined') return true
  try {
    const raw = window.localStorage.getItem(INSPECTOR_STORAGE_KEY)
    if (raw === 'false') return false
    if (raw === 'true') return true
  } catch {
    // ignore storage errors
  }
  return true
}

const defaultChatUiState: ChatUiState = {
  isSidebarCollapsed: false,
  isInspectorOpen: true,
  mobileView: 'sessions',
  mobileDetailOpen: false,
}

export const chatUiQueryKey = ['chat', 'ui'] as const

export function getChatUiState(queryClient: QueryClient): ChatUiState {
  const cached = queryClient.getQueryData(chatUiQueryKey)
  if (cached && typeof cached === 'object') {
    return {
      ...defaultChatUiState,
      isInspectorOpen: readStoredInspectorOpen(),
      ...(cached as Partial<ChatUiState>),
    }
  }
  return {
    ...defaultChatUiState,
    isInspectorOpen: readStoredInspectorOpen(),
  }
}

export function setChatUiState(
  queryClient: QueryClient,
  updater: (state: ChatUiState) => ChatUiState,
) {
  queryClient.setQueryData(chatUiQueryKey, function update(state: unknown) {
    const current =
      state && typeof state === 'object'
        ? {
            ...defaultChatUiState,
            isInspectorOpen: readStoredInspectorOpen(),
            ...(state as Partial<ChatUiState>),
          }
        : {
            ...defaultChatUiState,
            isInspectorOpen: readStoredInspectorOpen(),
          }
    const next = updater(current)
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(
          INSPECTOR_STORAGE_KEY,
          String(next.isInspectorOpen),
        )
      } catch {
        // ignore storage errors
      }
    }
    return next
  })
}
