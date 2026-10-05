import { useEffect, useState } from 'react'
import { type AboutInfo, waitForBridge } from '../bridge'

type ExternalDestination = 'repository' | 'license' | 'third_party_notices' | 'author_twitch'

function AboutPage() {
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [error, setError] = useState('')
  const [copyLabel, setCopyLabel] = useState('Copy')
  const [opening, setOpening] = useState<ExternalDestination | ''>('')

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const result = await api.get_about_info()
        if (active) {
          setAbout(result)
          setError('')
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : 'About information is unavailable.')
        }
      }
    }
    void load()
    return () => { active = false }
  }, [])

  const copyDiscord = async () => {
    const value = about?.discord_contact ?? 'de.tected'
    setError('')
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
      } else {
        const input = document.createElement('textarea')
        input.value = value
        input.setAttribute('readonly', '')
        input.style.position = 'fixed'
        input.style.opacity = '0'
        document.body.appendChild(input)
        try {
          input.select()
          if (!document.execCommand('copy')) {
            throw new Error('Clipboard access is unavailable.')
          }
        } finally {
          input.remove()
        }
      }
      setCopyLabel('Copied')
      window.setTimeout(() => setCopyLabel('Copy'), 1600)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not copy the Discord contact.')
    }
  }

  const openExternal = async (destination: ExternalDestination) => {
    setOpening(destination)
    setError('')
    try {
      const api = await waitForBridge()
      const result = await api.open_external_link(destination)
      if (!result.ok) {
        throw new Error(result.error ?? 'Could not open the link.')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not open the link.')
    } finally {
      setOpening('')
    }
  }

  return (
    <section className="about-layout">
      {error && <p className="inline-error" role="alert">{error}</p>}
      <article className="card about-card">
        <div className="about-heading">
          <div>
            <p className="label">ABOUT</p>
            <h2>{about?.application_name ?? 'HeetKit'}</h2>
            <p className="section-copy">{about?.application_subtitle ?? 'Desktop control center for Twitch chat'}</p>
          </div>
          <span className="mini-badge">Version {about?.version ?? '…'}</span>
        </div>
        <dl className="about-details">
          <div><dt>Created by</dt><dd>{about?.author ?? 'heeetz'}</dd></div>
          <div><dt>Twitch</dt><dd><button className="ghost" onClick={() => void openExternal('author_twitch')} disabled={Boolean(opening)} aria-label={`Open Twitch profile ${about?.author_twitch ?? '@heet_ok'}`}>{about?.author_twitch ?? '@heet_ok'} {opening === 'author_twitch' ? '…' : '↗'}</button></dd></div>
          <div className="about-contact"><dt>Discord</dt><dd><code>{about?.discord_contact ?? 'de.tected'}</code><button className="ghost" onClick={() => void copyDiscord}>{copyLabel}</button></dd></div>
          <div><dt>License</dt><dd>{about?.license_name ?? 'Apache-2.0'}</dd></div>
        </dl>
        <p className="about-disclaimer">Not affiliated with or endorsed by Twitch.</p>
      </article>

      <article className="card about-links-card">
        <div className="section-heading">
          <div>
            <p className="label">PROJECT LINKS</p>
            <h2>Official resources</h2>
            <p className="section-copy">Links open in your default external browser.</p>
          </div>
        </div>
        <div className="about-link-list">
          <button className="secondary" onClick={() => void openExternal('repository')} disabled={Boolean(opening)}>
            GitHub repository {opening === 'repository' ? '…' : '↗'}
          </button>
          <button className="secondary" onClick={() => void openExternal('license')} disabled={Boolean(opening)}>
            Apache-2.0 license {opening === 'license' ? '…' : '↗'}
          </button>
          <button className="secondary" onClick={() => void openExternal('third_party_notices')} disabled={Boolean(opening)}>
            Third-party notices {opening === 'third_party_notices' ? '…' : '↗'}
          </button>
        </div>
      </article>
    </section>
  )
}

export default AboutPage
