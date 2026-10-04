import { createRoot } from 'react-dom/client'
import FiltersPage from '../src/pages/FiltersPage'
import type { FilterCategoryName, FilterEntry, FilterInput, FiltersResponse, waitForBridge } from '../src/bridge'
import '../src/styles.css'

const query = new URLSearchParams(window.location.search)
const calls: unknown[][] = []
Object.assign(window, { filterCalls: calls })

const categoryNames: FilterCategoryName[] = ['words', 'phrases', 'patterns']
const defaults: Record<FilterCategoryName, string[]> = {
  words: ['alpha'],
  phrases: ['hello, world'],
  patterns: ['^safe$'],
}

function entries(name: FilterCategoryName, values: string[], origins?: ('default' | 'local')[]): FilterEntry[] {
  return values.map((value, index) => ({
    value,
    origin: origins?.[index] ?? (defaults[name].includes(value) ? 'default' : 'local'),
    valid: true,
    error: null,
  }))
}

function initialValues(): Record<FilterCategoryName, string[]> {
  if (query.has('large')) {
    return {
      words: Array.from({ length: 80 }, (_, index) => `word-${index + 1}`),
      phrases: Array.from({ length: 65 }, (_, index) => `phrase ${index + 1}, with punctuation`),
      patterns: ['^safe$', ...Array.from({ length: 18 }, (_, index) => `^pattern-${index + 1}$`)],
    }
  }
  return {
    words: ['alpha', 'local-word'],
    phrases: ['hello, world', 'phrase, with, commas'],
    patterns: ['^safe$', '^safe$', '\\burl\\b'],
  }
}

function responseFrom(values: Record<FilterCategoryName, string[]>): FiltersResponse {
  return Object.fromEntries(categoryNames.map((name) => [name, {
    rules: entries(name, values[name]),
    defaults: [...defaults[name]],
    load_error: query.has('loadWarning') && name === 'words' ? 'The synthetic words file is unreadable.' : null,
  }])) as unknown as FiltersResponse
}

let persisted = responseFrom(initialValues())

function normalizeText(values: string[]) {
  const seen = new Set<string>()
  return values
    .map((value) => value.trim())
    .filter((value) => value && !value.startsWith('#'))
    .filter((value) => {
      if (seen.has(value)) return false
      seen.add(value)
      return true
    })
}

function normalizedResponse(payload: FilterInput): FiltersResponse {
  const values = {
    words: normalizeText(payload.words),
    phrases: normalizeText(payload.phrases),
    patterns: payload.patterns.map((value) => value.trim()).filter(Boolean),
  }
  return responseFrom(values)
}

function invalidPattern(payload: FilterInput) {
  const index = payload.patterns.map((value) => value.trim()).filter(Boolean).findIndex((value) => {
    try { new RegExp(value); return false } catch { return true }
  })
  return index < 0 ? undefined : { category: 'patterns' as const, index }
}

function action(action: 'apply' | 'save', payload: FilterInput) {
  calls.push([`${action}_filters`, structuredClone(payload)])
  if (query.has('saveError') && action === 'save') return { ok: false, error: 'Synthetic filter save failed.' }
  for (const category of ['words', 'phrases'] as const) {
    const index = payload[category].findIndex((value) => value.includes('\ufffd'))
    if (index >= 0) return { ok: false, error: 'Rule contains invalid text.', invalid_rule: { category, index } }
  }
  const invalid = invalidPattern(payload)
  if (invalid) return { ok: false, error: 'Invalid regular expression.', invalid_rule: invalid }
  if (action === 'save') persisted = normalizedResponse(payload)
  return { ok: true }
}

window.pywebview = { api: {
  get_app_status: async () => ({
    running: false, twitch_connected: false, twitch_connection_state: 'stopped',
    uptime_seconds: 0, channel: '', account: '',
  }),
  get_filters: async () => structuredClone(persisted),
  apply_filters: async (payload: FilterInput) => action('apply', payload),
  save_filters: async (payload: FilterInput) => action('save', payload),
} as unknown as Awaited<ReturnType<typeof waitForBridge>> }

createRoot(document.getElementById('root')!).render(<main><FiltersPage active /></main>)
