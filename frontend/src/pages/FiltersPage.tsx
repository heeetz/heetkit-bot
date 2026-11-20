import { useEffect, useRef, useState } from 'react'

import {
  type FilterCategoryName,
  type FilterCategory,
  type FilterEntry,
  type FilterInput,
  type FilterTestResult,
  type FiltersResponse,
  waitForBridge,
} from '../bridge'
import Confirmation from '../components/Confirmation'
import HelpTip from '../components/HelpTip'
import EditorDialog, { EditorSections } from '../components/EditorDialog'
import FeedbackToast from '../components/FeedbackToast'
import { useRestartDraft } from '../desktopRestart'

interface FiltersPageProps {
  active: boolean
}

type FilterTexts = Record<FilterCategoryName, string>
type RuleError = { category: FilterCategoryName; value: string; message: string }

const categoryNames = ['words', 'phrases', 'patterns'] as const
const categoryInfo = {
  words: { label: 'Blocked words', description: 'Matches whole words.' },
  phrases: { label: 'Blocked phrases', description: 'Matches the text you enter, including punctuation.' },
  patterns: { label: 'Regex patterns', description: 'Uses Python regular expressions.' },
}

function draftTexts(data: FiltersResponse): FilterTexts {
  return {
    words: data.words.rules.map(({ value }) => value).join('\n'),
    phrases: data.phrases.rules.map(({ value }) => value).join('\n'),
    patterns: data.patterns.rules.map(({ value }) => value).join('\n'),
  }
}

function ruleValues(text: string): string[] {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
}

function filterInput(drafts: FilterTexts): FilterInput {
  return {
    words: ruleValues(drafts.words),
    phrases: ruleValues(drafts.phrases),
    patterns: ruleValues(drafts.patterns),
  }
}

function acceptedFilters(previous: FiltersResponse, payload: FilterInput): FiltersResponse {
  const category = (name: FilterCategoryName): FilterCategory => {
    const { defaults } = previous[name]
    const values = payload[name].filter((value) => !value.startsWith('#'))
    const rules = (name === 'patterns' ? values : [...new Set(values)]).map<FilterEntry>((value) => ({
      value, origin: defaults.includes(value) ? 'default' : 'local', valid: true,
    }))
    return { defaults, rules }
  }
  return { words: category('words'), phrases: category('phrases'), patterns: category('patterns') }
}

export default function FiltersPage({ active }: FiltersPageProps) {
  const [data, setData] = useState<FiltersResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [drafts, setDrafts] = useState<FilterTexts>({ words: '', phrases: '', patterns: '' })
  const [section, setSection] = useState<FilterCategoryName | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [invalidRule, setInvalidRule] = useState<RuleError | null>(null)
  const [editorError, setEditorError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [testText, setTestText] = useState('')
  const [testResult, setTestResult] = useState<Extract<FilterTestResult, { ok: true }> | null>(null)
  const [testError, setTestError] = useState('')
  const [testBusy, setTestBusy] = useState(false)
  const testBusyRef = useRef(false)
  const testRequestVersion = useRef(0)

  useEffect(() => {
    if (!active || data) return
    let current = true
    setLoading(true)
    void (async () => {
      try {
        const response = await (await waitForBridge()).get_filters()
        if (current) {
          setData(response)
          setDrafts(draftTexts(response))
          setError('')
        }
      } catch (reason) {
        if (current) setError(reason instanceof Error ? reason.message : 'Could not load filters.')
      } finally {
        if (current) setLoading(false)
      }
    })()
    return () => { current = false }
  }, [active, data])

  const dirty = Boolean(data && categoryNames.some((name) => (
    JSON.stringify(ruleValues(drafts[name])) !== JSON.stringify(data[name].rules.map(({ value }) => value))
  )))
  useRestartDraft('Filters', dirty)

  const clearTestResult = () => {
    testRequestVersion.current += 1
    setTestResult(null)
    setTestError('')
  }

  const closeEditor = () => {
    if (busy) return
    if (dirty) {
      setConfirmDiscard(true)
      return
    }
    discardEdits()
  }

  const discardEdits = () => {
    if (data) setDrafts(draftTexts(data))
    setConfirmDiscard(false)
    setSection(null)
  }

  const saveFilters = async () => {
    if (busy || !data || !dirty) return
    const payload = filterInput(drafts)
    setBusy(true)
    setEditorError('')
    setInvalidRule(null)
    try {
      const api = await waitForBridge()
      const result = await api.save_filters(payload)
      if (!result.ok) {
        const message = result.error ?? 'Filters could not be saved.'
        if (result.invalid_rule) {
          const { category, index } = result.invalid_rule
          const value = payload[category][index]
          setSection(category)
          if (value !== undefined) setInvalidRule({ category, value, message })
        }
        setEditorError(message)
        return
      }
      clearTestResult()
      // A successful save is final even if the follow-up read fails.
      const response = await api.get_filters().catch(() => acceptedFilters(data, payload))
      setData(response)
      setDrafts(draftTexts(response))
      setSection(null)
      setNotice('Filters saved.')
    } catch (reason) {
      setEditorError(reason instanceof Error ? reason.message : 'Filters could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  const runFilterTest = async () => {
    if (testBusyRef.current || busy || !data) return
    testBusyRef.current = true
    const requestVersion = ++testRequestVersion.current
    setTestBusy(true)
    setTestResult(null)
    setTestError('')
    try {
      const result = await (await waitForBridge()).test_filters(testText, 'active', null)
      if (requestVersion !== testRequestVersion.current) return
      if (result.ok) setTestResult(result)
      else setTestError(result.error)
    } catch (reason) {
      if (requestVersion === testRequestVersion.current) {
        setTestError(reason instanceof Error ? reason.message : 'The filter test could not be completed.')
      }
    } finally {
      testBusyRef.current = false
      setTestBusy(false)
    }
  }

  const renderSection = (name: FilterCategoryName) => {
    if (!data) return null
    const category = data[name]
    const info = categoryInfo[name]
    const values = ruleValues(drafts[name]).filter((value) => !value.startsWith('#'))
    const configured = name === 'patterns' ? values : [...new Set(values)]
    const defaults = configured.filter((value) => category.defaults.includes(value)).length
    const invalid = new Map(category.rules.filter((rule) => !rule.valid || rule.error)
      .map(({ value, error }) => [value, error ?? 'Invalid rule.']))
    if (invalidRule?.category === name) invalid.set(invalidRule.value, invalidRule.message)
    const errors = drafts[name].split(/\r?\n/).flatMap((line, index) => {
      const message = invalid.get(line.trim())
      return message ? [{ line: index + 1, message }] : []
    })
    const inputId = `filters-${name}-input`

    return (
      <div className="filter-text-editor" id={`filters-${name}`}>
        <div className="filter-editor-heading">
          <div className="filter-editor-topic">
            <h3>{info.label}</h3>
            {name === 'patterns' && <HelpTip label="Regex example"><code>^hello\b</code> matches messages that start with the word “hello”.</HelpTip>}
          </div>
          <span className="read-only-badge">{configured.length} {configured.length === 1 ? 'rule' : 'rules'}</span>
        </div>
        {category.load_error && <p className="filter-load-warning" role="status">{category.load_error}</p>}
        <label className="form-field" htmlFor={inputId}>{info.label}, one rule per line</label>
        <textarea id={inputId} className={`filter-textarea${errors.length ? ' invalid' : ''}`} rows={9}
          data-editor-focus={name === 'words' ? true : undefined}
          aria-invalid={errors.length > 0} aria-describedby={`${inputId}-help${errors.length ? ` ${inputId}-errors` : ''}`}
          value={drafts[name]} disabled={busy}
          onChange={(event) => {
            setDrafts((current) => ({ ...current, [name]: event.target.value }))
            setEditorError('')
          }} />
        <p className="settings-hint" id={`${inputId}-help`}>{info.description} HeetKit skips blank lines and lines beginning with #.</p>
        {configured.length > 0 && <div className="filter-text-meta">
          <span className="mini-badge filter-default-badge">{defaults} built-in {defaults === 1 ? 'default' : 'defaults'}</span>
          <span className="mini-badge filter-local-badge">{configured.length - defaults} local {configured.length - defaults === 1 ? 'rule' : 'rules'}</span>
        </div>}
        {errors.length > 0 && <ul className="filter-text-errors" id={`${inputId}-errors`}>
          {errors.map(({ line, message }) => <li key={line}>Line {line}: {message}</li>)}
        </ul>}
      </div>
    )
  }

  return (
    <div className="filters-layout" aria-busy={loading}>
      <FeedbackToast error={error} notice={notice} onDismiss={() => { setError(''); setNotice('') }} />
      <section className="card filters-intro">
        <div>
          <h2>Bot filters</h2>
          <p className="section-copy">HeetKit skips Twitch messages that match these rules and blocks matching AI replies.</p>
        </div>
        <div className="filters-intro-actions">
          <button className="primary" type="button" aria-haspopup="dialog" disabled={!data || busy} onClick={() => {
            setEditorError('')
            setInvalidRule(null)
            setNotice('')
            setSection('words')
          }}>Edit filters</button>
        </div>
      </section>
      <section className="card filter-tester-card" id="filter-tester">
        <div className="section-heading">
          <div>
            <h2>Filter Tester</h2>
            <p className="section-copy">Check whether a sample matches your saved bot filters. The test runs locally.</p>
          </div>
        </div>
        <label className="form-field filter-test-text">
          Sample text
          <textarea rows={4} value={testText} placeholder="Enter a message to test"
            onChange={(event) => { setTestText(event.target.value); clearTestResult() }} />
        </label>
        <div className="filter-test-footer">
          <p className="settings-hint">The test checks your editable filters. AI safety checks run when you use AI.</p>
          <button className="primary" type="button" disabled={testBusy || busy || !data} onClick={() => void runFilterTest()}>
            {testBusy ? 'Testing…' : 'Test sample'}
          </button>
        </div>
        {testError && <div className="filter-test-error" role="alert">{testError}</div>}
        {testResult && (
          <div className={`filter-test-result ${testResult.decision.toLowerCase()}${testResult.timed_out ? ' timed-out' : ''}`} role="status" aria-live="polite">
            <div className="filter-test-decision">
              <span>{testResult.timed_out ? 'Regex timeout' : testResult.decision === 'ALLOW' ? 'User filters passed' : 'User filter matched'}</span>
              <strong>{testResult.decision}</strong>
            </div>
            {testResult.timed_out ? (
              <p>Regex evaluation timed out. The sample was blocked as a precaution.</p>
            ) : testResult.decision === 'BLOCK' ? (
              <dl>
                <div><dt>Category</dt><dd>{testResult.category ? categoryInfo[testResult.category].label : 'Not reported'}</dd></div>
                <div><dt>Editable rule</dt><dd>{testResult.rule ? <code>{testResult.rule}</code> : 'Not available'}</dd></div>
              </dl>
            ) : (
              <p>Protected AI safety may still block an AI request or reply.</p>
            )}
          </div>
        )}
      </section>
      {active && section && <EditorDialog id="filters-editor" title="Edit filters" closeLabel="Close editor"
        dirtyLabel={dirty ? 'Unsaved changes' : undefined} busy={busy} error={editorError} onClose={closeEditor}
        className="filters-editor-dialog">
        <EditorSections id="filters-editor" label="Filter sections" active={section} onSelect={setSection}
          sections={categoryNames.map((name) => ({ id: name, label: categoryInfo[name].label, body: renderSection(name) }))} />
        <div className="command-dialog-footer">
          <button className="secondary" type="button" disabled={busy} onClick={closeEditor}>Cancel</button>
          <button className="primary" type="button" disabled={busy || !dirty} onClick={() => void saveFilters()}>
            {busy ? 'Saving…' : 'Save filters'}
          </button>
        </div>
      </EditorDialog>}
      {active && confirmDiscard && <Confirmation title="Discard unsaved changes?"
        description="The current bot filters will stay in effect." danger onConfirm={discardEdits} onCancel={() => setConfirmDiscard(false)} />}
    </div>
  )
}
