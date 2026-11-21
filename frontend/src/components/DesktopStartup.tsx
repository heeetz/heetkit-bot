import { type ReactNode, useEffect, useState } from 'react'
import { type DesktopStartupStatus, waitForBridge } from '../bridge'
import { shell } from '../i18n/app'
import { useCatalog } from '../i18n/core'
import { loadDesktopLanguage } from '../i18n/language'

export default function DesktopStartup({ children }: { children: (windows: boolean) => ReactNode }) {
  const text = useCatalog(shell).startup
  const [status, setStatus] = useState<DesktopStartupStatus | 'failed' | null>(null)
  useEffect(() => {
    let active = true
    void waitForBridge().then(async (api) => {
      await loadDesktopLanguage(api)
      const next = await api.get_desktop_startup()
      if (active) setStatus(next)
    }).catch(() => {
      if (active) setStatus('failed')
    })
    return () => { active = false }
  }, [])

  if (status && status !== 'failed') return children(status.windows === true)
  return <main className="browser-login desktop-startup">
    <section className="card" aria-labelledby="startup-title" aria-busy={status === null}>
      <div className="brand"><strong>HeetKit</strong></div>
      <h1 id="startup-title">{status === 'failed' ? text.titleFailed : text.titleStarting}</h1>
      {status === 'failed'
        ? <p className="inline-error" role="alert">{text.unavailable}</p>
        : <p role="status">{text.waiting}</p>}
    </section>
  </main>
}
