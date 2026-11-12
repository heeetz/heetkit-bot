import { useEffect, useRef, useState } from 'react'
import { type AboutInfo, type DesktopUpdateProgress, type UpdateCheckResponse, isBrowserMode, waitForBridge } from '../bridge'
import HelpTip from '../components/HelpTip'
import { confirmDesktopRestart } from '../desktopRestart'

type ExternalDestination = 'repository' | 'license' | 'third_party_notices' | 'author_twitch' | 'releases'

function AboutPage() {
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [error, setError] = useState('')
  const [copyLabel, setCopyLabel] = useState('Copy')
  const [opening, setOpening] = useState<ExternalDestination | ''>('')
  const [updateResult, setUpdateResult] = useState<UpdateCheckResponse | null>(null)
  const [updateError, setUpdateError] = useState('')
  const [updateBusy, setUpdateBusy] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [progress, setProgress] = useState<DesktopUpdateProgress>({})
  const updateLock = useRef(false)

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

  const checkForUpdates = async () => {
    if (updateLock.current) return
    updateLock.current = true
    setUpdateResult(null)
    setUpdateError('')
    setUpdateBusy(true)
    try {
      const api = await waitForBridge()
      const result = await api.check_for_updates()
      if (!result.ok) {
        setUpdateError(result.error ?? 'Could not check for updates.')
        return
      }
      setUpdateResult(result)
    } catch (reason) {
      setUpdateError(reason instanceof Error ? reason.message : 'Could not check for updates.')
    } finally {
      updateLock.current = false
      setUpdateBusy(false)
    }
  }

  const installUpdate = async () => {
    const version = updateResult?.latest_version
    if (updateLock.current || !version) return
    updateLock.current = true
    setInstalling(true)
    setProgress({})
    setUpdateError('')
    let polling: number | undefined
    let restarting = false
    try {
      const api = await waitForBridge()
      polling = window.setInterval(() => {
        void api.get_desktop_update_progress().then(setProgress).catch(() => {})
      }, 300)
      const prepared = await api.prepare_desktop_update(version)
      if (!prepared.ok) throw new Error(prepared.error ?? 'Could not download and verify the update.')
      if (!confirmDesktopRestart()) {
        setUpdateError('Update verified. Save any drafts, then select Update & restart to continue.')
        return
      }
      setProgress({ phase: 'ready' })
      const result = await api.finish_desktop_update(version)
      if (!result.ok) throw new Error(result.error ?? 'Could not start the installer handoff.')
      restarting = true
    } catch (reason) {
      setUpdateError(reason instanceof Error ? reason.message : 'Could not prepare the update.')
    } finally {
      window.clearInterval(polling)
      if (!restarting) {
        updateLock.current = false
        setInstalling(false)
      }
    }
  }

  const currentVersion = updateResult?.current_version ?? about?.version ?? '…'

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

      {!isBrowserMode() && <article className="card update-card">
        <div className="section-heading update-heading">
          <div className="update-title">
            <h2>Check for updates</h2>
            <HelpTip label="Check for updates">HeetKit checks the latest stable release on request. Update &amp; restart downloads and verifies the installer before closing HeetKit. Open release / downloads is available for manual installation.</HelpTip>
          </div>
        </div>
        <div className="update-toolbar">
          <div className="update-actions">
            <button className={updateResult?.automatic_update ? 'secondary' : 'primary'} onClick={() => void checkForUpdates()} disabled={updateBusy || installing}>
              {updateBusy ? 'Checking…' : updateResult || updateError ? 'Check again' : 'Check for updates'}
            </button>
            <button className="secondary" onClick={() => void openExternal('releases')} disabled={opening === 'releases'}>
              {opening === 'releases' ? 'Opening…' : 'Open release / downloads'}
            </button>
            {updateResult?.automatic_update && <button className="primary" disabled={installing} onClick={() => void installUpdate()}>Update &amp; restart</button>}
          </div>
          <div className="update-summary" aria-live="polite">
            <div>
              <span className="update-label">Current version</span>
              <strong>{currentVersion}</strong>
            </div>
            {updateResult && (
              <div>
                <span className="update-label">Latest version</span>
                <strong>{updateResult.latest_version ?? 'Unavailable'}</strong>
              </div>
            )}
          </div>
        </div>
        {updateResult && (
          <div className={`update-result ${updateResult.update_available ? 'update-available' : 'update-current'}`} role="status">
            <strong>{updateResult.update_available ? 'Update available' : 'You are up to date'}</strong>
            {updateResult.release_name && <span>{updateResult.release_name}</span>}
            {updateResult.published_at && <time dateTime={updateResult.published_at}>Published {updateResult.published_at}</time>}
            {updateResult.release_notes && <p className="update-notes">{updateResult.release_notes}</p>}
            {updateResult.automatic_update_reason && <p>{updateResult.automatic_update_reason}</p>}
          </div>
        )}
        {installing && <div role="status">
          {progress.phase === 'ready' ? 'Closing HeetKit to install the update…' : progress.phase === 'verifying' ? 'Verifying installer and preparing the restart…' : 'Downloading installer…'}
          {progress.phase === 'downloading' && <progress aria-label="Installer download" value={progress.downloaded} max={progress.total} />}
        </div>}
        {updateError && <p className="inline-error update-error" role="alert">{updateError}</p>}
      </article>}

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
