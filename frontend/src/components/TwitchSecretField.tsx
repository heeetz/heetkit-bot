import { useId } from 'react'
import type { CredentialInfo } from '../bridge'
import HelpTip from './HelpTip'
import { useCatalog } from '../i18n/core'
import { settingsText } from '../i18n/settings'

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
  const text = useCatalog(settingsText).secret
  const configured = Boolean(credential?.configured)
  const external = credential?.managed === false
  const disabled = Boolean(busy) || !credential
  const removable = configured && !external && (host === 'server' || credential?.source === 'credential_store')
  return <div className="twitch-secret-field form-field">
    <div className="twitch-secret-label">
      <label htmlFor={id}>{text.label}</label>
      <HelpTip label={text.label}>
        <ul>
          {text.help.map((item) => <li key={item}>{item}</li>)}
          {host === 'desktop'
            ? <li>{text.helpDesktop}</li>
            : <li>{text.helpServer}</li>}
          {external && <li>{text.helpExternal}</li>}
        </ul>
      </HelpTip>
    </div>
    <input id={id} aria-label={text.label} aria-describedby={host === 'server' ? `${id}-effect` : undefined} type="password" autoComplete="new-password" maxLength={8192}
      value={value} disabled={disabled || external} placeholder={external ? text.managedExternally : configured ? text.replacementPlaceholder : text.placeholder}
      onChange={(event) => onChange(event.target.value)} />
    <div className="credential-actions">
      <button className="secondary" disabled={disabled || external || !value.trim()} onClick={() => onAction('replace')}>{busy === 'twitch_client_secret:replace' ? text.saving : configured ? text.replace : text.add}</button>
      {host === 'desktop' && value.trim() && <button className="primary" disabled={disabled || external} onClick={() => onAction('replace', true)}>{configured ? text.replaceRestart : text.addRestart}</button>}
      <button className="secondary" disabled={disabled || !configured} onClick={() => onAction('test')}>{busy === 'twitch_client_secret:test' ? text.testing : text.test}</button>
      {removable && <details className="secret-actions-menu">
        <summary>{text.actions}</summary>
        <div className="secret-actions-menu-items">
          <button className="ghost destructive" disabled={disabled} onClick={() => onAction('remove')}>{busy === 'twitch_client_secret:remove' ? text.removing : text.remove}</button>
          {host === 'desktop' && <button className="ghost destructive" disabled={disabled} onClick={() => onAction('remove', true)}>{text.removeRestart}</button>}
        </div>
      </details>}
    </div>
    {host === 'server' && <p className="settings-hint" id={`${id}-effect`}>{external
      ? text.serverExternal
      : text.serverEffect}</p>}
    {!credential && <p className="credential-warning" role="alert">{text.statusUnavailable}</p>}
    {credential?.validation_status === 'validation_failed' && <p className="credential-warning" role="alert">{text.validationFailed}</p>}
  </div>
}
