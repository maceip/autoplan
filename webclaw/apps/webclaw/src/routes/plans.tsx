import { createFileRoute } from '@tanstack/react-router'
import { PlansPortfolioView } from '../screens/plans/plans-portfolio-view'

export const Route = createFileRoute('/plans')({
  component: PlansRoute,
})

function PlansRoute() {
  return <PlansPortfolioView />
}
