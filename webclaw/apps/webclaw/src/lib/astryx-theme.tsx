import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import type { DefinedTheme } from '@astryxdesign/core/theme'
import { Theme } from '@astryxdesign/core/theme'
import { LayerProvider } from '@astryxdesign/core/Layer'
import { neutralTheme } from '@astryxdesign/theme-neutral/built'
import { stoneTheme } from '@astryxdesign/theme-stone/built'
import { matchaTheme } from '@astryxdesign/theme-matcha/built'
import { butterTheme } from '@astryxdesign/theme-butter/built'
import { chocolateTheme } from '@astryxdesign/theme-chocolate/built'
import { useChatSettingsStore } from '@/hooks/use-chat-settings'

export type AstryxThemeSlug =
  | 'neutral'
  | 'stone'
  | 'matcha'
  | 'butter'
  | 'chocolate'

export type AstryxColorMode = 'light' | 'dark' | 'system'
export type PlansViewMode = 'cards' | 'rows'

export type AstryxThemeOption = {
  slug: AstryxThemeSlug
  label: string
  description: string
  lightSurface: string
  darkSurface: string
  accent: string
}

export const ASTRYX_THEME_OPTIONS: Array<AstryxThemeOption> = [
  {
    slug: 'neutral',
    label: 'Neutral',
    description: 'Restrained warm grays where content leads',
    lightSurface: '#fafaf9',
    darkSurface: '#141413',
    accent: '#57534e',
  },
  {
    slug: 'stone',
    label: 'Stone',
    description: 'Quiet mineral slate for sustained reading',
    lightSurface: '#f5f6f8',
    darkSurface: '#15181c',
    accent: '#3b82f6',
  },
  {
    slug: 'matcha',
    label: 'Matcha',
    description: 'Calm botanical green tint with crisp ink contrast',
    lightSurface: '#f3f7f2',
    darkSurface: '#121a14',
    accent: '#2f855a',
  },
  {
    slug: 'butter',
    label: 'Butter',
    description: 'Warm sunlit paper surface for plan review',
    lightSurface: '#fbf7eb',
    darkSurface: '#1c1810',
    accent: '#b7791f',
  },
  {
    slug: 'chocolate',
    label: 'Chocolate',
    description: 'Rich espresso material with warm amber contrast',
    lightSurface: '#f8f3ef',
    darkSurface: '#191311',
    accent: '#a05a2c',
  },
]

const THEME_BY_SLUG: Record<AstryxThemeSlug, DefinedTheme> = {
  neutral: neutralTheme,
  stone: stoneTheme,
  matcha: matchaTheme,
  butter: butterTheme,
  chocolate: chocolateTheme,
}

export const ASTRYX_PREFS_STORAGE_KEY = 'autoplan-astryx-prefs'

export type UiPreferencesState = {
  themeSlug: AstryxThemeSlug
  colorMode: AstryxColorMode
  plansViewMode: PlansViewMode
  pinnedPlanIds: Array<string>
  collapsedProjectIds: Array<string>
}

const DEFAULT_PREFS: UiPreferencesState = {
  themeSlug: 'neutral',
  colorMode: 'dark',
  plansViewMode: 'cards',
  pinnedPlanIds: [],
  collapsedProjectIds: [],
}

function isValidThemeSlug(value: unknown): value is AstryxThemeSlug {
  return (
    value === 'neutral' ||
    value === 'stone' ||
    value === 'matcha' ||
    value === 'butter' ||
    value === 'chocolate'
  )
}

function isValidColorMode(value: unknown): value is AstryxColorMode {
  return value === 'light' || value === 'dark' || value === 'system'
}

function isValidPlansViewMode(value: unknown): value is PlansViewMode {
  return value === 'cards' || value === 'rows'
}

function parseStoredPrefs(): Partial<UiPreferencesState> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(ASTRYX_PREFS_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    return {
      themeSlug: isValidThemeSlug(parsed.themeSlug)
        ? parsed.themeSlug
        : undefined,
      colorMode: isValidColorMode(parsed.colorMode)
        ? parsed.colorMode
        : undefined,
      plansViewMode: isValidPlansViewMode(parsed.plansViewMode)
        ? parsed.plansViewMode
        : undefined,
      pinnedPlanIds: Array.isArray(parsed.pinnedPlanIds)
        ? parsed.pinnedPlanIds.map(String).filter(Boolean)
        : undefined,
      collapsedProjectIds: Array.isArray(parsed.collapsedProjectIds)
        ? parsed.collapsedProjectIds.map(String).filter(Boolean)
        : undefined,
    }
  } catch {
    return {}
  }
}

function saveStoredPrefs(prefs: UiPreferencesState) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(ASTRYX_PREFS_STORAGE_KEY, JSON.stringify(prefs))
  } catch {
    // Ignore storage quota errors cleanly
  }
}

function resolveColorScheme(colorMode: AstryxColorMode): 'light' | 'dark' {
  if (colorMode === 'dark') return 'dark'
  if (colorMode === 'light') return 'light'
  if (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  ) {
    return 'dark'
  }
  return 'light'
}

function applyDocumentTheme(
  themeSlug: AstryxThemeSlug,
  colorMode: AstryxColorMode,
) {
  if (typeof document === 'undefined') return 'dark' as const
  const root = document.documentElement
  const resolved = resolveColorScheme(colorMode)
  root.setAttribute('data-astryx-theme', themeSlug)
  root.setAttribute('data-theme', resolved)
  root.classList.remove('light', 'dark', 'system')
  root.classList.add(colorMode)
  if (colorMode === 'system' && resolved === 'dark') {
    root.classList.add('dark')
  }
  root.style.colorScheme = resolved
  if (typeof window !== 'undefined' && window.parent !== window) {
    try {
      window.parent.postMessage(
        {
          type: 'astryx:theme-changed',
          themeSlug,
          colorMode,
          resolvedMode: resolved,
        },
        '*',
      )
    } catch {
      // Ignore cross-origin frame postMessage failures
    }
  }
  return resolved
}

export type AstryxWorkbenchContextValue = UiPreferencesState & {
  resolvedMode: 'light' | 'dark'
  hydrated: boolean
  setThemeSlug: (slug: AstryxThemeSlug) => Promise<void>
  setColorMode: (mode: AstryxColorMode) => Promise<void>
  setPlansViewMode: (view: PlansViewMode) => Promise<void>
  togglePinPlan: (planId: string) => Promise<void>
  toggleCollapseProject: (projectId: string) => Promise<void>
  refreshPreferences: () => Promise<void>
}

const AstryxWorkbenchContext =
  createContext<AstryxWorkbenchContextValue | null>(null)

type BackendUiPrefsPayload = {
  success?: boolean
  preferences?: {
    theme_slug?: string
    color_mode?: string
    plans_view_mode?: string
    pinned_plan_ids?: Array<string>
    collapsed_project_ids?: Array<string>
  }
}

export function AstryxWorkbenchProvider({
  children,
}: {
  children: ReactNode
}) {
  const [prefs, setPrefs] = useState<UiPreferencesState>(DEFAULT_PREFS)
  const [hydrated, setHydrated] = useState(false)
  const [resolvedMode, setResolvedMode] = useState<'light' | 'dark'>('dark')

  const mergeAndApply = useCallback((next: UiPreferencesState) => {
    setPrefs(next)
    saveStoredPrefs(next)
    useChatSettingsStore.getState().updateSettings({ theme: next.colorMode })
    setResolvedMode(applyDocumentTheme(next.themeSlug, next.colorMode))
  }, [])

  const patchServerPreferences = useCallback(
    async (payload: Record<string, unknown>) => {
      try {
        const res = await fetch('/api/autoplan/ui/preferences', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!res.ok) return
        const data = (await res.json()) as BackendUiPrefsPayload
        if (data.success && data.preferences) {
          const p = data.preferences
          const synced: UiPreferencesState = {
            themeSlug: isValidThemeSlug(p.theme_slug)
              ? p.theme_slug
              : DEFAULT_PREFS.themeSlug,
            colorMode: isValidColorMode(p.color_mode)
              ? p.color_mode
              : DEFAULT_PREFS.colorMode,
            plansViewMode: isValidPlansViewMode(p.plans_view_mode)
              ? p.plans_view_mode
              : DEFAULT_PREFS.plansViewMode,
            pinnedPlanIds: Array.isArray(p.pinned_plan_ids)
              ? p.pinned_plan_ids.map(String).filter(Boolean)
              : [],
            collapsedProjectIds: Array.isArray(p.collapsed_project_ids)
              ? p.collapsed_project_ids.map(String).filter(Boolean)
              : [],
          }
          mergeAndApply(synced)
        }
      } catch {
        // Offline / unit-test mode: keep optimistic local state
      }
    },
    [mergeAndApply],
  )

  const refreshPreferences = useCallback(async () => {
    try {
      const res = await fetch('/api/autoplan/ui/preferences')
      if (!res.ok) return
      const data = (await res.json()) as BackendUiPrefsPayload
      if (!data.success || !data.preferences) return
      const p = data.preferences
      mergeAndApply({
        themeSlug: isValidThemeSlug(p.theme_slug)
          ? p.theme_slug
          : DEFAULT_PREFS.themeSlug,
        colorMode: isValidColorMode(p.color_mode)
          ? p.color_mode
          : DEFAULT_PREFS.colorMode,
        plansViewMode: isValidPlansViewMode(p.plans_view_mode)
          ? p.plans_view_mode
          : DEFAULT_PREFS.plansViewMode,
        pinnedPlanIds: Array.isArray(p.pinned_plan_ids)
          ? p.pinned_plan_ids.map(String).filter(Boolean)
          : [],
        collapsedProjectIds: Array.isArray(p.collapsed_project_ids)
          ? p.collapsed_project_ids.map(String).filter(Boolean)
          : [],
      })
    } catch {
      // Ignore transient network errors when server is not reachable
    }
  }, [mergeAndApply])

  useEffect(() => {
    const local = parseStoredPrefs()
    const initial: UiPreferencesState = {
      ...DEFAULT_PREFS,
      ...local,
    }
    mergeAndApply(initial)
    setHydrated(true)
    void refreshPreferences()
  }, [mergeAndApply, refreshPreferences])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onMediaChange = () => {
      if (prefs.colorMode === 'system') {
        setResolvedMode(applyDocumentTheme(prefs.themeSlug, 'system'))
      }
    }
    media.addEventListener('change', onMediaChange)
    return () => media.removeEventListener('change', onMediaChange)
  }, [prefs.themeSlug, prefs.colorMode])

  useEffect(() => {
    setResolvedMode(applyDocumentTheme(prefs.themeSlug, prefs.colorMode))
  }, [prefs.themeSlug, prefs.colorMode])

  const setThemeSlug = useCallback(
    async (themeSlug: AstryxThemeSlug) => {
      const next = { ...prefs, themeSlug }
      mergeAndApply(next)
      await patchServerPreferences({ theme_slug: themeSlug })
    },
    [prefs, mergeAndApply, patchServerPreferences],
  )

  const setColorMode = useCallback(
    async (colorMode: AstryxColorMode) => {
      const next = { ...prefs, colorMode }
      mergeAndApply(next)
      await patchServerPreferences({ color_mode: colorMode })
    },
    [prefs, mergeAndApply, patchServerPreferences],
  )

  const setPlansViewMode = useCallback(
    async (plansViewMode: PlansViewMode) => {
      const next = { ...prefs, plansViewMode }
      mergeAndApply(next)
      await patchServerPreferences({ plans_view_mode: plansViewMode })
    },
    [prefs, mergeAndApply, patchServerPreferences],
  )

  const togglePinPlan = useCallback(
    async (planId: string) => {
      const exists = prefs.pinnedPlanIds.includes(planId)
      const pinnedPlanIds = exists
        ? prefs.pinnedPlanIds.filter((id) => id !== planId)
        : [...prefs.pinnedPlanIds, planId]
      const next = { ...prefs, pinnedPlanIds }
      mergeAndApply(next)
      await patchServerPreferences({ pinned_plan_ids: pinnedPlanIds })
    },
    [prefs, mergeAndApply, patchServerPreferences],
  )

  const toggleCollapseProject = useCallback(
    async (projectId: string) => {
      const exists = prefs.collapsedProjectIds.includes(projectId)
      const collapsedProjectIds = exists
        ? prefs.collapsedProjectIds.filter((id) => id !== projectId)
        : [...prefs.collapsedProjectIds, projectId]
      const next = { ...prefs, collapsedProjectIds }
      mergeAndApply(next)
      await patchServerPreferences({
        collapsed_project_ids: collapsedProjectIds,
      })
    },
    [prefs, mergeAndApply, patchServerPreferences],
  )

  const activeTheme = THEME_BY_SLUG[prefs.themeSlug]

  const value = useMemo<AstryxWorkbenchContextValue>(
    () => ({
      ...prefs,
      resolvedMode,
      hydrated,
      setThemeSlug,
      setColorMode,
      setPlansViewMode,
      togglePinPlan,
      toggleCollapseProject,
      refreshPreferences,
    }),
    [
      prefs,
      resolvedMode,
      hydrated,
      setThemeSlug,
      setColorMode,
      setPlansViewMode,
      togglePinPlan,
      toggleCollapseProject,
      refreshPreferences,
    ],
  )

  return (
    <AstryxWorkbenchContext.Provider value={value}>
      <Theme theme={activeTheme} mode={prefs.colorMode}>
        <LayerProvider>{children}</LayerProvider>
      </Theme>
    </AstryxWorkbenchContext.Provider>
  )
}

export function useAstryxWorkbench(): AstryxWorkbenchContextValue {
  const ctx = useContext(AstryxWorkbenchContext)
  if (!ctx) {
    return {
      ...DEFAULT_PREFS,
      resolvedMode: 'dark',
      hydrated: false,
      setThemeSlug: async () => {},
      setColorMode: async () => {},
      setPlansViewMode: async () => {},
      togglePinPlan: async () => {},
      toggleCollapseProject: async () => {},
      refreshPreferences: async () => {},
    }
  }
  return ctx
}
