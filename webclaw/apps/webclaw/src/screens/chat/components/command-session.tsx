import { useEffect, useMemo, useState } from 'react'
import { MessageSquare, Search } from 'lucide-react'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { EmptyState } from '@astryxdesign/core/EmptyState'
import { Item } from '@astryxdesign/core/Item'
import { List } from '@astryxdesign/core/List'
import { Text } from '@astryxdesign/core/Text'
import { TextInput } from '@astryxdesign/core/TextInput'

type CommandSession = {
  key: string
  friendlyId: string
  title?: string
  derivedTitle?: string
  label?: string
}

type CommandSessionProps = {
  sessions: Array<CommandSession>
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (session: CommandSession) => void
}

function getSessionLabel(session: CommandSession) {
  return (
    session.label || session.title || session.derivedTitle || session.friendlyId
  )
}

function CommandSessionDialog({
  sessions,
  open,
  onOpenChange,
  onSelect,
}: CommandSessionProps) {
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return sessions
    return sessions.filter((s) => {
      const lbl = getSessionLabel(s).toLowerCase()
      return (
        lbl.includes(q) ||
        s.friendlyId.toLowerCase().includes(q) ||
        s.key.toLowerCase().includes(q)
      )
    })
  }, [query, sessions])

  useEffect(() => {
    setActiveIndex(0)
  }, [query, open])

  return (
    <Dialog
      isOpen={open}
      onOpenChange={(nextOpen) => {
        onOpenChange(nextOpen)
        if (!nextOpen) setQuery('')
      }}
      width={500}
      padding={0}
      purpose="info"
    >
      <div
        className="flex flex-col"
        onKeyDown={(e) => {
          if (filtered.length === 0) return
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setActiveIndex((idx) => (idx + 1) % filtered.length)
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActiveIndex((idx) => (idx - 1 + filtered.length) % filtered.length)
          } else if (e.key === 'Enter') {
            const chosen = filtered[activeIndex]
            if (chosen) {
              e.preventDefault()
              onSelect(chosen)
            }
          }
        }}
      >
        <DialogHeader
          title="Jump to session"
          onOpenChange={onOpenChange}
          hasDivider={false}
        />
        <div className="px-4 pb-3">
          <TextInput
            label="Search sessions"
            isLabelHidden
            value={query}
            onChange={(val) => setQuery(val)}
            placeholder="Search sessions..."
            hasAutoFocus
            hasClear
            startIcon={<Search className="size-4" />}
            width="100%"
          />
        </div>
        <div className="max-h-72 overflow-y-auto border-t border-border px-2 py-2">
          {filtered.length === 0 ? (
            <EmptyState
              isCompact
              title="No sessions found"
              description="Try another search keyword or create a new session."
            />
          ) : (
            <List density="compact" hasDividers={false}>
              {filtered.map((session, idx) => (
                <Item
                  key={session.key}
                  as="li"
                  label={getSessionLabel(session)}
                  description={session.friendlyId}
                  isHighlighted={idx === activeIndex}
                  startContent={
                    <MessageSquare
                      className="size-4 text-secondary"
                      aria-hidden="true"
                    />
                  }
                  onClick={() => onSelect(session)}
                />
              ))}
            </List>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-border bg-surface px-4 py-2">
          <Text type="supporting" color="secondary">
            Up / Down to select · Enter to open
          </Text>
          <Text type="supporting" color="secondary">
            Esc to close
          </Text>
        </div>
      </div>
    </Dialog>
  )
}

export { CommandSessionDialog }
