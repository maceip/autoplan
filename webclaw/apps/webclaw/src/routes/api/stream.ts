import { createFileRoute } from '@tanstack/react-router'
import { acquireGatewayClient, gatewayRpcShared } from '../../server/gateway'
import {
  getAutoplanBaseUrl,
  isOpenClawGatewayConfigured,
} from '../../server/autoplan'

type StreamEventPayload = {
  event: string
  payload?: unknown
  seq?: number
  stateVersion?: number
}

export const Route = createFileRoute('/api/stream')({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const url = new URL(request.url)

        if (!isOpenClawGatewayConfigured()) {
          const upstreamUrl = `${getAutoplanBaseUrl()}/api/webclaw/stream${url.search}`
          try {
            const upstream = await fetch(upstreamUrl, {
              headers: { Accept: 'text/event-stream' },
              signal: request.signal,
            })
            const reader = upstream.body?.getReader()
            if (!reader) {
              return new Response('', {
                status: upstream.status,
                headers: {
                  'Content-Type': 'text/event-stream; charset=utf-8',
                  'Cache-Control': 'no-cache, no-transform',
                  'X-Accel-Buffering': 'no',
                  Connection: 'keep-alive',
                },
              })
            }
            const proxyStream = new ReadableStream<Uint8Array>({
              async pull(controller) {
                try {
                  const { done, value } = await reader.read()
                  if (done) {
                    controller.close()
                    return
                  }
                  if (value) {
                    controller.enqueue(value)
                  }
                } catch {
                  try {
                    controller.close()
                  } catch {
                    // stream already closed
                  }
                }
              },
              cancel() {
                void reader.cancel().catch(() => undefined)
              },
            })
            return new Response(proxyStream, {
              status: upstream.status,
              headers: {
                'Content-Type': 'text/event-stream; charset=utf-8',
                'Cache-Control': 'no-cache, no-transform',
                'X-Accel-Buffering': 'no',
                Connection: 'keep-alive',
              },
            })
          } catch (err) {
            const encoder = new TextEncoder()
            const message = err instanceof Error ? err.message : String(err)
            const body = encoder.encode(
              `data: ${JSON.stringify({ event: 'error', payload: message })}\n\n`,
            )
            return new Response(body, {
              status: 200,
              headers: {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
              },
            })
          }
        }

        const sessionKey = url.searchParams.get('sessionKey')?.trim() || ''
        const friendlyId = url.searchParams.get('friendlyId')?.trim() || ''
        const encoder = new TextEncoder()

        let releaseClient: (() => void) | null = null
        let closed = false

        const stream = new ReadableStream({
          start(controller) {
            function send(data: StreamEventPayload) {
              if (closed) return
              try {
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify(data)}\n\n`),
                )
              } catch {
                closed = true
              }
            }

            const heartbeat = setInterval(() => {
              controller.enqueue(encoder.encode('event: ping\ndata: {}\n\n'))
            }, 15000)

            const key = sessionKey || friendlyId
            if (key) {
              void acquireGatewayClient(key, {
                onEvent(event) {
                  send({
                    event: event.event,
                    payload: event.payload,
                    seq: event.seq,
                    stateVersion: event.stateVersion,
                  })
                },
                onError(error) {
                  send({ event: 'error', payload: error.message })
                },
              })
                .then((handle) => {
                  if (closed) {
                    handle.release()
                    return
                  }
                  releaseClient = handle.release
                  if (sessionKey) {
                    void gatewayRpcShared(
                      'chat.history',
                      { sessionKey, limit: 1 },
                      sessionKey,
                    )
                  }
                })
                .catch((error: unknown) => {
                  if (closed) return
                  const message =
                    error instanceof Error ? error.message : String(error)
                  send({ event: 'error', payload: message })
                })
            }

            request.signal.addEventListener(
              'abort',
              () => {
                if (closed) return
                closed = true
                clearInterval(heartbeat)
                releaseClient?.()
                try {
                  controller.close()
                } catch {
                  return
                }
              },
              { once: true },
            )
          },
          cancel() {
            if (closed) return
            closed = true
            releaseClient?.()
          },
        })

        return new Response(stream, {
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          },
        })
      },
    },
  },
})
