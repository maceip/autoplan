import { useState } from 'react'
import { Check, Monitor, Moon, Palette, Sun } from 'lucide-react'
import { Button } from '@astryxdesign/core/Button'
import { Item } from '@astryxdesign/core/Item'
import { List } from '@astryxdesign/core/List'
import { Popover } from '@astryxdesign/core/Popover'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@astryxdesign/core/SegmentedControl'
import { Text } from '@astryxdesign/core/Text'
import {
  ASTRYX_THEME_OPTIONS,
  useAstryxWorkbench,
} from '@/lib/astryx-theme'
import type { AstryxColorMode, AstryxThemeSlug } from '@/lib/astryx-theme'

export function ThemeAppearanceMenu() {
  const [open, setOpen] = useState(false)
  const { themeSlug, colorMode, resolvedMode, setThemeSlug, setColorMode } =
    useAstryxWorkbench()

  const activeThemeMeta =
    ASTRYX_THEME_OPTIONS.find((opt) => opt.slug === themeSlug) ??
    ASTRYX_THEME_OPTIONS[0]

  const popoverContent = (
    <div data-testid="theme-appearance-popover" className="space-y-3">
      <div className="space-y-1.5">
        <Text type="supporting" weight="semibold" color="secondary">
          Appearance
        </Text>
        <SegmentedControl
          value={colorMode}
          onChange={(val) => {
            void setColorMode(val as AstryxColorMode)
          }}
          label="Color mode"
          size="sm"
          layout="fill"
        >
          <SegmentedControlItem
            value="light"
            label="Light"
            icon={<Sun className="size-3.5" />}
            data-testid="color-mode-light"
          />
          <SegmentedControlItem
            value="dark"
            label="Dark"
            icon={<Moon className="size-3.5" />}
            data-testid="color-mode-dark"
          />
          <SegmentedControlItem
            value="system"
            label="System"
            icon={<Monitor className="size-3.5" />}
            data-testid="color-mode-system"
          />
        </SegmentedControl>
      </div>

      <div className="space-y-1.5">
        <Text type="supporting" weight="semibold" color="secondary">
          Theme Material
        </Text>
        <List density="compact" hasDividers={false}>
          {ASTRYX_THEME_OPTIONS.map((opt) => {
            const isSelected = themeSlug === opt.slug
            const bgSwatch =
              resolvedMode === 'dark' ? opt.darkSurface : opt.lightSurface
            return (
              <Item
                key={opt.slug}
                as="li"
                data-testid={`theme-option-${opt.slug}`}
                label={opt.label}
                description={opt.description}
                descriptionLines={1}
                isSelected={isSelected}
                onClick={() => {
                  void setThemeSlug(opt.slug as AstryxThemeSlug)
                }}
                startContent={
                  <span
                    className="inline-flex size-5 items-center justify-center rounded-md border border-border shadow-sm"
                    style={{ backgroundColor: bgSwatch }}
                    aria-hidden="true"
                  >
                    <span
                      className="size-2.5 rounded-full"
                      style={{ backgroundColor: opt.accent }}
                    />
                  </span>
                }
                endContent={
                  isSelected ? (
                    <Check className="size-4 text-accent" aria-hidden="true" />
                  ) : null
                }
              />
            )
          })}
        </List>
      </div>
    </div>
  )

  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      placement="below"
      alignment="end"
      width={300}
      padding={3}
      label="Theme and color appearance"
      content={popoverContent}
    >
      <Button
        data-testid="theme-appearance-trigger"
        variant="ghost"
        size="sm"
        icon={<Palette className="size-3.5" />}
        label={activeThemeMeta.label}
        aria-label={`Appearance theme: ${activeThemeMeta.label} (${resolvedMode})`}
      />
    </Popover>
  )
}
