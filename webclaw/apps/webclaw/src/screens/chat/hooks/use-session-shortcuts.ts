import { useHotkey } from '@tanstack/react-hotkeys'

type SessionShortcutOptions = {
  onNewSession: () => void
  onSearchSessions: () => void
}

function useSessionShortcuts({
  onNewSession,
  onSearchSessions,
}: SessionShortcutOptions) {
  useHotkey(
    'Mod+K',
    function handleSearchHotkey(event) {
      if (event.altKey || isEditableTarget(event.target)) return
      event.preventDefault()
      onSearchSessions()
    },
    { preventDefault: true },
  )

  useHotkey(
    'Mod+Shift+O',
    function handleNewSessionHotkey(event) {
      if (event.altKey || isEditableTarget(event.target)) return
      event.preventDefault()
      onNewSession()
    },
    { preventDefault: true },
  )
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  return target.isContentEditable
}

export { useSessionShortcuts }
