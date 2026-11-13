const DEFAULT_AUTOPLAN_URL = 'http://localhost:5001'

export function getAutoplanBaseUrl(): string {
  return (process.env.AUTOPLAN_BACKEND_URL || DEFAULT_AUTOPLAN_URL)
    .trim()
    .replace(/\/+$/, '')
}

export function isOpenClawGatewayConfigured(): boolean {
  return Boolean((process.env.CLAWDBOT_GATEWAY_URL || '').trim())
}

export async function proxyAutoplanJson(
  backendPath: string,
  init?: RequestInit,
): Promise<Response> {
  const targetUrl = `${getAutoplanBaseUrl()}${backendPath}`
  const upstream = await fetch(targetUrl, {
    ...init,
    headers: {
      'content-type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  const text = await upstream.text()
  return new Response(text, {
    status: upstream.status,
    headers: {
      'content-type':
        upstream.headers.get('content-type') || 'application/json',
    },
  })
}
