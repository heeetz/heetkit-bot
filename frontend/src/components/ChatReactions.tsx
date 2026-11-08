import { useEffect, useRef, useState, type FormEvent } from 'react'
import { waitForBridge, type ChatReaction, type ChatReactionsResponse } from '../bridge'
import Confirmation from './Confirmation'
import HelpTip from './HelpTip'
import { Select } from './Select'
import Switch from './Switch'

type Draft = Omit<ChatReaction, 'probability' | 'cooldown_seconds' | 'responses'> & {
  probability: string
  cooldown_seconds: string
  responses: string
  position: number
}

const matchModes = [{ value: 'exact', label: 'Exact' }, { value: 'contains', label: 'Contains' }]
const matchLabel = (mode: ChatReaction['match_mode']) => mode === 'exact' ? 'Exact' : 'Contains'
const probabilityText = (probability: number) => String(Number((probability * 100).toPrecision(15)))
const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, '0')).join('')

export default function ChatReactions({ active }: { active: boolean }) {
  const [data, setData] = useState<ChatReactionsResponse | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const request = useRef(0)
  const editor = useRef<HTMLFormElement>(null)
  const matchText = useRef<HTMLInputElement>(null)

  const load = async () => {
    const current = ++request.current
    setError('')
    setBusy(true)
    try {
      const response = await (await waitForBridge()).get_message_triggers()
      if (!response.ok) throw new Error(response.error ?? 'Could not load chat reactions.')
      if (current === request.current) setData(response)
    } catch (reason) {
      if (current === request.current) setError(reason instanceof Error ? reason.message : 'Could not load chat reactions.')
    } finally {
      if (current === request.current) setBusy(false)
    }
  }

  const hasData = data !== null
  useEffect(() => {
    if (active && !hasData) void load()
    return () => { ++request.current }
  }, [active, hasData])

  useEffect(() => {
    if (!active || !draft?.id) return
    editor.current?.scrollIntoView({ block: 'start' })
    matchText.current?.focus({ preventScroll: true })
  }, [active, draft?.id])

  const update = (change: Partial<Draft>) => setDraft((current) => current && { ...current, ...change })
  const position = draft && data ? data.triggers.findIndex((rule) => rule.id === draft.id) : -1
  const persist = async (rules: ChatReaction[]) => {
    if (!data || busy) return
    setError('')
    setBusy(true)
    try {
      const result = await (await waitForBridge()).save_message_triggers(rules, data.revision)
      if (!result.ok) throw new Error(result.error ?? 'Could not save chat reactions.')
      setData(result)
      setDraft(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save chat reactions.')
    } finally {
      setBusy(false)
    }
  }

  const save = (event: FormEvent) => {
    event.preventDefault()
    if (!data || !draft) return
    const { position: nextPosition, ...values } = draft
    const original = data.triggers[position]
    const rules = data.triggers.filter((rule) => rule.id !== draft.id)
    rules.splice(nextPosition, 0, {
      ...values,
      probability: original && draft.probability === probabilityText(original.probability)
        ? original.probability : Number(draft.probability) / 100,
      cooldown_seconds: Number(draft.cooldown_seconds),
      responses: draft.responses.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
    })
    void persist(rules)
  }

  return <section className="card command-editor-card" id="chat-reactions" aria-busy={busy}>
    <div className="section-heading">
      <div><h2>Chat reactions</h2><p className="section-copy">Respond to matching chat messages. Rules are checked from top to bottom.</p></div>
      {!draft && <button className="primary" disabled={!data || busy || data.triggers.length >= 100} onClick={() => {
        setError('')
        setDraft({ id: newId(), text: '', enabled: true, case_sensitive: false, match_mode: 'contains',
          probability: '100', cooldown_seconds: '0', responses: '', position: data!.triggers.length })
      }}>New reaction</button>}
    </div>
    {error && <p className="custom-editor-error" role="alert">{error}</p>}
    {error && !draft && <button className="secondary" disabled={busy} onClick={() => void load()}>Reload reactions</button>}
    {confirmRemove && <Confirmation title="Remove chat reaction?" description={`Remove the reaction for “${data?.triggers[position]?.text}”?`} danger
      onCancel={() => setConfirmRemove(false)} onConfirm={() => {
        setConfirmRemove(false)
        if (data && draft) void persist(data.triggers.filter((rule) => rule.id !== draft.id))
      }} />}
    {draft && data && <form ref={editor} className="custom-command-editor" id="chat-reaction-editor" onSubmit={save}>
      <div className="section-heading"><h3>{position < 0 ? 'Add reaction' : 'Edit reaction'}</h3></div>
      <fieldset className="reaction-fields" disabled={busy}>
        <Switch className="custom-command-enabled" checked={draft.enabled} ariaLabel="Enable chat reaction" onCheckedChange={(enabled) => update({ enabled })}>
          <span>{draft.enabled ? 'Enabled' : 'Disabled'}</span>
        </Switch>
        <div className="custom-command-fields">
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-text">Match text</label><HelpTip label="Match text">Enter up to 100 characters from an ordinary chat message.</HelpTip></div>
            <input ref={matchText} id="reaction-text" value={draft.text} onChange={(event) => update({ text: event.target.value })} required maxLength={100} />
          </div>
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-mode">Match mode</label><HelpTip label="Match mode">Exact matches the whole message. Contains matches anywhere in the message.</HelpTip></div>
            <Select id="reaction-mode" value={draft.match_mode} options={matchModes} onChange={(mode) => update({ match_mode: mode as Draft['match_mode'] })} />
          </div>
        </div>
        <div className="custom-command-fields custom-command-settings">
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-probability">Probability (%)</label><HelpTip label="Probability">Chance to respond to a match. At 0% it never responds. At 100% every match is eligible.</HelpTip></div>
            <input id="reaction-probability" type="number" required min="0" max="100" step="any" value={draft.probability} onChange={(event) => update({ probability: event.target.value })} />
          </div>
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-cooldown">Cooldown (seconds)</label><HelpTip label="Reaction cooldown">Minimum time between uses of this rule across viewers. Zero disables the cooldown.</HelpTip></div>
            <input id="reaction-cooldown" type="number" required min="0" max="86400" step="any" value={draft.cooldown_seconds} onChange={(event) => update({ cooldown_seconds: event.target.value })} />
          </div>
          <div className="reaction-case">
            <Switch checked={draft.case_sensitive} onCheckedChange={(case_sensitive) => update({ case_sensitive })}>Case sensitive</Switch>
            <HelpTip label="Case sensitive">When enabled, uppercase and lowercase letters must match the text you enter.</HelpTip>
          </div>
        </div>
        <div className="form-field custom-response-field">
          <div className="custom-field-label"><label htmlFor="reaction-responses">Responses</label><HelpTip label="Reaction responses">Enter 1–10 response lines. One is picked at random. Each line can use up to 450 UTF-8 bytes.</HelpTip></div>
          <textarea id="reaction-responses" className="custom-response-textarea" rows={4} required value={draft.responses} onChange={(event) => update({ responses: event.target.value })} />
        </div>
        <div className="command-editor-actions">
          {position >= 0 && <div className="row-actions">
            <span className="muted" aria-live="polite">Position {draft.position + 1} of {data.triggers.length}</span>
            <button type="button" className="secondary" disabled={draft.position === 0} onClick={() => update({ position: draft.position - 1 })}>Move up</button>
            <button type="button" className="secondary" disabled={draft.position >= data.triggers.length - 1} onClick={() => update({ position: draft.position + 1 })}>Move down</button>
          </div>}
          <div className="command-action-footer">
            {position >= 0 && <button type="button" className="ghost destructive" onClick={() => setConfirmRemove(true)}>Remove reaction</button>}
            <div className="command-action-group">
              <button className="primary" type="submit">Save reaction</button>
              <button className="secondary" type="button" onClick={() => { setDraft(null); void load() }}>Discard and close</button>
            </div>
          </div>
        </div>
      </fieldset>
    </form>}
    {data && !data.triggers.length && !draft && <p className="muted">No chat reactions yet.</p>}
    <div className="custom-command-list">
      {data?.triggers.map((rule, index) => <article className="custom-command-row" key={rule.id}>
        <div className="custom-command-summary">
          <div className="custom-command-heading"><strong>{rule.text}</strong><span className={`state-pill ${rule.enabled ? 'enabled' : ''}`}>{rule.enabled ? 'Enabled' : 'Disabled'}</span></div>
          <p className="command-meta">{matchLabel(rule.match_mode)}</p>
        </div>
        <button className="secondary" disabled={busy || Boolean(draft)} onClick={() => {
          setError('')
          setDraft({ ...rule, position: index, probability: probabilityText(rule.probability),
            cooldown_seconds: String(rule.cooldown_seconds), responses: rule.responses.join('\n') })
        }}>Edit</button>
      </article>)}
    </div>
  </section>
}
