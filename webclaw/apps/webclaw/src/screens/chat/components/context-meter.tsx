import { memo, useMemo } from 'react'
import { Gauge } from 'lucide-react'
import { Button } from '@astryxdesign/core/Button'
import { Popover } from '@astryxdesign/core/Popover'
import { Text } from '@astryxdesign/core/Text'
import { cn } from '@/lib/utils'

type ContextMeterProps = {
  usedTokens?: number
  maxTokens?: number
}

function ContextMeterComponent({ usedTokens, maxTokens }: ContextMeterProps) {
  const { percentage, usedLabel, leftPercentage } = useMemo(() => {
    if (
      typeof usedTokens !== 'number' ||
      typeof maxTokens !== 'number' ||
      maxTokens <= 0
    ) {
      return {
        percentage: null as number | null,
        usedLabel: null as string | null,
        leftPercentage: null as number | null,
      }
    }
    const rawPct = (usedTokens / maxTokens) * 100
    const clampedPct = Math.max(0, Math.min(100, Math.round(rawPct)))
    const leftPct = Math.max(0, Math.min(100, 100 - clampedPct))
    const formattedUsed = usedTokens.toLocaleString()
    const formattedMax = maxTokens.toLocaleString()
    return {
      percentage: clampedPct,
      usedLabel: `${formattedUsed} / ${formattedMax} context used`,
      leftPercentage: leftPct,
    }
  }, [usedTokens, maxTokens])

  if (percentage === null || usedLabel === null || leftPercentage === null) {
    return null
  }

  const barTone =
    percentage >= 85
      ? 'bg-error'
      : percentage >= 65
        ? 'bg-warning'
        : 'bg-accent-bg'

  return (
    <Popover
      placement="below"
      alignment="end"
      width={240}
      padding={3}
      label="Context usage"
      content={
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <Text type="supporting" weight="semibold">
              Context Window
            </Text>
            <span className="font-mono text-xs text-secondary tabular-nums">
              {percentage}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={cn('h-full rounded-full transition-all', barTone)}
              style={{ width: `${percentage}%` }}
            />
          </div>
          <Text type="supporting" color="secondary" display="block">
            {usedLabel} · {leftPercentage}% left
          </Text>
        </div>
      }
    >
      <Button
        variant="ghost"
        size="sm"
        icon={<Gauge className="size-3.5" />}
        label={`${percentage}%`}
        aria-label={`Context usage: ${percentage}%`}
      />
    </Popover>
  )
}

export const ContextMeter = memo(ContextMeterComponent)
