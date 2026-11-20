import { useId } from 'react'
import type { CredentialInfo } from '../bridge'
import HelpTip from './HelpTip'

interface TwitchSecretFieldProps {
  credential?: CredentialInfo
  value: string
  busy: string
  host: 'desktop' | 'server'
  onChange: (value: string) => void
  onAction: (action: 'replace' | 'remove' | 'test', restart?: boolean) => void
}

/** A draft field only: saved secrets are never returned to the UI. */
export default function TwitchSecretField({ credential, value, busy, host, onChange, onAction }: TwitchSecretFieldProps) {
  const id = useId()
  const configured = Boolean(credential?.configured)
  const external = credential?.managed === false
  const disabled = Boolean(busy) || !credential
  const removable = configured && !external && (host === 'server' || credential?.source === 'credential_store')
  return <div className="twitch-secret-field form-field">
    <div className="twitch-secret-label">
      <label htmlFor={id}>Twitch client secret</label>
      <HelpTip label="Twitch client secret">
        <ul>
          <li>The saved secret is never shown; the field always starts empty.</li>
          <li>Add/Replace and Remove apply immediately.</li>
          <li>Test saved secret checks it with the saved Client ID.</li>
          {host === 'desktop'
            ? <li>After a change, restart the app. Existing authorization is kept. A saved secret takes priority over the environment variable.</li>
            : <li>A change stops the bot and clears authorization. Connect Twitch again afterwards.</li>}
          {external && <li>This secret is set on the host (environment or secret file). Change it there.</li>}
        </ul>
      </HelpTip>
    </div>
    <input id={id} aria-label="Twitch client secret" aria-describedby={host === 'server' ? `${id}-effect` : undefined} type="password" autoComplete="new-password" maxLength={8192}
      value={value} disabled={disabled || external} placeholder={external ? 'Managed externally' : configured ? 'Enter replacement secret' : 'Enter client secret'}
      onChange={(event) => onChange(event.target.value)} />
    <div className="credential-actions">
      <button className="secondary" disabled={disabled || external || !value.trim()} onClick={() => onAction('replace')}>{busy === 'twitch_client_secret:replace' ? 'Saving...' : configured ? 'Replace secret' : 'Add secret'}</button>
      {host === 'desktop' && value.trim() && <button className="primary" disabled={disabled || external} onClick={() => onAction('replace', true)}>{configured ? 'Replace secret & restart' : 'Add secret & restart'}</button>}
      <button className="secondary" disabled={disabled || !configured} onClick={() => onAction('test')}>{busy === 'twitch_client_secret:test' ? 'Testing...' : 'Test saved secret'}</button>
      {removable && <details className="secret-actions-menu">
        <summary>Secret actions</summary>
        <div className="secret-actions-menu-items">
          <button className="ghost destructive" disabled={disabled} onClick={() => onAction('remove')}>{busy === 'twitch_client_secret:remove' ? 'Removing...' : 'Remove secret'}</button>
          {host === 'desktop' && <button className="ghost destructive" disabled={disabled} onClick={() => onAction('remove', true)}>Remove secret &amp; restart</button>}
        </div>
      </details>}
    </div>
    {host === 'server' && <p className="settings-hint" id={`${id}-effect`}>{external
      ? 'Change this secret on the Server host.'
      : 'Adding, replacing or removing a secret stops the bot and clears authorization. Connect Twitch again after saving a valid secret.'}</p>}
    {!credential && <p className="credential-warning" role="alert">Secret status unavailable. Reopen Settings to retry.</p>}
    {credential?.validation_status === 'validation_failed' && <p className="credential-warning" role="alert">Secret validation failed.</p>}
  </div>
}
