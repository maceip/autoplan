import { Copy, Monitor, Moon, Sun } from 'lucide-react'
import type { PathsPayload } from '../types'
import type { ThinkingLevel } from '@/hooks/use-chat-settings'
import { useChatSettings } from '@/hooks/use-chat-settings'
import {
  ASTRYX_THEME_OPTIONS,
  useAstryxWorkbench,
} from '@/lib/astryx-theme'
import type { AstryxColorMode } from '@/lib/astryx-theme'
import { Button } from '@astryxdesign/core/Button'
import { Card } from '@astryxdesign/core/Card'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { IconButton } from '@astryxdesign/core/IconButton'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@astryxdesign/core/SegmentedControl'
import { Switch } from '@astryxdesign/core/Switch'
import { Text } from '@astryxdesign/core/Text'
import { cn } from '@/lib/utils'

type SettingsSectionProps = {
  title: string
  children: React.ReactNode
}

function SettingsSection({ title, children }: SettingsSectionProps) {
  return (
    <section className="space-y-2.5">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-secondary">
        {title}
      </h3>
      <Card variant="muted" padding={3}>
        <div className="divide-y divide-border">{children}</div>
      </Card>
    </section>
  )
}

type SettingsRowProps = {
  label: string
  description?: string
  children: React.ReactNode
}

function SettingsRow({ label, description, children }: SettingsRowProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-primary">{label}</p>
        {description ? (
          <p className="text-xs text-secondary">{description}</p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  )
}

type SettingsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  pathsLoading: boolean
  pathsError: string | null
  paths: PathsPayload | null
  onClose: () => void
  onCopySessionsDir: () => void
  onCopyStorePath: () => void
}

export function SettingsDialog({
  open,
  onOpenChange,
  pathsLoading,
  pathsError,
  paths,
  onClose,
  onCopySessionsDir,
  onCopyStorePath,
}: SettingsDialogProps) {
  const { settings, updateSettings } = useChatSettings()
  const {
    themeSlug,
    colorMode,
    resolvedMode,
    setThemeSlug,
    setColorMode,
  } = useAstryxWorkbench()

  return (
    <Dialog
      isOpen={open}
      onOpenChange={onOpenChange}
      width={560}
      maxHeight="85dvh"
      padding={0}
      purpose="info"
    >
      <div className="flex max-h-[85dvh] flex-col">
        <DialogHeader
          title="Settings"
          subtitle="Workbench appearance, execution defaults, and workspace paths."
          onOpenChange={onOpenChange}
          hasDivider
        />

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          <SettingsSection title="Appearance">
            <SettingsRow
              label="Color mode"
              description="Syncs across workbench panels and desktop shell."
            >
              <SegmentedControl
                value={colorMode}
                onChange={(value) => {
                  void setColorMode(value as AstryxColorMode)
                }}
                label="Color mode"
                size="sm"
              >
                <SegmentedControlItem
                  value="system"
                  label="System"
                  icon={<Monitor className="size-3.5" />}
                />
                <SegmentedControlItem
                  value="light"
                  label="Light"
                  icon={<Sun className="size-3.5" />}
                />
                <SegmentedControlItem
                  value="dark"
                  label="Dark"
                  icon={<Moon className="size-3.5" />}
                />
              </SegmentedControl>
            </SettingsRow>

            <SettingsRow
              label="Theme material"
              description="Ergonomic surface palette powered by Astryx."
            >
              <div className="flex flex-wrap gap-1.5">
                {ASTRYX_THEME_OPTIONS.map((opt) => {
                  const selected = themeSlug === opt.slug
                  const surface =
                    resolvedMode === 'dark' ? opt.darkSurface : opt.lightSurface
                  return (
                    <button
                      key={opt.slug}
                      type="button"
                      onClick={() => void setThemeSlug(opt.slug)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                        selected
                          ? 'border-border-strong bg-card text-primary shadow-sm'
                          : 'border-border bg-surface text-secondary hover:text-primary',
                      )}
                    >
                      <span
                        className="size-3 rounded-full border border-border"
                        style={{ backgroundColor: surface }}
                        aria-hidden="true"
                      />
                      <span>{opt.label}</span>
                    </button>
                  )
                })}
              </div>
            </SettingsRow>
          </SettingsSection>

          <SettingsSection title="Conversation">
            <SettingsRow
              label="Show tool messages"
              description="Render tool call summaries inside message turns."
            >
              <Switch
                label="Show tool messages"
                isLabelHidden
                value={settings.showToolMessages}
                onChange={(checked) =>
                  updateSettings({ showToolMessages: checked })
                }
              />
            </SettingsRow>

            <SettingsRow
              label="Show reasoning blocks"
              description="Expand agent chain-of-thought when provided."
            >
              <Switch
                label="Show reasoning blocks"
                isLabelHidden
                value={settings.showReasoningBlocks}
                onChange={(checked) =>
                  updateSettings({ showReasoningBlocks: checked })
                }
              />
            </SettingsRow>

            <SettingsRow label="Thinking depth">
              <SegmentedControl
                value={settings.thinkingLevel}
                onChange={(value) =>
                  updateSettings({ thinkingLevel: value as ThinkingLevel })
                }
                label="Thinking depth"
                size="sm"
              >
                <SegmentedControlItem value="low" label="Low" />
                <SegmentedControlItem value="medium" label="Medium" />
                <SegmentedControlItem value="high" label="High" />
              </SegmentedControl>
            </SettingsRow>
          </SettingsSection>

          <SettingsSection title="Runtime Paths">
            {pathsLoading ? (
              <div className="py-2">
                <Text type="supporting" color="secondary">
                  Loading storage paths…
                </Text>
              </div>
            ) : pathsError ? (
              <div className="py-2">
                <Text type="supporting" color="secondary">
                  {pathsError}
                </Text>
              </div>
            ) : paths ? (
              <>
                <SettingsRow label="Agent ID">
                  <span className="font-mono text-xs text-primary">
                    {paths.agentId || 'default'}
                  </span>
                </SettingsRow>
                <SettingsRow label="Sessions directory">
                  <span className="max-w-52 truncate font-mono text-xs text-secondary">
                    {paths.sessionsDir}
                  </span>
                  <IconButton
                    variant="ghost"
                    size="sm"
                    label="Copy sessions directory"
                    tooltip="Copy path"
                    icon={<Copy className="size-3.5" />}
                    onClick={onCopySessionsDir}
                  />
                </SettingsRow>
                <SettingsRow label="Store path">
                  <span className="max-w-52 truncate font-mono text-xs text-secondary">
                    {paths.storePath}
                  </span>
                  <IconButton
                    variant="ghost"
                    size="sm"
                    label="Copy store path"
                    tooltip="Copy path"
                    icon={<Copy className="size-3.5" />}
                    onClick={onCopyStorePath}
                  />
                </SettingsRow>
              </>
            ) : (
              <div className="py-2">
                <Text type="supporting" color="secondary">
                  Paths unavailable.
                </Text>
              </div>
            )}
          </SettingsSection>
        </div>

        <div className="flex justify-end border-t border-border bg-surface px-5 py-3">
          <Button variant="secondary" size="sm" label="Close" onClick={onClose} />
        </div>
      </div>
    </Dialog>
  )
}
