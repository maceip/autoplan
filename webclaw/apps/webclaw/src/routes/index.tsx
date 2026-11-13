import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  beforeLoad: () => {
    throw redirect({
      to: '/chat/$sessionKey',
      params: { sessionKey: 'main' },
      replace: true,
    })
  },
  component: IndexRoute,
})

function IndexRoute() {
  return (
    <div className="h-screen flex items-center justify-center text-primary-600">
      Loading…
    </div>
  )
}
