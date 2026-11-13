import { useEffect, useRef } from 'react'

import { setPendingGeneration } from '../pending-send'

type UseChatGenerationGuardInput = {
  waitingForResponse: boolean
  refreshHistory: () => void
  setWaitingForResponse: (value: boolean) => void
}

export function useChatGenerationGuard({
  waitingForResponse,
  refreshHistory,
  setWaitingForResponse,
}: UseChatGenerationGuardInput) {
  const timeoutTimer = useRef<number | null>(null)
  const waitingRef = useRef(waitingForResponse)
  waitingRef.current = waitingForResponse

  function finish() {
    setPendingGeneration(false)
    setWaitingForResponse(false)
  }

  useEffect(() => {
    if (!waitingForResponse) {
      if (timeoutTimer.current) {
        window.clearTimeout(timeoutTimer.current)
        timeoutTimer.current = null
      }
      return
    }

    if (!timeoutTimer.current) {
      timeoutTimer.current = window.setTimeout(() => {
        timeoutTimer.current = null
        if (!waitingRef.current) return
        refreshHistory()
        finish()
      }, 120000)
    }

  }, [
    refreshHistory,
    setWaitingForResponse,
    waitingForResponse,
  ])
}
