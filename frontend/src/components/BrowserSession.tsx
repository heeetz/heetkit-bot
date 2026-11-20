import { type FormEvent, type ReactNode, useState, useSyncExternalStore } from 'react'
import { shell } from '../i18n/app'
import { useCatalog } from '../i18n/core'
import LanguageSwitcher from './LanguageSwitcher'
import { browserConnectionSecure, getBrowserSession, loginBrowserSession, logoutBrowserSession, subscribeBrowserSession } from '../httpTransport'

export default function BrowserSession({ children }: { children: ReactNode }) {
  const text = useCatalog(shell).session
  const session = useSyncExternalStore(subscribeBrowserSession, getBrowserSession)
  const [adminToken, setAdminToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const secure = browserConnectionSecure()

  const login = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !secure) return
    const token = adminToken
    setAdminToken('')
    setError('')
    setBusy(true)
    try { await loginBrowserSession(token) }
    catch (reason) { setError(reason instanceof Error ? reason.message : text.failed) }
    finally { setBusy(false) }
  }

  if (session.authenticated) {
    return <div className="browser-management"><div className="browser-session-bar"><span>{text.bar}</span><button className="secondary" onClick={() => { setError(''); void logoutBrowserSession() }}>{text.signOut}</button></div>{children}</div>
  }
  return (
    <main className="browser-login">
      <section className="card">
        <div className="brand"><img className="brand-mark" src="./icon.png" alt="" /><strong>HeetKit</strong><LanguageSwitcher /></div>
        <h1>{text.title}</h1>
        <p>{text.intro}</p>
        {!secure && <p className="inline-error" role="alert">{text.insecure}</p>}
        {session.message && <p role="status">{session.message === 'expired' ? text.expired : session.message === 'signed_out' ? text.signedOut : session.message}</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        <form onSubmit={(event) => void login(event)}>
          <label htmlFor="admin-token">{text.token}</label>
          <input id="admin-token" type="password" autoComplete="off" spellCheck={false} autoCapitalize="none" value={adminToken} disabled={!secure || busy} onChange={(event) => setAdminToken(event.target.value)} />
          <button className="primary" type="submit" disabled={!secure || busy || !adminToken}>{busy ? text.signingIn : text.signIn}</button>
        </form>
      </section>
    </main>
  )
}
