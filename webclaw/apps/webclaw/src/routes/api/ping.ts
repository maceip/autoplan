import { createFileRoute } from '@tanstack/react-router'
import { json } from '@tanstack/react-start'
import { gatewayConnectCheck } from '../../server/gateway'
import {
  isOpenClawGatewayConfigured,
  proxyAutoplanJson,
} from '../../server/autoplan'

export const Route = createFileRoute('/api/ping')({
  server: {
    handlers: {
      GET: async () => {
        try {
          if (!isOpenClawGatewayConfigured()) {
            return await proxyAutoplanJson('/api/webclaw/ping')
          }
          await gatewayConnectCheck()
          return json({ ok: true })
        } catch (err) {
          return json(
            {
              ok: false,
              error: err instanceof Error ? err.message : String(err),
            },
            { status: 503 },
          )
        }
      },
    },
  },
})
