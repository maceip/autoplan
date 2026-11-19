import {
  HeadContent,
  Outlet,
  Scripts,
  createRootRoute,
} from '@tanstack/react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AstryxWorkbenchProvider } from '../lib/astryx-theme'

import appCss from '../styles.css?url'

const themeScript = `
(() => {
  try {
    let colorMode = 'dark'
    let themeSlug = 'neutral'
    const astryxStored = localStorage.getItem('autoplan-astryx-prefs')
    if (astryxStored) {
      const parsed = JSON.parse(astryxStored)
      if (parsed?.colorMode === 'light' || parsed?.colorMode === 'dark' || parsed?.colorMode === 'system') {
        colorMode = parsed.colorMode
      }
      if (['neutral', 'stone', 'matcha', 'butter', 'chocolate'].includes(parsed?.themeSlug)) {
        themeSlug = parsed.themeSlug
      }
    } else {
      const stored = localStorage.getItem('chat-settings')
      if (stored) {
        const parsed = JSON.parse(stored)
        const storedTheme = parsed?.state?.settings?.theme
        if (storedTheme === 'light' || storedTheme === 'dark' || storedTheme === 'system') {
          colorMode = storedTheme
        }
      }
    }
    const root = document.documentElement
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const resolved = colorMode === 'system' ? (media.matches ? 'dark' : 'light') : colorMode
      root.setAttribute('data-astryx-theme', themeSlug)
      root.setAttribute('data-theme', resolved)
      root.classList.remove('light', 'dark', 'system')
      root.classList.add(colorMode)
      if (colorMode === 'system' && resolved === 'dark') {
        root.classList.add('dark')
      }
      root.style.colorScheme = resolved
    }
    apply()
    media.addEventListener('change', () => {
      if (colorMode === 'system') apply()
    })
  } catch {
    const root = document.documentElement
    root.setAttribute('data-astryx-theme', 'neutral')
    root.setAttribute('data-theme', 'dark')
    root.classList.add('dark')
  }
})()
`

export const Route = createRootRoute({
  head: () => ({
    meta: [
      {
        charSet: 'utf-8',
      },
      {
        name: 'viewport',
        content: 'width=device-width, initial-scale=1, viewport-fit=cover',
      },
      {
        title: 'autobot',
      },
      {
        name: 'description',
        content: 'Multi-agent Chief of Staff and lead agent workbench',
      },
      {
        name: 'theme-color',
        content: '#141413',
      },
      {
        property: 'og:title',
        content: 'autobot',
      },
      {
        property: 'og:description',
        content: 'Multi-agent Chief of Staff and lead agent workbench',
      },
      {
        property: 'og:type',
        content: 'website',
      },
      {
        property: 'og:image',
        content: 'https://queue.secure.build/autobot-icon-512.png?v=2',
      },
      {
        property: 'og:image:type',
        content: 'image/png',
      },
      {
        name: 'twitter:card',
        content: 'summary',
      },
      {
        name: 'twitter:image',
        content: 'https://queue.secure.build/autobot-icon-512.png?v=2',
      },
    ],
    links: [
      {
        rel: 'stylesheet',
        href: appCss,
      },
      {
        rel: 'icon',
        type: 'image/png',
        href: '/favicon.png?v=2',
      },
      {
        rel: 'apple-touch-icon',
        href: '/apple-touch-icon.png?v=2',
      },
      {
        rel: 'manifest',
        href: '/manifest.json?v=2',
      },
    ],
  }),

  shellComponent: RootDocument,
  component: RootLayout,
  notFoundComponent: RootNotFound,
})

const queryClient = new QueryClient()

function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <AstryxWorkbenchProvider>
        <Outlet />
      </AstryxWorkbenchProvider>
    </QueryClientProvider>
  )
}

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-astryx-theme="neutral"
      data-theme="dark"
      className="dark"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <HeadContent />
      </head>
      <body>
        <div className="root">{children}</div>
        <Scripts />
      </body>
    </html>
  )
}

function RootNotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-6">
      <p className="text-pretty text-sm text-primary-700">Page not found.</p>
    </div>
  )
}
