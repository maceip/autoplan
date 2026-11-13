import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'

import { clearHistoryMessages } from '../chat-queries'
import { resetPendingSend } from '../pending-send'
import type { QueryClient } from '@tanstack/react-query'

type UseChatRedirectInput = {
  activeFriendlyId: string
  isNewChat: boolean
  isRedirecting: boolean
  shouldRedirectToNew: boolean
  sessionsReady: boolean
  sessionKeyForHistory: string
  queryClient: QueryClient
  setIsRedirecting: (value: boolean) => void
}

export function useChatRedirect({
  activeFriendlyId,
  isNewChat,
  isRedirecting,
  shouldRedirectToNew,
  sessionsReady,
  sessionKeyForHistory,
  queryClient,
  setIsRedirecting,
}: UseChatRedirectInput) {
  const navigate = useNavigate()

  useEffect(() => {
    if (isRedirecting) {
      if (isNewChat) {
        setIsRedirecting(false)
        return
      }
      if (!shouldRedirectToNew && sessionsReady) {
        setIsRedirecting(false)
      }
    }

    if (isNewChat) return
    if (!sessionsReady) return
    if (!shouldRedirectToNew) return
    resetPendingSend()
    clearHistoryMessages(queryClient, activeFriendlyId, sessionKeyForHistory)
    navigate({ to: '/new', replace: true })
  }, [
    activeFriendlyId,
    isNewChat,
    navigate,
    queryClient,
    sessionKeyForHistory,
    sessionsReady,
    setIsRedirecting,
    shouldRedirectToNew,
  ])
}
