import { useId } from 'react'
import type { CredentialInfo } from '../bridge'
import HelpTip from './HelpTip'

interface TwitchSecretFieldProps {
  credential?: CredentialInfo
  value: string
  busy: string
  host: 'desktop' | 'server'
  onChange: (value: string) => void
  onAction: (action: 'replace' | 'remove' | 'test') => void
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
      <span className={`state-pill ${configured ? 'enabled' : 'unconfigured'}`}>{configured ? 'Configured' : 'Unconfigured'}</span>
      <HelpTip label="Twitch client secret">
        The field is always a new masked draft; saved secrets are never displayed. Replace/Add and Remove apply immediately.
        Test client secret checks the saved secret with the saved Client ID, without authorizing the bot account.
        {host === 'desktop' ? ' Changes require an application restart; existing OAuth tokens are retained. A secure value overrides the environment fallback.' : ' Changes stop the current session and clear authorization. Connect Twitch again after saving a valid secret.'}
        {external && ' This secret is managed externally. Rotate its environment or secret-file value on the host.'}
      </HelpTip>
    </div>
    <input id={id} aria-label="Twitch client secret" type="password" autoComplete="new-password" maxLength={8192}
      value={value} disabled={disabled || external} placeholder={external ? 'Managed externally' : configured ? 'Enter replacement secret' : 'Enter client secret'}
      onChange={(event) => onChange(event.target.value)} />
    <div className="credential-actions">
      <button className="secondary" disabled={disabled || external || !value.trim()} onClick={() => onAction('replace')}>{busy === 'twitch_client_secret:replace' ? 'Saving...' : configured ? 'Replace secret' : 'Add secret'}</button>
      <button className="secondary" disabled={disabled || !configured} onClick={() => onAction('test')}>{busy === 'twitch_client_secret:test' ? 'Testing...' : 'Test client secret'}</button>
      <button className="ghost destructive" disabled={disabled || !removable} onClick={() => onAction('remove')}>{busy === 'twitch_client_secret:remove' ? 'Removing...' : 'Remove secret'}</button>
    </div>
    {value.trim() && <p className="settings-hint">{host === 'desktop' ? 'Restart required after saving.' : 'Saving stops the bot and clears authorization.'}</p>}
    {!credential && <p className="credential-warning" role="alert">Secret status unavailable. Reopen Settings to retry.</p>}
    {credential?.validation_status === 'validation_failed' && <p className="credential-warning" role="alert">Secret validation failed.</p>}
  </div>
}
