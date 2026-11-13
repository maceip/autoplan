import { useLayoutEffect, useState } from 'react'
import { setChatUiState } from '../chat-ui'
import type { QueryClient } from '@tanstack/react-query'


function detectMobileViewport(): boolean {
  if (typeof window === 'undefined') return false
  if (window.matchMedia('(max-width: 768px)').matches) return true
  const coarsePointer = window.matchMedia('(pointer: coarse)').matches
  const minScreenEdge = Math.min(
    window.screen.width || window.innerWidth,
    window.screen.height || window.innerHeight,
  )
  if (coarsePointer && minScreenEdge > 0 && minScreenEdge <= 540) {
    return true
  }
  if (
    /Android|iPhone|iPod|Mobile/i.test(navigator.userAgent) &&
    window.innerWidth <= 1024
  ) {
    return true
  }
  return false
}

export function useChatMobile(queryClient: QueryClient) {
  const [isMobile, setIsMobile] = useState(false)

  useLayoutEffect(() => {
    const media = window.matchMedia('(max-width: 768px)')
    const pointerMedia = window.matchMedia('(pointer: coarse)')
    const update = () => setIsMobile(detectMobileViewport())
    update()
    media.addEventListener('change', update)
    pointerMedia.addEventListener('change', update)
    window.addEventListener('resize', update)
    return () => {
      media.removeEventListener('change', update)
      pointerMedia.removeEventListener('change', update)
      window.removeEventListener('resize', update)
    }
  }, [])

  useLayoutEffect(() => {
    if (!isMobile) return
    setChatUiState(queryClient, function collapse(state) {
      return { ...state, isSidebarCollapsed: true }
    })
  }, [isMobile, queryClient])

  return { isMobile }
}
