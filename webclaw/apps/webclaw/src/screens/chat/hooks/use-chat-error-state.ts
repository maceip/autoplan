import { isMissingGatewayAuth } from '../utils'

type UseChatErrorStateInput = {
  isRedirecting: boolean
  shouldRedirectToNew: boolean
  sessionsReady: boolean
  activeExists: boolean
  sessionsError: string | null
  historyError: string | null
  gatewayStatusError: string | null
}

export function shouldRedirectToConnect({
  isRedirecting,
  shouldRedirectToNew,
  sessionsReady,
  activeExists,
  sessionsError,
  historyError,
  gatewayStatusError,
}: UseChatErrorStateInput) {
  if (isRedirecting || shouldRedirectToNew) return false
  if (sessionsReady && !activeExists) return false
  const messageText = sessionsError ?? historyError ?? gatewayStatusError
  if (!messageText) return false
  return isMissingGatewayAuth(messageText)
}
