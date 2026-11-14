import type { QueryClient } from '@tanstack/react-query'

export type WorkspaceViewMode = 'workbench' | 'graph' | 'split'

export type ChatUiState = {
  isSidebarCollapsed: boolean
  isInspectorOpen: boolean
  mobileView: 'sessions' | 'session'
  mobileDetailOpen: boolean
  workspaceView: WorkspaceViewMode
}

const INSPECTOR_STORAGE_KEY = 'webclaw:inspector-open'

function readInitialWorkspaceView(): WorkspaceViewMode {
  if (typeof window === 'undefined') return 'workbench'
  try {
    const param = new URLSearchParams(window.location.search).get('view')
    if (param === 'graph' || param === 'split' || param === 'workbench') {
      return param
    }
  } catch {
    // ignore URL errors
  }
  return 'workbench'
}

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
  workspaceView: 'workbench',
}

export const chatUiQueryKey = ['chat', 'ui'] as const

export function getChatUiState(queryClient: QueryClient): ChatUiState {
  const cached = queryClient.getQueryData(chatUiQueryKey)
  if (cached && typeof cached === 'object') {
    return {
      ...defaultChatUiState,
      isInspectorOpen: readStoredInspectorOpen(),
      workspaceView: readInitialWorkspaceView(),
      ...(cached as Partial<ChatUiState>),
    }
  }
  return {
    ...defaultChatUiState,
    isInspectorOpen: readStoredInspectorOpen(),
    workspaceView: readInitialWorkspaceView(),
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
