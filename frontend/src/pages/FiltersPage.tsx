import { useEffect, useMemo, useRef, useState } from 'react'

import {
  type FilterActionResult,
  type FilterCategory,
  type FilterCategoryName,
  type FilterEntry,
  type FilterInput,
  type FilterTestResult,
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

function configuredRules(rules: FilterDraft[]): FilterDraft[] {
  return rules.filter((rule) => rule.value.trim() && !rule.value.trim().startsWith('#'))
}

export default function FiltersPage({ active }: FiltersPageProps) {
  const [data, setData] = useState<FiltersResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [drafts, setDrafts] = useState<Drafts>(emptyDrafts)
  const [nextId, setNextId] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [testText, setTestText] = useState('')
  const [testSource, setTestSource] = useState<'active' | 'draft'>('active')
  const [testResult, setTestResult] = useState<Extract<FilterTestResult, { ok: true }> | null>(null)
  const [testError, setTestError] = useState('')
  const [testBusy, setTestBusy] = useState(false)
  const [expanded, setExpanded] = useState<Record<FilterCategoryName, boolean>>({ words: false, phrases: false, patterns: false })
  const hasLoaded = useRef(false)
  const testBusyRef = useRef(false)
  const testRequestVersion = useRef(0)

  const clearTestResult = () => {
    testRequestVersion.current += 1
    setTestResult(null)
    setTestError('')
  }

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
    setLoading(true)
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
      } finally {
        if (mounted) setLoading(false)
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
    clearTestResult()
  }

  const updateTextRules = (name: 'words' | 'phrases', value: string) => {
    setDrafts((current) => {
      const previousRules = new Map(current[name].map((rule) => [rule.value.trim(), rule]))
      return {
        ...current,
        [name]: value.split(/\r?\n/).map((line, index) => {
          const previous = previousRules.get(line.trim())
          return {
            id: index,
            value: line,
            origin: data?.[name].defaults.includes(line.trim()) ? 'default' : 'local',
            valid: previous?.valid ?? true,
            error: previous?.error ?? null,
          }
        }),
      }
    })
    setError('')
    setNotice('')
    clearTestResult()
  }

  const addRule = (name: FilterCategoryName) => {
    setDrafts((current) => ({
      ...current,
      [name]: [...current[name], { id: nextId, value: '', origin: 'local', valid: true, error: null }],
    }))
    setNextId((current) => current + 1)
    setError('')
    setNotice('')
    clearTestResult()
  }

  const removeRule = (name: FilterCategoryName, id: number) => {
    setDrafts((current) => ({ ...current, [name]: current[name].filter((rule) => rule.id !== id) }))
    setError('')
    setNotice('')
    clearTestResult()
  }

  const runAction = async (action: 'apply' | 'save') => {
    const payload = inputFromDrafts(drafts)
    clearTestResult()
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
          setExpanded((current) => ({ ...current, [category]: true }))
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

  const runFilterTest = async () => {
    if (testBusyRef.current || busy || !data) return
    testBusyRef.current = true
    const requestVersion = testRequestVersion.current + 1
    testRequestVersion.current = requestVersion
    setTestBusy(true)
    setTestResult(null)
    setTestError('')
    try {
      const api = await waitForBridge()
      const result = await api.test_filters(
        testText,
        testSource,
        testSource === 'draft' ? inputFromDrafts(drafts) : null,
      )
      if (requestVersion !== testRequestVersion.current) return
      if (!result.ok) {
        const invalid = result.invalid_rule
        setTestError(invalid
          ? `Draft rule invalid: ${categoryInfo[invalid.category].label}, rule ${invalid.index + 1}. ${result.error}`
          : result.error)
        return
      }
      setTestResult(result)
    } catch (reason) {
      if (requestVersion === testRequestVersion.current) {
        setTestError(reason instanceof Error ? reason.message : 'The filter test could not be completed.')
      }
    } finally {
      testBusyRef.current = false
      setTestBusy(false)
    }
  }

  return (
    <div className="filters-layout" aria-busy={loading}>
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
      <section className="card filter-tester-card" id="filter-tester">
        <div className="section-heading">
          <div>
            <p className="label">LOCAL VALIDATION</p>
            <h2>Filter Tester</h2>
            <p className="section-copy">Try sample text against the filters used in this session or the unsaved rules currently shown below.</p>
          </div>
        </div>
        <label className="form-field filter-test-text">
          Sample text
          <textarea
            rows={4}
            value={testText}
            onChange={(event) => {
              setTestText(event.target.value)
              clearTestResult()
            }}
            placeholder="Enter a message to test"
          />
        </label>
        <fieldset className="filter-test-source">
          <legend>Rules to test</legend>
          <label>
            <input
              type="radio"
              name="filter-test-source"
              value="active"
              checked={testSource === 'active'}
              onChange={() => {
                setTestSource('active')
                clearTestResult()
              }}
            />
            <span><strong>Active filters</strong><small>The effective rules in the running session.</small></span>
          </label>
          <label>
            <input
              type="radio"
              name="filter-test-source"
              value="draft"
              checked={testSource === 'draft'}
              onChange={() => {
                setTestSource('draft')
                clearTestResult()
              }}
            />
            <span><strong>Unsaved draft</strong><small>The current editors, without applying or saving them.</small></span>
          </label>
        </fieldset>
        <div className="filter-test-footer">
          <p className="settings-hint">Tests editable global filters only. Protected AI safety is separate. This runs locally without Twitch or an API request.</p>
          <button className="primary" type="button" disabled={testBusy || busy || !data} onClick={() => void runFilterTest()}>
            {testBusy ? 'Testing…' : 'Test sample'}
          </button>
        </div>
        {testError && <div className="filter-test-error" role="alert">{testError}</div>}
        {testResult && (
          <div className={`filter-test-result ${testResult.decision.toLowerCase()}${testResult.timed_out ? ' timed-out' : ''}`} role="status" aria-live="polite">
            <div className="filter-test-decision">
              <span>Decision</span>
              <strong>{testResult.decision}</strong>
            </div>
            {testResult.timed_out ? (
              <p><strong>Evaluation timed out.</strong> The message was blocked safely; no rule is claimed as a match.</p>
            ) : testResult.decision === 'BLOCK' ? (
              <dl>
                <div><dt>Category</dt><dd>{testResult.category ? categoryInfo[testResult.category].label : 'Not reported'}</dd></div>
                <div><dt>Editable rule</dt><dd>{testResult.rule ? <code>{testResult.rule}</code> : 'Not available'}</dd></div>
              </dl>
            ) : (
              <p>No editable global filter matched this sample.</p>
            )}
            <small>Tested {testResult.source === 'draft' ? 'unsaved draft rules' : 'active session filters'}.</small>
          </div>
        )}
      </section>
      {data && categoryNames.map((name) => {
        const category = data[name]
        const info = categoryInfo[name]
        const rules = drafts[name]
        const configured = configuredRules(rules)
        const count = name === 'patterns' ? configured.length : new Set(configured.map((rule) => rule.value.trim())).size
        const invalidCount = rules.filter((rule) => !rule.valid || rule.error).length
        const defaultLines = rules.flatMap((rule, index) => rule.value.trim() && !rule.value.trim().startsWith('#') && rule.origin === 'default' ? [index + 1] : [])
        const defaultCount = new Set(configured.filter((rule) => rule.origin === 'default').map((rule) => rule.value.trim())).size
        const detailsId = `filter-details-${name}`
        return (
          <section className="card filter-category-card" id={`filters-${name}`} data-category={name} key={name}>
            <h2 className="filter-category-heading">
              <button
                type="button"
                className="filter-category-summary"
                aria-expanded={expanded[name]}
                aria-controls={detailsId}
                onClick={() => setExpanded((current) => ({ ...current, [name]: !current[name] }))}
              >
                <span>{info.label}</span>
                <span className="filter-category-status">
                  <span className="read-only-badge">{count} {count === 1 ? 'rule' : 'rules'}</span>
                  {invalidCount > 0 && <span className="filter-invalid-label">{invalidCount} invalid</span>}
                  {category.load_error && <span className="filter-warning-label">File warning</span>}
                  <span className="filter-expand-label">{expanded[name] ? 'Hide rules' : 'Show rules'}</span>
                </span>
              </button>
            </h2>
            {expanded[name] && <div className="filter-category-details" id={detailsId}>
              <p className="section-copy">{info.description}</p>
              {category.load_error && (
                <div className="filter-load-warning" role="status">
                  Could not load the latest file: {category.load_error}. Existing rules remain available.
                </div>
              )}
              {name !== 'patterns' ? (
                <div className="filter-text-editor">
                  <label className="form-field">
                    {info.label}, one rule per line
                    <textarea
                      className={`filter-textarea ${invalidCount ? 'invalid' : ''}`}
                      rows={6}
                      aria-invalid={invalidCount > 0}
                      aria-describedby={`filter-help-${name}${invalidCount ? ` filter-errors-${name}` : ''}`}
                      value={rules.map((rule) => rule.value).join('\n')}
                      onChange={(event) => updateTextRules(name, event.target.value)}
                      placeholder={info.empty}
                    />
                  </label>
                  <p className="settings-hint" id={`filter-help-${name}`}>One non-empty line = one rule. Whitespace is trimmed; blank lines and lines starting with # are ignored. Commas remain part of the rule.</p>
                  <div className="filter-text-meta">
                    <span className="mini-badge filter-default-badge">{defaultCount} built-in {defaultCount === 1 ? 'default' : 'defaults'}</span>
                    <span className="mini-badge filter-local-badge">{count - defaultCount} local {count - defaultCount === 1 ? 'rule' : 'rules'}</span>
                    {defaultLines.length > 0 && <span>Built-in defaults on {defaultLines.length === 1 ? 'line' : 'lines'} {defaultLines.join(', ')}. Other rules are local.</span>}
                  </div>
                  {invalidCount > 0 && <ul className="filter-text-errors" id={`filter-errors-${name}`}>
                    {rules.map((rule, index) => (!rule.valid || rule.error) && <li key={rule.id}>Line {index + 1}: {rule.error ?? 'Invalid rule.'}</li>)}
                  </ul>}
                </div>
              ) : rules.length === 0 ? (
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
              {name === 'patterns' && <div className="filter-category-actions">
                <button className="secondary" type="button" disabled={busy} onClick={() => addRule(name)}>Add rule</button>
              </div>}
            </div>}
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
