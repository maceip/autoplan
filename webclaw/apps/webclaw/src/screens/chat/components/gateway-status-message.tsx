import { MessageStatus } from './message-status'

type GatewayStatusMessageProps = {
  state: 'checking' | 'error'
  error?: string | null
  onRetry?: () => void
  className?: string
}

export function GatewayStatusMessage({
  state,
  error,
  onRetry,
  className,
}: GatewayStatusMessageProps) {
  const isChecking = state === 'checking'
  const title = isChecking
    ? 'Checking gateway connection...'
    : 'OpenClaw gateway is unreachable'
  const description = isChecking
    ? 'This dashboard needs access to the OpenClaw gateway configured by your server environment variables.'
    : ''
  return (
    <MessageStatus
      title={title}
      description={
        isChecking ? (
          description
        ) : (
          <>
            We could not reach the gateway from the dashboard server. Start the
            gateway and confirm your server environment has{' '}
            <span className="font-mono">CLAWDBOT_GATEWAY_URL</span> plus{' '}
            <span className="font-mono">CLAWDBOT_GATEWAY_TOKEN</span> (or{' '}
            <span className="font-mono">CLAWDBOT_GATEWAY_PASSWORD</span>).
          </>
        )
      }
      detail={isChecking ? null : error}
      actionLabel={isChecking ? undefined : 'Retry'}
      onAction={isChecking ? undefined : onRetry}
      className={className}
    />
  )
}
