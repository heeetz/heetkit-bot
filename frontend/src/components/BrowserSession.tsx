import { type FormEvent, type ReactNode, useEffect, useState, useSyncExternalStore } from 'react'
import { shell } from '../i18n/app'
import { useCatalog } from '../i18n/core'
import LanguageSwitcher from './LanguageSwitcher'
import Switch from './Switch'
import HelpTip from './HelpTip'
import { browserConnectionSecure, getBrowserSession, loginBrowserSession, logoutBrowserSession, restoreBrowserSession, subscribeBrowserSession } from '../httpTransport'

export default function BrowserSession({ children }: { children: ReactNode }) {
  const text = useCatalog(shell).session
  const session = useSyncExternalStore(subscribeBrowserSession, getBrowserSession)
  const [adminToken, setAdminToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [remember, setRemember] = useState(false)
  const secure = browserConnectionSecure()
  const [restoring, setRestoring] = useState(secure)
  useEffect(() => { if (secure) void restoreBrowserSession().finally(() => setRestoring(false)) }, [secure])

  const login = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !secure) return
    const token = adminToken
    setAdminToken('')
    setError('')
    setBusy(true)
    try { await loginBrowserSession(token, remember) }
    catch (reason) { setError(reason instanceof Error ? reason.message : text.failed) }
    finally { setBusy(false) }
  }

  if (session.authenticated) {
    return <div className="browser-management"><div className="browser-session-bar"><span>{text.bar}</span><div className="row-actions"><button className="ghost" onClick={() => { setError(''); void logoutBrowserSession(true) }}>{text.signOutEverywhere}</button><button className="secondary" onClick={() => { setError(''); void logoutBrowserSession() }}>{text.signOut}</button></div></div>{children}</div>
  }
  if (restoring) return null
  return (
    <main className="browser-login">
      <section className="card">
        <div className="brand"><img className="brand-mark" src="./icon.png" alt="" /><strong>HeetKit</strong><LanguageSwitcher /></div>
        <div className="browser-login-title"><h1>{text.title}</h1><HelpTip label={text.helpLabel}><ul>{text.help.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip></div>
        {!secure && <p className="inline-error" role="alert">{text.insecure}</p>}
        {session.message && <p role="status">{session.message === 'expired' ? text.expired : session.message === 'signed_out' ? text.signedOut : session.message}</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        <form onSubmit={(event) => void login(event)}>
          <label htmlFor="admin-token">{text.token}</label>
          <input id="admin-token" type="password" autoComplete="off" spellCheck={false} autoCapitalize="none" value={adminToken} disabled={!secure || busy} onChange={(event) => setAdminToken(event.target.value)} />
          <Switch checked={remember} disabled={!secure || busy} onCheckedChange={setRemember}>{text.remember}</Switch>
          <button className="primary" type="submit" disabled={!secure || busy || !adminToken}>{busy ? text.signingIn : text.signIn}</button>
        </form>
      </section>
    </main>
  )
}
