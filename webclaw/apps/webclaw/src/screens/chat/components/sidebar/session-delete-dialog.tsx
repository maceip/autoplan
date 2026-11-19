import { AlertDialog } from '@astryxdesign/core/AlertDialog'

type SessionDeleteDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  sessionTitle: string
  onConfirm: () => void
  onCancel: () => void
}

export function SessionDeleteDialog({
  open,
  onOpenChange,
  sessionTitle,
  onConfirm,
  onCancel,
}: SessionDeleteDialogProps) {
  return (
    <AlertDialog
      isOpen={open}
      onOpenChange={(nextOpen) => {
        onOpenChange(nextOpen)
        if (!nextOpen) onCancel()
      }}
      title="Delete session"
      description={`Remove "${sessionTitle}" from your session list?`}
      cancelLabel="Cancel"
      actionLabel="Delete"
      actionVariant="destructive"
      onAction={onConfirm}
    />
  )
}
