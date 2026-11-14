import { HugeiconsIcon } from '@hugeicons/react'
import {
  Search01Icon,
  Settings01Icon,
  SidebarLeft01Icon,
} from '@hugeicons/core-free-icons'
import { AnimatePresence, motion } from 'motion/react'
import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useChatSettings } from '../hooks/use-chat-settings'
import { useDeleteSession } from '../hooks/use-delete-session'
import { useRenameSession } from '../hooks/use-rename-session'
import { useSessionShortcuts } from '../hooks/use-session-shortcuts'
import { SettingsDialog } from './settings-dialog'
import { SessionRenameDialog } from './sidebar/session-rename-dialog'
import { SessionDeleteDialog } from './sidebar/session-delete-dialog'
import { CommandSessionDialog } from './command-session'
import type { DiscoveredRepo, ProjectInfo, SessionMeta } from '../types'
import {
  TooltipContent,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { Button, buttonVariants } from '@/components/ui/button'
import { WebClawIconBig } from '@/components/icons/webclaw-big'

type ChatSidebarProps = {
  sessions: Array<SessionMeta>
  projects: Array<ProjectInfo>
  activeProjectId: string
  defaultProjectId: string
  activeFriendlyId: string
  creatingSession: boolean
  onCreateSessionInProject: (projectId: string) => void
  onSelectProject?: (projectId: string) => void
  onProjectsChanged?: () => void
  isCollapsed: boolean
  onToggleCollapse: () => void
  onSelectSession?: () => void
  onActiveSessionDelete?: () => void
  hideBrandHeader?: boolean
  onStartDemo?: () => void
  startingDemo?: boolean
  canDispatchDemo?: boolean
}

function sessionDisplayLabel(s: SessionMeta): string {
  return (
    s.label?.trim() ||
    s.title?.trim() ||
    s.derivedTitle?.trim() ||
    s.friendlyId
  )
}

function FolderPlusIcon() {
  return (
    <svg
      viewBox="0 0 18 18"
      className="size-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      aria-hidden="true"
    >
      <path d="M2.25 5A1.5 1.5 0 0 1 3.75 3.5h3l1.45 1.5h6.05A1.5 1.5 0 0 1 15.75 6.5v6.5a1.5 1.5 0 0 1-1.5 1.5H3.75a1.5 1.5 0 0 1-1.5-1.5V5Z" />
      <path d="M9 8v4M7 10h4" />
    </svg>
  )
}

function ChatSidebarComponent({
  sessions,
  projects,
  activeProjectId,
  defaultProjectId,
  activeFriendlyId,
  creatingSession,
  onCreateSessionInProject,
  onSelectProject,
  onProjectsChanged,
  isCollapsed,
  onToggleCollapse,
  onSelectSession,
  onActiveSessionDelete,
  hideBrandHeader = false,
  onStartDemo,
  startingDemo = false,
  canDispatchDemo = true,
}: ChatSidebarProps) {
  const {
    settingsOpen,
    setSettingsOpen,
    pathsLoading,
    pathsError,
    paths,
    handleOpenSettings,
    closeSettings,
    copySessionsDir,
    copyStorePath,
  } = useChatSettings()
  const { deleteSession } = useDeleteSession()
  const { renameSession } = useRenameSession()
  const transition = {
    duration: 0.15,
    ease: isCollapsed ? 'easeIn' : 'easeOut',
  } as const

  const [renameDialogOpen, setRenameDialogOpen] = useState(false)
  const [renameSessionKey, setRenameSessionKey] = useState<string | null>(null)
  const [renameSessionTitle, setRenameSessionTitle] = useState('')

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteSessionKey, setDeleteSessionKey] = useState<string | null>(null)
  const [deleteFriendlyId, setDeleteFriendlyId] = useState<string | null>(null)
  const [deleteSessionTitle, setDeleteSessionTitle] = useState('')
  const [searchDialogOpen, setSearchDialogOpen] = useState(false)

  const [addProjectOpen, setAddProjectOpen] = useState(false)
  const [discoveredRepos, setDiscoveredRepos] = useState<Array<DiscoveredRepo>>(
    [],
  )
  const [newProjName, setNewProjName] = useState('')
  const [newProjPath, setNewProjPath] = useState('')
  const [projBusy, setProjBusy] = useState(false)
  const [projError, setProjError] = useState('')

  const navigate = useNavigate()

  useSessionShortcuts({
    onNewSession: () =>
      onCreateSessionInProject(activeProjectId || defaultProjectId),
    onSearchSessions: () => setSearchDialogOpen(true),
  })

  const loadDiscoveredRepos = useCallback(async () => {
    try {
      const res = await fetch('/api/autoplan/projects/discover')
      const data = (await res.json()) as {
        success?: boolean
        repositories?: Array<DiscoveredRepo>
      }
      if (res.ok && data.repositories) {
        setDiscoveredRepos(data.repositories)
      }
    } catch {
      // ignore discovery errors
    }
  }, [])

  useEffect(() => {
    if (addProjectOpen) {
      void loadDiscoveredRepos()
    }
  }, [addProjectOpen, loadDiscoveredRepos])

  async function registerProject(payload: {
    name: string
    repo_path: string
    default_branch?: string
  }) {
    setProjBusy(true)
    setProjError('')
    try {
      const res = await fetch('/api/autoplan/projects', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const body = (await res.json()) as {
        success?: boolean
        project?: ProjectInfo
        error?: string
      }
      if (!res.ok || body.success === false) {
        throw new Error(body.error || `HTTP ${res.status}`)
      }
      setNewProjName('')
      setNewProjPath('')
      setAddProjectOpen(false)
      onProjectsChanged?.()
      if (body.project?.id) {
        onSelectProject?.(body.project.id)
      }
      void loadDiscoveredRepos()
    } catch (err) {
      setProjError(err instanceof Error ? err.message : String(err))
    } finally {
      setProjBusy(false)
    }
  }

  const groupedProjects = useMemo(() => {
    const fallbackId = defaultProjectId || projects[0]?.id || 'default'
    const buckets = new Map<string, Array<SessionMeta>>()
    for (const p of projects) {
      buckets.set(p.id, [])
    }
    for (const s of sessions) {
      const pid = s.projectId && buckets.has(s.projectId) ? s.projectId : fallbackId
      const existing = buckets.get(pid)
      if (existing) {
        existing.push(s)
      } else {
        buckets.set(pid, [s])
      }
    }
    return projects.map((proj) => ({
      project: proj,
      sessions: buckets.get(proj.id) || [],
    }))
  }, [defaultProjectId, projects, sessions])

  function handleSearchSelect(session: SessionMeta) {
    setSearchDialogOpen(false)
    void navigate({
      to: '/chat/$sessionKey',
      params: { sessionKey: session.friendlyId },
    })
    onSelectSession?.()
  }

  function handleOpenRename(session: SessionMeta) {
    setRenameSessionKey(session.key)
    setRenameSessionTitle(sessionDisplayLabel(session))
    setRenameDialogOpen(true)
  }

  function handleSaveRename(newTitle: string) {
    if (renameSessionKey) {
      void renameSession(renameSessionKey, newTitle)
    }
    setRenameDialogOpen(false)
    setRenameSessionKey(null)
  }

  function handleOpenDelete(session: SessionMeta) {
    setDeleteSessionKey(session.key)
    setDeleteFriendlyId(session.friendlyId)
    setDeleteSessionTitle(sessionDisplayLabel(session))
    setDeleteDialogOpen(true)
  }

  function handleConfirmDelete() {
    if (deleteSessionKey && deleteFriendlyId) {
      const isActive = deleteFriendlyId === activeFriendlyId
      if (isActive && onActiveSessionDelete) {
        onActiveSessionDelete()
      }
      void deleteSession(deleteSessionKey, deleteFriendlyId, isActive)
    }
    setDeleteDialogOpen(false)
    setDeleteSessionKey(null)
    setDeleteFriendlyId(null)
  }

  const unregisteredRepos = discoveredRepos.filter((r) => !r.already_registered)

  return (
    <motion.aside
      initial={false}
      animate={{ width: isCollapsed ? 48 : 272 }}
      transition={transition}
      className="border-r border-primary-200 h-full overflow-hidden bg-primary-100 flex flex-col"
    >
      {!hideBrandHeader ? (
        <motion.div
          layout
          transition={{ layout: transition }}
          className="flex items-center h-11 px-2 justify-between"
        >
          <AnimatePresence initial={false}>
            {!isCollapsed ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={transition}
              >
                <Link
                  to="/new"
                  data-testid="desktop-brand-link"
                  className={cn(
                    buttonVariants({ variant: 'ghost', size: 'sm' }),
                    'w-full pl-1.5 justify-start',
                  )}
                >
                  <WebClawIconBig className="size-5" />
                  autobot
                </Link>
              </motion.div>
            ) : null}
          </AnimatePresence>
          <TooltipProvider>
            <TooltipRoot>
              <TooltipTrigger
                onClick={onToggleCollapse}
                render={
                  <Button size="icon-sm" variant="ghost" aria-label="Toggle sidebar">
                    <HugeiconsIcon
                      icon={SidebarLeft01Icon}
                      size={18}
                      strokeWidth={1.5}
                    />
                  </Button>
                }
              />
              <TooltipContent side="right">
                {isCollapsed ? 'Open sidebar' : 'Collapse sidebar'}
              </TooltipContent>
            </TooltipRoot>
          </TooltipProvider>
        </motion.div>
      ) : null}

      {isCollapsed ? (
        <div className="flex flex-col items-center gap-1.5 pt-2.5">
          <Button
            size="icon-sm"
            variant="ghost"
            disabled={creatingSession}
            aria-label="New session"
            onClick={() =>
              onCreateSessionInProject(activeProjectId || defaultProjectId)
            }
          >
            +
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Search sessions"
            onClick={() => setSearchDialogOpen(true)}
          >
            <HugeiconsIcon icon={Search01Icon} size={17} strokeWidth={1.5} />
          </Button>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between px-3 pt-3 pb-1.5">
            <span className="text-xs font-medium text-primary-600">
              Projects
            </span>
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                data-testid="sidebar-search-button"
                aria-label="Search sessions"
                onClick={() => setSearchDialogOpen(true)}
                className="flex size-6 items-center justify-center rounded-md text-primary-600 hover:bg-primary-200/70 hover:text-primary-950"
              >
                <HugeiconsIcon icon={Search01Icon} size={14} strokeWidth={1.6} />
              </button>
              <button
                type="button"
                data-testid="add-project-button"
                aria-label="Add project"
                aria-expanded={addProjectOpen}
                onClick={() => {
                  setProjError('')
                  setAddProjectOpen((prev) => !prev)
                }}
                className="flex size-6 items-center justify-center rounded-md text-primary-600 hover:bg-primary-200/70 hover:text-primary-950"
              >
                <FolderPlusIcon />
              </button>
            </div>
          </div>

          {addProjectOpen ? (
            <div
              data-testid="add-project-panel"
              className="mx-2.5 mb-2 rounded-lg border border-primary-200 bg-surface p-2.5 text-xs space-y-2"
            >
              {projError ? (
                <div className="text-[11px] text-red-500">{projError}</div>
              ) : null}

              <input
                type="text"
                data-testid="project-path-input"
                value={newProjPath}
                onChange={(e) => setNewProjPath(e.target.value)}
                placeholder="/path/to/git/repo"
                className="h-7 w-full rounded-md border border-primary-200 bg-primary-100 px-2 font-mono text-[11px] text-primary-950 outline-none"
              />
              <input
                type="text"
                data-testid="project-name-input"
                value={newProjName}
                onChange={(e) => setNewProjName(e.target.value)}
                placeholder="Display name (optional)"
                className="h-7 w-full rounded-md border border-primary-200 bg-primary-100 px-2 text-xs text-primary-950 outline-none"
              />
              <div className="flex items-center justify-end gap-1.5">
                <button
                  type="button"
                  onClick={() => setAddProjectOpen(false)}
                  className="h-7 rounded-md px-2 text-xs text-primary-600 hover:text-primary-900"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-testid="project-submit-button"
                  disabled={!newProjPath.trim() || projBusy}
                  onClick={() =>
                    void registerProject({
                      name: newProjName.trim(),
                      repo_path: newProjPath.trim(),
                    })
                  }
                  className="h-7 rounded-md bg-primary-900 px-2.5 text-xs font-medium text-surface disabled:opacity-40"
                >
                  {projBusy ? 'Adding…' : 'Add'}
                </button>
              </div>

              {unregisteredRepos.length > 0 ? (
                <div className="border-t border-primary-200 pt-1.5 space-y-0.5 max-h-28 overflow-y-auto">
                  {unregisteredRepos.slice(0, 6).map((repo) => (
                    <button
                      key={repo.repo_path}
                      type="button"
                      data-testid={`discover-add-${repo.name}`}
                      disabled={projBusy}
                      onClick={() =>
                        void registerProject({
                          name: repo.name,
                          repo_path: repo.repo_path,
                          default_branch: repo.default_branch,
                        })
                      }
                      className="flex w-full items-center justify-between rounded px-1.5 py-1 text-left hover:bg-primary-100"
                    >
                      <span className="truncate font-medium text-primary-900">
                        {repo.name}
                      </span>
                      <span className="text-[11px] text-primary-600">+</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          <div
            data-testid="sidebar-projects-list"
            className="flex-1 min-h-0 overflow-y-auto px-2 pb-2 space-y-2"
          >
            {groupedProjects.map(({ project, sessions: projSessions }) => {
              const isProjActive = project.id === activeProjectId
              return (
                <section
                  key={project.id}
                  data-testid={`project-group-${project.id}`}
                  className="space-y-0.5"
                >
                  <div
                    className={cn(
                      'flex h-7 items-center justify-between rounded-md px-2 transition-colors',
                      isProjActive
                        ? 'text-primary-950'
                        : 'text-primary-700 hover:bg-primary-200/40',
                    )}
                  >
                    <button
                      type="button"
                      data-testid={`project-select-${project.id}`}
                      onClick={() => onSelectProject?.(project.id)}
                      title={project.repo_path}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      <svg
                        viewBox="0 0 18 18"
                        className="size-4 shrink-0 text-primary-600"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={1.5}
                        aria-hidden="true"
                      >
                        <path d="M2.25 5A1.5 1.5 0 0 1 3.75 3.5h3l1.45 1.5h6.05A1.5 1.5 0 0 1 15.75 6.5v6.5a1.5 1.5 0 0 1-1.5 1.5H3.75a1.5 1.5 0 0 1-1.5-1.5V5Z" />
                      </svg>
                      <span className="truncate text-[13px] font-medium">
                        {project.name}
                      </span>
                    </button>

                    <button
                      type="button"
                      data-testid={`project-new-session-${project.id}`}
                      disabled={creatingSession}
                      aria-label={`New session in ${project.name}`}
                      onClick={() => onCreateSessionInProject(project.id)}
                      className="flex size-6 shrink-0 items-center justify-center rounded-md text-sm text-primary-600 hover:bg-primary-200/70 hover:text-primary-950 disabled:opacity-40"
                    >
                      +
                    </button>
                  </div>

                  <div className="pl-4 space-y-0.5">
                    {projSessions.map((session) => {
                      const isActive = session.friendlyId === activeFriendlyId
                      return (
                        <div
                          key={session.key}
                          className={cn(
                            'group flex h-8 items-center justify-between gap-1 rounded-md px-2 text-[13px] transition-colors',
                            isActive
                              ? 'bg-primary-200/70 font-medium text-primary-950'
                              : 'text-primary-700 hover:bg-primary-200/40 hover:text-primary-950',
                          )}
                        >
                          <Link
                            to="/chat/$sessionKey"
                            params={{ sessionKey: session.friendlyId }}
                            data-testid={`sidebar-session-${session.friendlyId}`}
                            onClick={() => {
                              onSelectProject?.(project.id)
                              onSelectSession?.()
                            }}
                            className="flex min-w-0 flex-1 items-center gap-1.5 py-1"
                          >
                            <span className="truncate">
                              {sessionDisplayLabel(session)}
                            </span>
                          </Link>

                          <div className="hidden items-center gap-0.5 group-hover:flex">
                            <button
                              type="button"
                              aria-label="Rename session"
                              onClick={() => handleOpenRename(session)}
                              className="rounded px-1 py-0.5 text-[11px] text-primary-600 hover:bg-primary-200 hover:text-primary-950"
                            >
                              ✎
                            </button>
                            <button
                              type="button"
                              aria-label="Delete session"
                              onClick={() => handleOpenDelete(session)}
                              className="rounded px-1 py-0.5 text-[11px] text-primary-600 hover:bg-red-500/20 hover:text-red-500"
                            >
                              ×
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </section>
              )
            })}
          </div>
        </>
      )}

      <CommandSessionDialog
        sessions={sessions}
        open={searchDialogOpen}
        onOpenChange={setSearchDialogOpen}
        onSelect={handleSearchSelect}
      />

      <div className="flex items-center justify-between gap-1.5 border-t border-primary-200 bg-primary-100 px-2.5 py-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={handleOpenSettings}
          title={isCollapsed ? 'Settings' : undefined}
          className={cn(
            'justify-start pl-1 text-primary-700 hover:text-primary-950',
            isCollapsed ? 'w-full justify-center px-0' : '',
          )}
        >
          <HugeiconsIcon
            icon={Settings01Icon}
            size={16}
            strokeWidth={1.5}
            className="min-w-4"
          />
          {!isCollapsed ? <span>Settings</span> : null}
        </Button>

        {!isCollapsed && onStartDemo ? (
          <button
            type="button"
            data-testid="start-demo-button"
            disabled={!canDispatchDemo || startingDemo}
            onClick={onStartDemo}
            className="rounded-md px-2 py-1 text-xs text-primary-600 hover:bg-primary-200/60 hover:text-primary-950 disabled:opacity-35 disabled:pointer-events-none"
          >
            {startingDemo ? 'Starting…' : 'Start Demo'}
          </button>
        ) : null}
      </div>

      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        pathsLoading={pathsLoading}
        pathsError={pathsError}
        paths={paths}
        onClose={closeSettings}
        onCopySessionsDir={copySessionsDir}
        onCopyStorePath={copyStorePath}
      />

      <SessionRenameDialog
        open={renameDialogOpen}
        onOpenChange={setRenameDialogOpen}
        sessionTitle={renameSessionTitle}
        onSave={handleSaveRename}
        onCancel={() => setRenameDialogOpen(false)}
      />

      <SessionDeleteDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        sessionTitle={deleteSessionTitle}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteDialogOpen(false)}
      />
    </motion.aside>
  )
}

const MemoizedChatSidebar = memo(ChatSidebarComponent)

export { MemoizedChatSidebar as ChatSidebar }
