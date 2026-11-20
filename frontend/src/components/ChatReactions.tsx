import type { ChatReaction } from '../bridge'
import { Select } from './Select'
import Switch from './Switch'
import CommandEditorDialog from './CommandEditorDialog'
import { commandEditorCopy as copy } from '../i18n/commands.en'

export type ReactionDraft = Omit<ChatReaction, 'probability' | 'cooldown_seconds' | 'responses' | 'creation_order'> & {
  probability: string
  cooldown_seconds: string
  responses: string
  position: number
}

const matchModes = [{ value: 'exact', label: 'Exact' }, { value: 'contains', label: 'Contains' }]
export const probabilityText = (probability: number) => String(Number((probability * 100).toPrecision(15)))

export function reactionDraftFrom(rule: ChatReaction, position: number): ReactionDraft {
  const { creation_order: _, ...values } = rule
  return { ...values, probability: probabilityText(rule.probability), cooldown_seconds: String(rule.cooldown_seconds),
    responses: rule.responses.join('\n'), position }
}

export function newReactionDraft(position: number): ReactionDraft {
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, '0')).join('')
  return { id, text: '', enabled: true, case_sensitive: false, match_mode: 'contains',
    probability: '100', cooldown_seconds: '0', responses: '', position }
}

export default function ChatReactions({ draft, count, position, dirty, busy, error, update, onSave, onClose }: {
  draft: ReactionDraft
  count: number
  position: number
  dirty: boolean
  busy: boolean
  error: string
  update: (change: Partial<ReactionDraft>) => void
  onSave: () => void
  onClose: () => void
}) {
  return <CommandEditorDialog id="chat-reaction-editor" title={position < 0 ? copy.newReaction : copy.editReaction}
    dirty={dirty} busy={busy} error={error} saveLabel={copy.saveReaction} onSave={onSave} onClose={onClose}
    sections={[
      { id: 'general', body: <div className="command-editor-stack">
        <div className="command-editor-identity">
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-text">Match text</label></div>
            <input data-editor-focus id="reaction-text" value={draft.text} onChange={(event) => update({ text: event.target.value })} required maxLength={100} />
          </div>
          <Switch className="reaction-enabled" checked={draft.enabled} ariaLabel="Enable chat reaction" onCheckedChange={(enabled) => update({ enabled })}>
            <span>{draft.enabled ? copy.enabled : copy.disabled}</span>
          </Switch>
        </div>
        <div className="form-field custom-response-field">
          <div className="custom-field-label"><label htmlFor="reaction-responses">Responses</label></div>
          <textarea id="reaction-responses" className="custom-response-textarea" rows={4} required value={draft.responses} onChange={(event) => update({ responses: event.target.value })} />
        </div>
      </div> },
      { id: 'matching', body: <div className="command-editor-stack">
        <div className="reaction-matching-fields">
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-mode">Match mode</label></div>
            <Select id="reaction-mode" value={draft.match_mode} options={matchModes} onChange={(mode) => update({ match_mode: mode as ReactionDraft['match_mode'] })} />
          </div>
          <div className="reaction-case">
            <span className="custom-field-label">Case sensitivity</span>
            <Switch checked={draft.case_sensitive} onCheckedChange={(case_sensitive) => update({ case_sensitive })}>Case sensitive</Switch>
          </div>
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-probability">Probability (%)</label></div>
            <input id="reaction-probability" type="number" required min="0" max="100" step="any" value={draft.probability} onChange={(event) => update({ probability: event.target.value })} />
          </div>
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="reaction-cooldown">Cooldown (seconds)</label></div>
            <input id="reaction-cooldown" type="number" required min="0" max="86400" step="any" value={draft.cooldown_seconds} onChange={(event) => update({ cooldown_seconds: event.target.value })} />
          </div>
        </div>
        {position >= 0 && <div className="row-actions reaction-order">
            <div className="custom-field-label">
              <span className="muted" aria-live="polite">Priority {draft.position + 1} of {count}</span>
            </div>
            <div className="row-actions">
              <button type="button" className="secondary" disabled={draft.position === 0} onClick={() => update({ position: draft.position - 1 })}>Move up</button>
              <button type="button" className="secondary" disabled={draft.position >= count - 1} onClick={() => update({ position: draft.position + 1 })}>Move down</button>
            </div>
          </div>}
      </div> },
    ]} />
}
