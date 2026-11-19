import { useState } from 'react'
import { Download } from 'lucide-react'
import { IconButton } from '@astryxdesign/core/IconButton'
import { Item } from '@astryxdesign/core/Item'
import { List } from '@astryxdesign/core/List'
import { Popover } from '@astryxdesign/core/Popover'

type ExportFormat = 'markdown' | 'json' | 'text'

type ExportMenuProps = {
  onExport: (format: ExportFormat) => void
  disabled?: boolean
}

const formats: Array<{ format: ExportFormat; label: string; ext: string }> = [
  { format: 'markdown', label: 'Markdown', ext: '.md' },
  { format: 'json', label: 'JSON', ext: '.json' },
  { format: 'text', label: 'Plain Text', ext: '.txt' },
]

export function ExportMenu({ onExport, disabled }: ExportMenuProps) {
  const [open, setOpen] = useState(false)

  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      isEnabled={!disabled}
      placement="below"
      alignment="end"
      width={190}
      padding={1}
      label="Export conversation"
      content={
        <List density="compact" hasDividers={false}>
          {formats.map(({ format, label, ext }) => (
            <Item
              key={format}
              as="li"
              label={label}
              endContent={
                <span className="font-mono text-xs text-secondary">{ext}</span>
              }
              onClick={() => {
                setOpen(false)
                onExport(format)
              }}
            />
          ))}
        </List>
      }
    >
      <IconButton
        variant="ghost"
        size="sm"
        label="Export conversation"
        tooltip={disabled ? 'Nothing to export' : 'Export conversation'}
        isDisabled={disabled}
        icon={<Download className="size-3.5" />}
      />
    </Popover>
  )
}
