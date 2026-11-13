import { cn } from '@/lib/utils'

export type WebClawIconProps = {
  className?: string
}

export function WebClawIcon({ className }: WebClawIconProps) {
  return (
    <img
      src="/autobot-icon.png?v=2"
      alt=""
      aria-hidden="true"
      data-testid="autobot-brand-icon"
      className={cn('size-6 shrink-0 object-contain', className)}
    />
  )
}

export { WebClawIcon as AutobotIcon }
