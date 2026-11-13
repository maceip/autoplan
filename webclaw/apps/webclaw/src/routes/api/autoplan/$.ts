import { createFileRoute } from '@tanstack/react-router'
import { json } from '@tanstack/react-start'
import {
  getAutoplanBaseUrl,
  isOpenClawGatewayConfigured,
  proxyAutoplanJson,
} from '../../../server/autoplan'

async function forward(request: Request, splat: string): Promise<Response> {
  if (isOpenClawGatewayConfigured()) {
    return json({ success: false, error: 'AutoPlan mode disabled' }, { status: 404 })
  }
  const url = new URL(request.url)
  const cleanSplat = (splat || '').replace(/^\/+/, '')
  const backendPath = `/api/${cleanSplat}${url.search}`
  const method = request.method.toUpperCase()
  const hasBody = method !== 'GET' && method !== 'HEAD'
  const rawBody = hasBody ? await request.text() : undefined
  try {
    return await proxyAutoplanJson(backendPath, {
      method,
      body: rawBody,
    })
  } catch (err) {
    return json(
      {
        success: false,
        error: `AutoPlan backend unreachable at ${getAutoplanBaseUrl()}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      },
      { status: 502 },
    )
  }
}

export const Route = createFileRoute('/api/autoplan/$')({
  server: {
    handlers: {
      GET: ({ request, params }) => forward(request, params._splat ?? ''),
      POST: ({ request, params }) => forward(request, params._splat ?? ''),
      PATCH: ({ request, params }) => forward(request, params._splat ?? ''),
      DELETE: ({ request, params }) => forward(request, params._splat ?? ''),
    },
  },
})
