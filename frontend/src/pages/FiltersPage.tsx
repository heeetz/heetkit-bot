import { useEffect, useMemo, useRef, useState } from 'react'

import {
  type FilterActionResult,
  type FilterCategory,
  type FilterCategoryName,
  type FilterEntry,
  type FilterInput,
  type FiltersResponse,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'

interface FilterDraft extends FilterEntry {
  id: number
}

type Drafts = Record<FilterCategoryName, FilterDraft[]>

interface FiltersPageProps {
  active: boolean
}

const categoryInfo: Record<FilterCategoryName, { label: string; description: string; empty: string }> = {
  words: {
    label: 'Blocked words',
    description: 'Match individual words in incoming chat messages.',
    empty: 'No blocked words configured.',
  },
  phrases: {
    label: 'Blocked phrases',
    description: 'Match longer text snippets in incoming chat messages.',
    empty: 'No blocked phrases configured.',
  },
  patterns: {
    label: 'Regex patterns',
    description: 'Match messages with Python regular expressions. Validation is performed by the backend.',
    empty: 'No regex patterns configured.',
  },
}

const categoryNames: FilterCategoryName[] = ['words', 'phrases', 'patterns']

function emptyDrafts(): Drafts {
  return { words: [], phrases: [], patterns: [] }
}

function draftsFromResponse(response: FiltersResponse): Drafts {
  let nextId = 0
  return Object.fromEntries(categoryNames.map((name) => [
    name,
    response[name].rules.map((rule) => ({ ...rule, id: nextId++ })),
  ])) as Drafts
}

function inputFromDrafts(drafts: Drafts): FilterInput {
  return {
    words: drafts.words.map((rule) => rule.value.trim()).filter(Boolean),
    phrases: drafts.phrases.map((rule) => rule.value.trim()).filter(Boolean),
    patterns: drafts.patterns.map((rule) => rule.value.trim()).filter(Boolean),
  }
}

function categoryIsDirty(category: FilterCategory | undefined, rules: FilterDraft[]): boolean {
  if (!category) return rules.length > 0
  return JSON.stringify(rules.map((rule) => rule.value.trim()).filter(Boolean))
    !== JSON.stringify(category.rules.map((rule) => rule.value.trim()).filter(Boolean))
}

export default function FiltersPage({ active }: FiltersPageProps) {
  const [data, setData] = useState<FiltersResponse | null>(null)
  const [drafts, setDrafts] = useState<Drafts>(emptyDrafts)
  const [nextId, setNextId] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const hasLoaded = useRef(false)

  const loadFilters = async () => {
    const api = await waitForBridge()
    const response = await api.get_filters()
    setData(response)
    const nextDrafts = draftsFromResponse(response)
    setDrafts(nextDrafts)
    setNextId(Math.max(-1, ...categoryNames.flatMap((name) => nextDrafts[name].map((rule) => rule.id))) + 1)
    setError('')
  }

  useEffect(() => {
    if (!active || hasLoaded.current) return
    let mounted = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const response = await api.get_filters()
        if (mounted) {
          hasLoaded.current = true
          setData(response)
          const nextDrafts = draftsFromResponse(response)
          setDrafts(nextDrafts)
          setNextId(Math.max(-1, ...categoryNames.flatMap((name) => nextDrafts[name].map((rule) => rule.id))) + 1)
          setError('')
        }
      } catch (reason) {
        if (mounted) setError(reason instanceof Error ? reason.message : 'Could not load filters.')
      }
    }
    void load()
    return () => { mounted = false }
  }, [active])

  const dirty = useMemo(
    () => categoryNames.some((name) => categoryIsDirty(data?.[name], drafts[name])),
    [data, drafts],
  )

  const updateRule = (name: FilterCategoryName, id: number, value: string) => {
    setDrafts((current) => ({
      ...current,
      [name]: current[name].map((rule) => rule.id === id
        ? { ...rule, value, origin: data?.[name].defaults.includes(value.trim()) ? 'default' : 'local', valid: true, error: null }
        : rule),
    }))
    setError('')
    setNotice('')
  }

  const addRule = (name: FilterCategoryName) => {
    setDrafts((current) => ({
      ...current,
      [name]: [...current[name], { id: nextId, value: '', origin: 'local', valid: true, error: null }],
    }))
    setNextId((current) => current + 1)
    setError('')
    setNotice('')
  }

  const removeRule = (name: FilterCategoryName, id: number) => {
    setDrafts((current) => ({ ...current, [name]: current[name].filter((rule) => rule.id !== id) }))
    setError('')
    setNotice('')
  }

  const runAction = async (action: 'apply' | 'save') => {
    const payload = inputFromDrafts(drafts)
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result: FilterActionResult = action === 'apply'
        ? await api.apply_filters(payload)
        : await api.save_filters(payload)
      if (!result.ok) {
        if (result.invalid_rule) {
          const { category, index } = result.invalid_rule
          const nonblankRules = drafts[category].filter((rule) => rule.value.trim())
          const invalidId = nonblankRules[index]?.id
          if (invalidId !== undefined) {
            setDrafts((current) => ({
              ...current,
              [category]: current[category].map((rule) => rule.id === invalidId
                ? { ...rule, valid: false, error: result.error ?? 'Invalid rule.' }
                : rule),
            }))
          }
        }
        throw new Error(result.error ?? 'Filters could not be updated.')
      }
      if (action === 'save') {
        await loadFilters()
      } else {
        setDrafts((current) => Object.fromEntries(categoryNames.map((name) => [
          name,
          current[name].map((rule) => ({ ...rule, valid: true, error: null })),
        ])) as Drafts)
      }
      setNotice(action === 'apply'
        ? 'Applied filters for this session.'
        : 'Saved filters across restarts.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Filters could not be updated.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="filters-layout">
      <FeedbackToast error={error} notice={notice} onDismiss={() => { setError(''); setNotice('') }} />
      <section className="card filters-intro">
        <div className="section-heading">
          <div>
            <p className="label">MESSAGE FILTERS</p>
            <h2>Moderation rules</h2>
            <p className="section-copy">Manage blocked words, phrases, and regex patterns. Apply changes to this session or save them for future launches.</p>
          </div>
          <span className="read-only-badge">{data ? 'Loaded' : 'Loading…'}</span>
        </div>
        <div className="filters-effect-note">
          <strong>Apply</strong> changes the running session only. <strong>Save</strong> persists them across restarts. Regex rules are validated by Python when you apply or save.
        </div>
      </section>
      {data && categoryNames.map((name) => {
        const category = data[name]
        const info = categoryInfo[name]
        const rules = drafts[name]
        return (
          <section className="card filter-category-card" key={name}>
            <div className="section-heading">
              <div>
                <p className="label">{name === 'patterns' ? 'REGULAR EXPRESSIONS' : 'TEXT MATCHING'}</p>
                <h2>{info.label}</h2>
                <p className="section-copy">{info.description}</p>
              </div>
              <span className="read-only-badge">{rules.length} {rules.length === 1 ? 'rule' : 'rules'}</span>
            </div>
            {category.load_error && (
              <div className="filter-load-warning" role="status">
                Could not load the latest file: {category.load_error}. Existing rules remain available.
              </div>
            )}
            {rules.length === 0 ? (
              <div className="empty-state-inline"><strong>{info.empty}</strong><p>Add a rule below to update this category.</p></div>
            ) : (
              <div className="filter-rule-list">
                {rules.map((rule, index) => (
                  <div className={`filter-rule-row ${!rule.valid ? 'invalid' : ''}`} key={rule.id}>
                    <label className="form-field">
                      {info.label} {index + 1}
                      <input
                        aria-invalid={!rule.valid || Boolean(rule.error)}
                        className={!rule.valid || rule.error ? 'invalid' : ''}
                        value={rule.value}
                        onChange={(event) => updateRule(name, rule.id, event.target.value)}
                        placeholder={name === 'patterns' ? String.raw`\bexample\b` : 'Enter a rule'}
                      />
                    </label>
                    <div className="filter-rule-meta">
                      <span className={`mini-badge ${rule.origin === 'default' ? 'filter-default-badge' : 'filter-local-badge'}`}>
                        {rule.origin === 'default' ? 'Built-in default' : 'Local rule'}
                      </span>
                      {!rule.valid && <span className="filter-invalid-label">Invalid</span>}
                      {rule.error && <span className="filter-rule-error">{rule.error}</span>}
                    </div>
                    <button className="ghost" type="button" disabled={busy} onClick={() => removeRule(name, rule.id)}>Remove</button>
                  </div>
                ))}
              </div>
            )}
            {category.defaults.length > 0 && (
              <p className="filter-default-summary">{category.defaults.length} built-in {category.defaults.length === 1 ? 'default is' : 'defaults are'} available in this category.</p>
            )}
            <div className="filter-category-actions">
              <button className="secondary" type="button" disabled={busy} onClick={() => addRule(name)}>Add rule</button>
            </div>
          </section>
        )
      })}
      <section className="card filters-actions-card">
        {!data && <p className="muted">Loading filters…</p>}
        <div className="settings-actions">
          <button className="secondary" type="button" disabled={busy || !data || !dirty} onClick={() => void runAction('apply')}>Apply for session</button>
          <button className="primary" type="button" disabled={busy || !data || !dirty} onClick={() => void runAction('save')}>{busy ? 'Saving…' : 'Save filters'}</button>
        </div>
      </section>
    </div>
  )
}
