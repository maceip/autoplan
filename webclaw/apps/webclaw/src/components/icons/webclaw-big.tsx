import { cn } from '@/lib/utils'

export type WebClawIconBigProps = {
  className?: string
}

export function WebClawIconBig({ className }: WebClawIconBigProps) {
  return (
    <img
      src="/autobot-icon.png"
      alt=""
      aria-hidden="true"
      data-testid="autobot-brand-icon"
      className={cn('size-6 shrink-0 object-contain', className)}
    />
  )
}

export { WebClawIconBig as AutobotIconBig }
