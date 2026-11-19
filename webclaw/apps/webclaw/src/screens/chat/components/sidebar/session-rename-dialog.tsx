import { useEffect, useState } from 'react'
import { Button } from '@astryxdesign/core/Button'
import { Dialog, DialogHeader } from '@astryxdesign/core/Dialog'
import { TextInput } from '@astryxdesign/core/TextInput'

type SessionRenameDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  sessionTitle: string
  onSave: (newTitle: string) => void
  onCancel: () => void
}

export function SessionRenameDialog({
  open,
  onOpenChange,
  sessionTitle,
  onSave,
  onCancel,
}: SessionRenameDialogProps) {
  const [title, setTitle] = useState(sessionTitle)

  useEffect(() => {
    if (open) {
      setTitle(sessionTitle)
    }
  }, [open, sessionTitle])

  function submitRename() {
    const trimmed = title.trim()
    if (!trimmed) return
    onSave(trimmed)
  }

  return (
    <Dialog
      isOpen={open}
      onOpenChange={onOpenChange}
      width={400}
      padding={0}
      purpose="form"
    >
      <div className="flex flex-col">
        <DialogHeader
          title="Rename session"
          subtitle="Choose a clear name for this session."
          onOpenChange={onOpenChange}
          hasDivider
        />
        <form
          onSubmit={(e) => {
            e.preventDefault()
            submitRename()
          }}
          className="space-y-4 p-4"
        >
          <TextInput
            label="Session title"
            value={title}
            onChange={(val) => setTitle(val)}
            placeholder="Session name"
            hasAutoFocus
            width="100%"
          />
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              label="Cancel"
              onClick={onCancel}
            />
            <Button
              type="submit"
              variant="primary"
              size="sm"
              label="Save"
              isDisabled={!title.trim()}
            />
          </div>
        </form>
      </div>
    </Dialog>
  )
}
