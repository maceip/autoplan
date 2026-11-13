import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deriveFriendlyIdFromKey,
  isMissingGatewayAuth,
  isSessionNotFound,
  readError,
} from './utils'
import { createOptimisticMessage } from './chat-screen-utils'
import {
  appendHistoryMessage,
  chatQueryKeys,
  clearHistoryMessages,
  fetchGatewayStatus,
  removeHistoryMessageByClientId,
  updateHistoryMessageByClientId,
  updateSessionLastMessage,
} from './chat-queries'
import { chatUiQueryKey, getChatUiState, setChatUiState } from './chat-ui'
import { ChatSidebar } from './components/chat-sidebar'
import { ChatHeader } from './components/chat-header'
import { ChatMessageList } from './components/chat-message-list'
import { ChatComposer } from './components/chat-composer'
import { GatewayStatusMessage } from './components/gateway-status-message'
import { AutoplanInspector } from './components/autoplan-inspector'
import type { AgentServiceInfo } from './components/autoplan-inspector'
import { MobileAntigravityWorkbench } from './components/mobile-antigravity-workbench'
import type { MobileStageView } from './components/mobile-antigravity-workbench'
import {
  hasPendingGeneration,
  hasPendingSend,
  isRecentSession,
  setPendingGeneration,
  setRecentSession,
  stashPendingSend,
} from './pending-send'
import { useChatMeasurements } from './hooks/use-chat-measurements'
import { useChatHistory } from './hooks/use-chat-history'
import { useChatMobile } from './hooks/use-chat-mobile'
import { useChatSessions } from './hooks/use-chat-sessions'
import { useChatStream } from './hooks/use-chat-stream'
import { useChatPendingSend } from './hooks/use-chat-pending-send'
import { useChatGenerationGuard } from './hooks/use-chat-generation-guard'
import { shouldRedirectToConnect } from './hooks/use-chat-error-state'
import { useChatRedirect } from './hooks/use-chat-redirect'
import type { AttachmentFile } from '@/components/attachment-button'
import type { ChatComposerHelpers } from './components/chat-composer'
import { useExport } from '@/hooks/use-export'
import { useChatSettings } from '@/hooks/use-chat-settings'
import { cn, randomUUID } from '@/lib/utils'

type ChatScreenProps = {
  activeFriendlyId: string
  isNewChat?: boolean
  onSessionResolved?: (payload: {
    sessionKey: string
    friendlyId: string
  }) => void
  forcedSessionKey?: string
}

type AgentsApiResponse = {
  success?: boolean
  services?: Array<AgentServiceInfo>
  default_service?: string
}

type QueueStatsResponse = {
  success?: boolean
  counts?: Record<string, number>
  chief?: {
    llm_configured?: boolean
    llm_status?: string
  }
}

export function ChatScreen({
  activeFriendlyId,
  isNewChat = false,
  onSessionResolved,
  forcedSessionKey,
}: ChatScreenProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [sending, setSending] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [isRedirecting, setIsRedirecting] = useState(false)
  const [newChatService, setNewChatService] = useState<string>('')
  const [busyDemoService, setBusyDemoService] = useState<string | null>(null)
  const [dispatchError, setDispatchError] = useState<string>('')
  const [inspectorTab, setInspectorTab] = useState<'queue' | 'agents' | 'runs'>(
    'queue',
  )
  const { headerRef, composerRef, mainRef, pinGroupMinHeight, headerHeight } =
    useChatMeasurements()
  const [waitingForResponse, setWaitingForResponse] = useState(
    () => hasPendingSend() || hasPendingGeneration(),
  )
  const [pinToTop, setPinToTop] = useState(
    () => hasPendingSend() || hasPendingGeneration(),
  )
  const { settings } = useChatSettings()
  const pendingRunIdsRef = useRef(new Set<string>())
  const pendingRunTimersRef = useRef(new Map<string, number>())
  const { isMobile } = useChatMobile(queryClient)
  const {
    sessionsQuery,
    sessions,
    activeSession,
    activeExists,
    activeSessionKey,
    activeTitle,
    sessionsError,
  } = useChatSessions({ activeFriendlyId, isNewChat, forcedSessionKey })
  const {
    historyQuery,
    displayMessages,
    historyError,
    resolvedSessionKey,
    activeCanonicalKey,
    sessionKeyForHistory,
  } = useChatHistory({
    activeFriendlyId,
    activeSessionKey,
    forcedSessionKey,
    isNewChat,
    isRedirecting,
    activeExists,
    sessionsReady: sessionsQuery.isSuccess,
    queryClient,
  })

  const agentsQuery = useQuery({
    queryKey: ['autoplan', 'agents'],
    queryFn: async (): Promise<AgentsApiResponse> => {
      const res = await fetch('/api/autoplan/agents')
      if (!res.ok) throw new Error(await readError(res))
      return (await res.json()) as AgentsApiResponse
    },
    refetchInterval: 8000,
  })

  const queueStatsQuery = useQuery({
    queryKey: ['autoplan', 'queue-stats'],
    queryFn: async (): Promise<QueueStatsResponse> => {
      const res = await fetch('/api/autoplan/queue/stats')
      if (!res.ok) throw new Error(await readError(res))
      return (await res.json()) as QueueStatsResponse
    },
    refetchInterval: 8000,
  })

  const services = agentsQuery.data?.services ?? []
  const defaultService =
    agentsQuery.data?.default_service ?? services[0]?.service ?? 'antigravity'
  const selectedService = isNewChat
    ? newChatService || defaultService
    : activeSession?.service || defaultService
  const chiefLlmStatus = queueStatsQuery.data?.chief?.llm_status ?? ''
  const chiefLlmConfigured = Boolean(
    queueStatsQuery.data?.chief?.llm_configured,
  )
  const needsReviewCount = queueStatsQuery.data?.counts?.needs_review ?? 0

  const { exportConversation } = useExport({
    currentFriendlyId: activeFriendlyId,
    currentSessionKey: sessionKeyForHistory,
    sessionTitle: activeTitle,
  })

  const uiQuery = useQuery({
    queryKey: chatUiQueryKey,
    queryFn: function readUiState() {
      return getChatUiState(queryClient)
    },
    initialData: function initialUiState() {
      return getChatUiState(queryClient)
    },
    staleTime: Infinity,
  })
  const gatewayStatusQuery = useQuery({
    queryKey: ['gateway', 'status'],
    queryFn: fetchGatewayStatus,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: 'always',
  })
  const gatewayStatusMountRef = useRef(Date.now())
  const gatewayStatusError =
    gatewayStatusQuery.error instanceof Error
      ? gatewayStatusQuery.error.message
      : gatewayStatusQuery.data && !gatewayStatusQuery.data.ok
        ? gatewayStatusQuery.data.error || 'Gateway unavailable'
        : null
  const gatewayError = gatewayStatusError ?? sessionsError ?? historyError
  const handleGatewayRefetch = useCallback(() => {
    void gatewayStatusQuery.refetch()
  }, [gatewayStatusQuery])
  const isSidebarCollapsed = uiQuery.data.isSidebarCollapsed
  const isInspectorOpen = uiQuery.data.isInspectorOpen
  const mobileView = uiQuery.data.mobileView
  const mobileDetailOpen = uiQuery.data.mobileDetailOpen

  const handleActiveSessionDelete = useCallback(() => {
    setIsRedirecting(true)
    navigate({ to: '/new', replace: true })
  }, [navigate])
  const stableContentStyle = useMemo<React.CSSProperties>(() => ({}), [])
  const missingSessionError =
    isSessionNotFound(historyError ?? '') ||
    isSessionNotFound(sessionsError ?? '')

  const shouldRedirectToNew =
    !isNewChat &&
    !forcedSessionKey &&
    !isRecentSession(activeFriendlyId) &&
    sessionsQuery.isSuccess &&
    !sessions.some((session) => session.friendlyId === activeFriendlyId) &&
    (missingSessionError || (!historyQuery.isFetching && !historyQuery.isSuccess))

  const refreshHistory = useCallback(() => {
    void historyQuery.refetch()
  }, [historyQuery])

  const refreshAgents = useCallback(() => {
    void agentsQuery.refetch()
  }, [agentsQuery])

  const hideUi = shouldRedirectToNew || isRedirecting

  const finishRun = useCallback(
    (runId: string) => {
      if (!runId) return
      const timer = pendingRunTimersRef.current.get(runId)
      if (typeof timer === 'number') {
        window.clearTimeout(timer)
      }
      pendingRunTimersRef.current.delete(runId)
      pendingRunIdsRef.current.delete(runId)
      if (pendingRunIdsRef.current.size === 0) {
        setPendingGeneration(false)
        setWaitingForResponse(false)
      }
    },
    [setWaitingForResponse],
  )

  const startRun = useCallback(
    (runId: string) => {
      if (!runId) return
      pendingRunIdsRef.current.add(runId)
      const existingTimer = pendingRunTimersRef.current.get(runId)
      if (typeof existingTimer === 'number') {
        window.clearTimeout(existingTimer)
      }
      const timeout = window.setTimeout(() => {
        pendingRunTimersRef.current.delete(runId)
        pendingRunIdsRef.current.delete(runId)
        refreshHistory()
        if (pendingRunIdsRef.current.size === 0) {
          setPendingGeneration(false)
          setWaitingForResponse(false)
        }
      }, 120000)
      pendingRunTimersRef.current.set(runId, timeout)
      setPendingGeneration(true)
      setWaitingForResponse(true)
    },
    [refreshHistory],
  )

  const finishAllRuns = useCallback(() => {
    for (const [, timer] of pendingRunTimersRef.current) {
      window.clearTimeout(timer)
    }
    pendingRunTimersRef.current.clear()
    pendingRunIdsRef.current.clear()
    setPendingGeneration(false)
    setWaitingForResponse(false)
  }, [])

  useEffect(() => {
    return () => {
      const hadLocalRuns = pendingRunTimersRef.current.size > 0
      for (const [, timer] of pendingRunTimersRef.current) {
        window.clearTimeout(timer)
      }
      pendingRunTimersRef.current.clear()
      pendingRunIdsRef.current.clear()
      if (hadLocalRuns) {
        setPendingGeneration(false)
      }
    }
  }, [])

  useEffect(() => {
    if (!waitingForResponse) return
    if (pendingRunIdsRef.current.size > 0) return
    const lastMessage = displayMessages[displayMessages.length - 1]
    if (lastMessage && lastMessage.role === 'assistant') {
      setPendingGeneration(false)
      setWaitingForResponse(false)
    }
  }, [displayMessages, waitingForResponse])

  const handleSelectService = useCallback(
    async (nextService: string) => {
      setDispatchError('')
      if (isNewChat) {
        setNewChatService(nextService)
        return
      }
      const sessionKeyTarget =
        forcedSessionKey ||
        resolvedSessionKey ||
        activeSessionKey ||
        activeFriendlyId
      try {
        const res = await fetch('/api/sessions', {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            sessionKey: sessionKeyTarget,
            friendlyId: activeFriendlyId,
            service: nextService,
          }),
        })
        if (!res.ok) throw new Error(await readError(res))
        await queryClient.invalidateQueries({ queryKey: chatQueryKeys.sessions })
      } catch (err) {
        setDispatchError(err instanceof Error ? err.message : String(err))
      }
    },
    [
      activeFriendlyId,
      activeSessionKey,
      forcedSessionKey,
      isNewChat,
      queryClient,
      resolvedSessionKey,
    ],
  )

  function sendMessage(
    sessionKey: string,
    friendlyId: string,
    body: string,
    skipOptimistic = false,
    attachments?: Array<AttachmentFile>,
  ) {
    setDispatchError('')
    let optimisticClientId = ''
    if (!skipOptimistic) {
      const { clientId, optimisticMessage } = createOptimisticMessage(
        body,
        attachments,
      )
      optimisticClientId = clientId
      appendHistoryMessage(
        queryClient,
        friendlyId,
        sessionKey,
        optimisticMessage,
      )
      updateSessionLastMessage(
        queryClient,
        sessionKey,
        friendlyId,
        optimisticMessage,
      )
    }

    setPendingGeneration(true)
    setSending(true)
    setWaitingForResponse(true)
    setPinToTop(true)

    const attachmentsPayload = attachments?.map((a) => ({
      mimeType: a.file.type,
      content: a.base64,
    }))

    fetch('/api/send', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        sessionKey,
        friendlyId,
        service: selectedService,
        message: body,
        thinking: settings.thinkingLevel,
        idempotencyKey: randomUUID(),
        attachments: attachmentsPayload,
      }),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(await readError(res))
        const payload = (await res.json().catch(() => ({}))) as {
          runId?: string
        }
        if (
          typeof payload.runId === 'string' &&
          payload.runId.trim().length > 0
        ) {
          startRun(payload.runId.trim())
        }
        refreshHistory()
        window.dispatchEvent(new CustomEvent('autoplan:event'))
      })
      .catch((err) => {
        const messageText = err instanceof Error ? err.message : String(err)
        if (isMissingGatewayAuth(messageText)) {
          navigate({ to: '/connect', replace: true })
          return
        }
        setDispatchError(messageText)
        if (optimisticClientId) {
          updateHistoryMessageByClientId(
            queryClient,
            friendlyId,
            sessionKey,
            optimisticClientId,
            function markFailed(message) {
              return { ...message, status: 'error' }
            },
          )
        }
        setPendingGeneration(false)
        setWaitingForResponse(false)
        setPinToTop(false)
        refreshHistory()
      })
      .finally(() => {
        setSending(false)
      })
  }

  const createSessionForMessage = useCallback(
    async (serviceOverride?: string) => {
      setCreatingSession(true)
      try {
        const res = await fetch('/api/sessions', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            service: serviceOverride || selectedService,
          }),
        })
        if (!res.ok) throw new Error(await readError(res))

        const data = (await res.json()) as {
          sessionKey?: string
          friendlyId?: string
        }

        const sessionKey =
          typeof data.sessionKey === 'string' ? data.sessionKey : ''
        const friendlyId =
          typeof data.friendlyId === 'string' &&
          data.friendlyId.trim().length > 0
            ? data.friendlyId.trim()
            : deriveFriendlyIdFromKey(sessionKey)

        if (!sessionKey || !friendlyId) {
          throw new Error('Invalid session response')
        }

        await queryClient.invalidateQueries({ queryKey: chatQueryKeys.sessions })
        return { sessionKey, friendlyId }
      } finally {
        setCreatingSession(false)
      }
    },
    [queryClient, selectedService],
  )

  const handleRunSimpleTask = useCallback(
    async (serviceOverride?: string) => {
      const targetSvc = serviceOverride || selectedService
      setDispatchError('')
      setBusyDemoService(targetSvc)
      try {
        let targetSessionKey =
          forcedSessionKey ||
          resolvedSessionKey ||
          activeSessionKey ||
          activeFriendlyId
        let navigateFriendlyId = ''

        if (isNewChat) {
          const created = await createSessionForMessage(targetSvc)
          targetSessionKey = created.sessionKey
          navigateFriendlyId = created.friendlyId
          setRecentSession(created.friendlyId)
        }

        const res = await fetch('/api/autoplan/agents/demo-task', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            service: targetSvc,
            webclaw_session_key: targetSessionKey,
          }),
        })
        const payload = (await res.json().catch(() => ({}))) as {
          success?: boolean
          error?: string
          run?: { id?: string }
        }
        if (!res.ok || payload.success === false) {
          throw new Error(payload.error || `HTTP ${res.status}`)
        }
        if (navigateFriendlyId) {
          setPendingGeneration(true)
          refreshAgents()
          window.dispatchEvent(new CustomEvent('autoplan:event'))
          navigate({
            to: '/chat/$sessionKey',
            params: { sessionKey: navigateFriendlyId },
            replace: true,
          })
        } else {
          if (payload.run?.id) {
            startRun(payload.run.id)
          }
          refreshHistory()
          refreshAgents()
          window.dispatchEvent(new CustomEvent('autoplan:event'))
        }
      } catch (err) {
        setDispatchError(err instanceof Error ? err.message : String(err))
      } finally {
        setBusyDemoService(null)
      }
    },
    [
      activeFriendlyId,
      activeSessionKey,
      createSessionForMessage,
      forcedSessionKey,
      isNewChat,
      navigate,
      refreshAgents,
      refreshHistory,
      resolvedSessionKey,
      selectedService,
      startRun,
    ],
  )

  const send = useCallback(
    (body: string, helpers: ChatComposerHelpers) => {
      const attachments = helpers.attachments
      if (body.length === 0 && (!attachments || attachments.length === 0))
        return
      helpers.reset()

      if (isNewChat) {
        const { clientId, optimisticId, optimisticMessage } =
          createOptimisticMessage(body, attachments)
        appendHistoryMessage(queryClient, 'new', 'new', optimisticMessage)
        setPendingGeneration(true)
        setSending(true)
        setWaitingForResponse(true)
        setPinToTop(true)

        createSessionForMessage()
          .then(({ sessionKey, friendlyId }) => {
            setRecentSession(friendlyId)
            stashPendingSend({
              sessionKey,
              friendlyId,
              message: body,
              optimisticMessage,
              attachments,
            })
            if (onSessionResolved) {
              onSessionResolved({ sessionKey, friendlyId })
              return
            }
            navigate({
              to: '/chat/$sessionKey',
              params: { sessionKey: friendlyId },
              replace: true,
            })
          })
          .catch((err) => {
            setDispatchError(err instanceof Error ? err.message : String(err))
            removeHistoryMessageByClientId(
              queryClient,
              'new',
              'new',
              clientId,
              optimisticId,
            )
            helpers.setValue(body)
            setPendingGeneration(false)
            setWaitingForResponse(false)
            setPinToTop(false)
            setSending(false)
          })
        return
      }

      const sessionKeyForSend =
        forcedSessionKey ||
        resolvedSessionKey ||
        activeSessionKey ||
        activeFriendlyId
      sendMessage(sessionKeyForSend, activeFriendlyId, body, false, attachments)
    },
    [
      activeFriendlyId,
      activeSessionKey,
      createSessionForMessage,
      forcedSessionKey,
      isNewChat,
      navigate,
      onSessionResolved,
      queryClient,
      resolvedSessionKey,
      selectedService,
      settings.thinkingLevel,
    ],
  )

  const startNewChat = useCallback(() => {
    setWaitingForResponse(false)
    setPinToTop(false)
    setDispatchError('')
    clearHistoryMessages(queryClient, 'new', 'new')
    navigate({ to: '/new' })
    if (isMobile) {
      setChatUiState(queryClient, function collapse(state) {
        return { ...state, isSidebarCollapsed: true }
      })
    }
  }, [isMobile, navigate, queryClient])

  const handleToggleSidebarCollapse = useCallback(() => {
    setChatUiState(queryClient, function toggle(state) {
      return { ...state, isSidebarCollapsed: !state.isSidebarCollapsed }
    })
  }, [queryClient])

  const handleToggleInspector = useCallback(() => {
    setChatUiState(queryClient, function toggle(state) {
      return { ...state, isInspectorOpen: !state.isInspectorOpen }
    })
  }, [queryClient])

  const handleFocusOrchestratorQueue = useCallback(() => {
    setInspectorTab('queue')
    setChatUiState(queryClient, function ensureInspectorOpen(state) {
      return { ...state, isInspectorOpen: true }
    })
  }, [queryClient])

  const handleSelectSession = useCallback(() => {
    setDispatchError('')
    if (!isMobile) return
    setChatUiState(queryClient, function collapse(state) {
      return { ...state, isSidebarCollapsed: true }
    })
  }, [isMobile, queryClient])

  const handleOpenSidebar = useCallback(() => {
    setChatUiState(queryClient, function open(state) {
      return { ...state, isSidebarCollapsed: false }
    })
  }, [queryClient])

  const handleChangeMobileView = useCallback(
    (nextView: MobileStageView) => {
      setChatUiState(queryClient, function setView(state) {
        return {
          ...state,
          mobileView: nextView,
          mobileDetailOpen:
            nextView === 'sessions' ? false : state.mobileDetailOpen,
        }
      })
    },
    [queryClient],
  )

  const handleChangeMobileDetailOpen = useCallback(
    (nextOpen: boolean) => {
      setChatUiState(queryClient, function setDetail(state) {
        return { ...state, mobileDetailOpen: nextOpen }
      })
    },
    [queryClient],
  )

  const handleMobileCreateSessionForService = useCallback(
    async (targetService: string) => {
      setDispatchError('')
      try {
        setNewChatService(targetService)
        const created = await createSessionForMessage(targetService)
        setRecentSession(created.friendlyId)
        setChatUiState(queryClient, function enterSession(state) {
          return { ...state, mobileView: 'session', mobileDetailOpen: false }
        })
        await sessionsQuery.refetch()
        navigate({
          to: '/chat/$sessionKey',
          params: { sessionKey: created.friendlyId },
        })
      } catch (err) {
        setDispatchError(err instanceof Error ? err.message : String(err))
      }
    },
    [createSessionForMessage, navigate, queryClient, sessionsQuery],
  )

  const handleRefreshAll = useCallback(() => {
    void sessionsQuery.refetch()
    void agentsQuery.refetch()
    void queueStatsQuery.refetch()
    refreshHistory()
  }, [agentsQuery, queueStatsQuery, refreshHistory, sessionsQuery])

  const historyLoading = historyQuery.isLoading || isRedirecting
  const showGatewayDown = Boolean(gatewayStatusError)
  const showGatewayNotice =
    showGatewayDown &&
    gatewayStatusQuery.errorUpdatedAt > gatewayStatusMountRef.current
  const redirectToConnect = shouldRedirectToConnect({
    isRedirecting,
    shouldRedirectToNew,
    sessionsReady: sessionsQuery.isSuccess,
    activeExists,
    sessionsError,
    historyError,
    gatewayStatusError,
  })
  const historyEmpty = !historyLoading && displayMessages.length === 0
  const gatewayNotice = useMemo(() => {
    if (!showGatewayNotice) return null
    if (!gatewayError) return null
    return (
      <GatewayStatusMessage
        state="error"
        error={gatewayError}
        onRetry={handleGatewayRefetch}
      />
    )
  }, [gatewayError, handleGatewayRefetch, showGatewayNotice])

  useChatStream({
    activeFriendlyId,
    isNewChat,
    isRedirecting,
    resolvedSessionKey,
    sessionKeyForHistory,
    queryClient,
    refreshHistory,
    onChatEvent(payload) {
      const payloadSessionKey =
        typeof payload.sessionKey === 'string' ? payload.sessionKey : ''
      if (
        payloadSessionKey &&
        resolvedSessionKey &&
        payloadSessionKey !== resolvedSessionKey &&
        payloadSessionKey !== sessionKeyForHistory
      ) {
        return
      }
      const runId = typeof payload.runId === 'string' ? payload.runId : ''
      const state = typeof payload.state === 'string' ? payload.state : ''
      if (runId && state === 'delta') {
        startRun(runId)
      }
      if (
        runId &&
        (state === 'final' || state === 'error' || state === 'aborted')
      ) {
        finishRun(runId)
      }
      if (
        !runId &&
        (state === 'final' || state === 'error' || state === 'aborted')
      ) {
        finishAllRuns()
      }
    },
  })

  useChatRedirect({
    activeFriendlyId,
    isNewChat,
    isRedirecting,
    shouldRedirectToNew,
    sessionsReady: sessionsQuery.isSuccess,
    sessionKeyForHistory,
    queryClient,
    setIsRedirecting,
  })

  useChatGenerationGuard({
    waitingForResponse,
    refreshHistory,
    setWaitingForResponse,
  })

  useChatPendingSend({
    activeFriendlyId,
    activeSessionKey,
    forcedSessionKey,
    isNewChat,
    queryClient,
    resolvedSessionKey,
    setWaitingForResponse,
    setPinToTop,
    sendMessage,
  })

  const sidebar = (
    <ChatSidebar
      sessions={sessions}
      activeFriendlyId={activeFriendlyId}
      creatingSession={creatingSession}
      onCreateSession={startNewChat}
      isCollapsed={isMobile ? false : isSidebarCollapsed}
      onToggleCollapse={handleToggleSidebarCollapse}
      onSelectSession={handleSelectSession}
      onActiveSessionDelete={handleActiveSessionDelete}
      hideBrandHeader={!isMobile}
    />
  )

  if (redirectToConnect) {
    return <Navigate to="/connect" replace />
  }

  if (isMobile) {
    return (
      <MobileAntigravityWorkbench
        sessions={sessions}
        activeFriendlyId={activeFriendlyId}
        activeTitle={activeTitle}
        activeCanonicalKey={activeCanonicalKey}
        isNewChat={isNewChat}
        creatingSession={creatingSession}
        services={services}
        selectedService={selectedService}
        chiefLlmConfigured={chiefLlmConfigured}
        chiefLlmStatus={chiefLlmStatus}
        displayMessages={displayMessages}
        historyLoading={historyLoading}
        historyEmpty={historyEmpty}
        gatewayNotice={gatewayNotice}
        waitingForResponse={waitingForResponse}
        pinToTop={pinToTop}
        pinGroupMinHeight={pinGroupMinHeight}
        headerHeight={48}
        stableContentStyle={stableContentStyle}
        sending={sending}
        dispatchError={dispatchError}
        onDismissError={() => setDispatchError('')}
        busyDemoService={busyDemoService}
        onSelectService={handleSelectService}
        onRunSimpleTask={handleRunSimpleTask}
        onCreateSessionForService={handleMobileCreateSessionForService}
        onSendMessage={send}
        onExportMarkdown={() => exportConversation('markdown')}
        onRefreshAll={handleRefreshAll}
        onRefreshHistory={refreshHistory}
        onRunFinished={finishRun}
        mobileView={mobileView}
        onChangeMobileView={handleChangeMobileView}
        mobileDetailOpen={mobileDetailOpen}
        onChangeMobileDetailOpen={handleChangeMobileDetailOpen}
      />
    )
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-surface text-primary-900">
      <ChatHeader
        activeTitle={activeTitle}
        wrapperRef={headerRef}
        showSidebarButton={false}
        onOpenSidebar={handleOpenSidebar}
        isSidebarCollapsed={isSidebarCollapsed}
        onToggleSidebarCollapse={handleToggleSidebarCollapse}
        onExport={exportConversation}
        exportDisabled={historyLoading || displayMessages.length === 0}
        showExport={!isNewChat}
        usedTokens={activeSession?.totalTokens}
        maxTokens={activeSession?.contextTokens}
        services={services}
        selectedService={selectedService}
        onSelectService={(svc) => void handleSelectService(svc)}
        chiefLlmConfigured={chiefLlmConfigured}
        chiefLlmStatus={chiefLlmStatus}
        needsReviewCount={needsReviewCount}
        onFocusOrchestratorQueue={handleFocusOrchestratorQueue}
        onRunSimpleTask={() => void handleRunSimpleTask()}
        runningSimpleTask={busyDemoService !== null}
        inspectorOpen={isInspectorOpen}
        onToggleInspector={handleToggleInspector}
      />

      <div
        className={cn(
          'min-h-0 flex-1 overflow-hidden max-md:grid-cols-1',
          isInspectorOpen
            ? 'grid grid-cols-[auto_1fr_auto]'
            : 'grid grid-cols-[auto_1fr]',
        )}
      >
        {hideUi ? null : <div className="max-md:hidden h-full">{sidebar}</div>}

        <main className="flex flex-col h-full min-h-0 min-w-0" ref={mainRef}>
          {dispatchError ? (
            <div
              data-testid="dispatch-error-banner"
              role="alert"
              className="flex items-center justify-between border-b border-red-500/40 bg-red-500/10 px-4 py-1.5 text-xs text-red-400"
            >
              <span className="truncate">{dispatchError}</span>
              <button
                type="button"
                onClick={() => setDispatchError('')}
                className="ml-3 shrink-0 underline"
              >
                Dismiss
              </button>
            </div>
          ) : null}

          {hideUi ? null : (
            <>
              <ChatMessageList
                messages={displayMessages}
                loading={historyLoading}
                empty={historyEmpty}
                notice={gatewayNotice}
                noticePosition="end"
                waitingForResponse={waitingForResponse}
                sessionKey={activeCanonicalKey}
                pinToTop={pinToTop}
                pinGroupMinHeight={pinGroupMinHeight}
                headerHeight={headerHeight}
                contentStyle={stableContentStyle}
              />
              <ChatComposer
                onSubmit={send}
                isLoading={sending}
                disabled={sending}
                wrapperRef={composerRef}
              />
            </>
          )}
        </main>

        {!hideUi && isInspectorOpen ? (
          <div className="max-md:hidden h-full">
            <AutoplanInspector
              services={services}
              chiefLlmStatus={chiefLlmStatus}
              onRunSimpleTask={handleRunSimpleTask}
              busyDemoService={busyDemoService}
              onRefreshAgents={refreshAgents}
              onRefreshHistory={refreshHistory}
              onRunFinished={finishRun}
              activeTab={inspectorTab}
              onTabChange={setInspectorTab}
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}
