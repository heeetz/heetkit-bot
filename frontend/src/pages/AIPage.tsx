import { useEffect, useState } from 'react'

import {
  type AIStatus,
  type PersonalityInfo,
  type PersonalitiesResponse,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'

interface AIPageProps {
  active: boolean
}

export default function AIPage({ active }: AIPageProps) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [data, setData] = useState<PersonalitiesResponse | null>(null)
  const [selected, setSelected] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const mergeData = (response: PersonalitiesResponse, completedPersonality = '') => {
    setDrafts((currentDrafts) => Object.fromEntries(response.personalities.map((personality) => {
      const previous = data?.personalities.find((item) => item.name === personality.name)
      const currentDraft = currentDrafts[personality.name]
      const keepDraft = personality.name !== completedPersonality
        && previous
        && currentDraft !== undefined
        && currentDraft !== previous.prompt
      return [personality.name, keepDraft ? currentDraft : personality.prompt]
    })))
    setData(response)
    setSelected((current) => current || response.active_personality)
  }

  const refresh = async (completedPersonality = '') => {
    const api = await waitForBridge()
    const [nextStatus, response] = await Promise.all([
      api.get_ai_status(),
      api.get_personalities(),
    ])
    setStatus(nextStatus)
    mergeData(response, completedPersonality)
  }

  useEffect(() => {
    if (!active) {
      return
    }
    let current = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const [nextStatus, response] = await Promise.all([
          api.get_ai_status(),
          api.get_personalities(),
        ])
        if (current) {
          setStatus(nextStatus)
          mergeData(response)
          setError('')
        }
      } catch (reason) {
        if (current) {
          setError(reason instanceof Error ? reason.message : 'Could not load AI settings.')
        }
      }
    }
    void load()
    return () => { current = false }
  }, [active])

  const changeToggle = async (kind: 'enabled' | 'memory', enabled: boolean) => {
    setBusy(kind)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = kind === 'enabled'
        ? await api.set_ai_enabled(enabled)
        : await api.set_ai_memory_enabled(enabled)
      if (!result.ok) {
        throw new Error(result.error ?? 'AI setting could not be changed.')
      }
      setStatus(await api.get_ai_status())
      setNotice(kind === 'enabled' ? 'AI command state updated.' : 'AI memory state updated.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI setting could not be changed.')
    } finally {
      setBusy('')
    }
  }

  const runPersonalityAction = async (action: 'apply' | 'save' | 'reset') => {
    const personality = data?.personalities.find((item) => item.name === selected)
    const prompt = drafts[selected]
    if (!personality || prompt === undefined) {
      return
    }
    if (action === 'reset' && !window.confirm(`Reset ${selected} to its built-in prompt?`)) {
      return
    }
    setBusy(action)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = action === 'apply'
        ? await api.apply_personality(selected, prompt)
        : action === 'save'
          ? await api.save_personality(selected, prompt)
          : await api.reset_personality(selected)
      if (!result.ok) {
        throw new Error(result.error ?? 'Personality could not be updated.')
      }
      await refresh(selected)
      setNotice(action === 'apply'
        ? `Applied ${selected} for this session.`
        : action === 'save'
          ? `Saved ${selected} and made it the active personality.`
          : `Restored the built-in ${selected} prompt.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Personality could not be updated.')
    } finally {
      setBusy('')
    }
  }

  const personality: PersonalityInfo | undefined = data?.personalities.find(
    (item) => item.name === selected,
  )
  const prompt = selected ? (drafts[selected] ?? personality?.prompt ?? '') : ''
  const dirty = personality ? prompt !== personality.prompt : false
  const isActive = data?.active_personality === selected
  const canReset = Boolean(
    personality
      && (dirty || personality.has_saved_override || personality.prompt !== personality.built_in_prompt),
  )

  return (
    <section className="ai-layout">
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <div className="ai-status-grid">
        <article className="card compact-card">
          <p className="label">AI command</p>
          <Switch
            className="settings-toggle"
            checked={status?.enabled ?? false}
            disabled={!status || Boolean(busy)}
            ariaLabel="Enable AI command"
            onCheckedChange={(enabled) => void changeToggle('enabled', enabled)}
          >
            <span>{status?.enabled ? 'Enabled' : 'Disabled'}</span>
          </Switch>
          <p className="setting-effect">Applies immediately for this session. Save the Ask command on the Commands page to persist it.</p>
        </article>
        <article className="card compact-card">
          <p className="label">Conversation memory</p>
          <Switch
            className="settings-toggle"
            checked={status?.memory_enabled ?? false}
            disabled={!status || Boolean(busy)}
            ariaLabel="Enable conversation memory"
            onCheckedChange={(enabled) => void changeToggle('memory', enabled)}
          >
            <span>{status?.memory_enabled ? 'Enabled' : 'Disabled'}</span>
          </Switch>
          <p className="setting-effect">Applies immediately and is saved across restarts.</p>
        </article>
        <article className="card compact-card">
          <p className="label">Gemini model</p>
          <strong>{status?.model ?? '—'}</strong>
        </article>
        <article className="card compact-card">
          <p className="label">Active personality</p>
          <strong>{data?.active_personality ?? '—'}</strong>
        </article>
      </div>
      <article className="card personality-editor">
        <div className="section-heading">
          <div>
            <p className="label">PERSONALITY EDITOR</p>
            <h2>Personality-specific prompt</h2>
            <p className="section-copy">Core shared instructions stay protected in Python.</p>
          </div>
          <div className="personality-badges">
            {isActive && <span className="mini-badge saved-badge">Active</span>}
            {personality?.has_saved_override && <span className="mini-badge saved-badge">Saved override</span>}
            {data && !data.active_personality_saved && isActive && <span className="mini-badge runtime-badge">Runtime only</span>}
            {dirty && <span className="mini-badge dirty-badge">Edited</span>}
          </div>
        </div>
        <label className="form-field personality-select">
          Personality
          <select value={selected} onChange={(event) => { setSelected(event.target.value); setError(''); setNotice('') }}>
            {data?.personalities.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">
          Editable prompt
          <textarea
            value={prompt}
            maxLength={50000}
            disabled={!personality}
            onChange={(event) => {
              setDrafts((current) => ({ ...current, [selected]: event.target.value }))
              setError('')
              setNotice('')
            }}
          />
        </label>
        <div className="editor-footer">
          <span className="muted">{prompt.length.toLocaleString()} / 50,000 characters</span>
          <div className="row-actions">
            <button className="secondary" disabled={!personality || Boolean(busy) || (!dirty && isActive)} onClick={() => void runPersonalityAction('apply')}>Apply</button>
            <button className="primary" disabled={!personality || Boolean(busy) || (!dirty && personality.prompt_saved && isActive && data?.active_personality_saved)} onClick={() => void runPersonalityAction('save')}>Save</button>
            <button className="ghost" disabled={!personality || Boolean(busy) || !canReset} onClick={() => void runPersonalityAction('reset')}>Reset</button>
          </div>
        </div>
      </article>
    </section>
  )
}
