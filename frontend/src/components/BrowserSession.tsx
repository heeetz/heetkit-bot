import { type FormEvent, type ReactNode, useState, useSyncExternalStore } from 'react'
import { browserConnectionSecure, getBrowserSession, loginBrowserSession, logoutBrowserSession, subscribeBrowserSession } from '../httpTransport'

export default function BrowserSession({ children }: { children: ReactNode }) {
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
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Sign in failed. Retry.') }
    finally { setBusy(false) }
  }

  if (session.authenticated) {
    return <div className="browser-management"><div className="browser-session-bar"><span>Server management</span><button className="secondary" onClick={() => { setError(''); void logoutBrowserSession() }}>Sign out</button></div>{children}</div>
  }
  return (
    <main className="browser-login">
      <section className="card">
        <div className="brand"><img className="brand-mark" src="./icon.png" alt="" /><strong>HeetKit</strong></div>
        <h1>Sign in to server</h1>
        <p>Enter the administrator token configured on this HeetKit server. The session stays in this tab's memory and ends after one hour or when the page reloads.</p>
        {!secure && <p className="inline-error" role="alert">Open this panel using HTTPS or a loopback address before entering a token.</p>}
        {session.message && <p role="status">{session.message}</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        <form onSubmit={(event) => void login(event)}>
          <label htmlFor="admin-token">Administrator token</label>
          <input id="admin-token" type="password" autoComplete="off" spellCheck={false} autoCapitalize="none" value={adminToken} disabled={!secure || busy} onChange={(event) => setAdminToken(event.target.value)} />
          <button className="primary" type="submit" disabled={!secure || busy || !adminToken}>{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>
      </section>
    </main>
  )
}
