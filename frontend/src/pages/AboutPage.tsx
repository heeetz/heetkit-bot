import { useEffect, useRef, useState } from 'react'
import { type AboutInfo, type DesktopUpdateProgress, isBrowserMode, waitForBridge } from '../bridge'
import HelpTip from '../components/HelpTip'
import { confirmDesktopRestart } from '../desktopRestart'
import type useUpdateCheck from '../useUpdateCheck'
import { aboutText } from '../i18n/about'
import { useCatalog, useI18n } from '../i18n/core'

type ExternalDestination = 'repository' | 'license' | 'third_party_notices' | 'author_twitch' | 'releases'

function AboutPage({ updates }: { updates: ReturnType<typeof useUpdateCheck> }) {
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [error, setError] = useState('')
  const text = useCatalog(aboutText)
  const { fmt } = useI18n()
  const [copied, setCopied] = useState(false)
  const [opening, setOpening] = useState<ExternalDestination | ''>('')
  const { result: updateResult, error: checkError, busy: updateBusy, check } = updates
  const [updateError, setUpdateError] = useState('')
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
          setError(reason instanceof Error ? reason.message : text.unavailable)
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
            throw new Error(text.clipboardUnavailable)
          }
        } finally {
          input.remove()
        }
      }
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.copyFailed)
    }
  }

  const openExternal = async (destination: ExternalDestination) => {
    setOpening(destination)
    setError('')
    try {
      const api = await waitForBridge()
      const result = await api.open_external_link(destination)
      if (!result.ok) {
        throw new Error(result.error ?? text.openFailed)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.openFailed)
    } finally {
      setOpening('')
    }
  }

  const checkForUpdates = async () => {
    if (updateLock.current) return
    setUpdateError('')
    await check()
  }

  const installUpdate = async () => {
    const version = updateResult?.latest_version
    if (updateLock.current || updateBusy || !version) return
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
      if (!prepared.ok) throw new Error(prepared.error ?? text.downloadFailed)
      if (!confirmDesktopRestart()) {
        setUpdateError(text.verifiedSaveDrafts)
        return
      }
      setProgress({ phase: 'ready' })
      const result = await api.finish_desktop_update(version)
      if (!result.ok) throw new Error(result.error ?? text.handoffFailed)
      restarting = true
    } catch (reason) {
      setUpdateError(reason instanceof Error ? reason.message : text.prepareFailed)
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
            <p className="label">{text.label}</p>
            <h2>{about?.application_name ?? 'HeetKit'}</h2>
            <p className="section-copy">{about?.application_subtitle ?? text.subtitle}</p>
          </div>
          <span className="mini-badge">{fmt(text.version, { version: about?.version ?? '…' })}</span>
        </div>
        <dl className="about-details">
          <div><dt>{text.createdBy}</dt><dd>{about?.author ?? 'heeetz'}</dd></div>
          <div><dt>{text.twitch}</dt><dd><button className="ghost" onClick={() => void openExternal('author_twitch')} disabled={Boolean(opening)} aria-label={fmt(text.openTwitch, { handle: about?.author_twitch ?? '@heet_ok' })}>{about?.author_twitch ?? '@heet_ok'} {opening === 'author_twitch' ? '…' : '↗'}</button></dd></div>
          <div className="about-contact"><dt>{text.discord}</dt><dd><code>{about?.discord_contact ?? 'de.tected'}</code><button className="ghost" onClick={() => void copyDiscord}>{copied ? text.copied : text.copy}</button></dd></div>
          <div><dt>{text.license}</dt><dd>{about?.license_name ?? 'Apache-2.0'}</dd></div>
        </dl>
        <p className="about-disclaimer">{text.disclaimer}</p>
      </article>

      {!isBrowserMode() && <article className="card update-card" id="desktop-updates" aria-labelledby="desktop-updates-title">
        <div className="section-heading update-heading">
          <div className="update-title">
            <h2 id="desktop-updates-title">{text.checkTitle}</h2>
            <HelpTip label={text.helpLabel}><ul>{text.help.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip>
          </div>
        </div>
        <div className="update-toolbar">
          <div className="update-actions">
            <button className={updateResult?.automatic_update ? 'secondary' : 'primary'} onClick={() => void checkForUpdates()} disabled={updateBusy || installing}>
              {updateBusy ? text.checking : updateResult || checkError ? text.checkAgain : text.check}
            </button>
            <button className="secondary" onClick={() => void openExternal('releases')} disabled={opening === 'releases'}>
              {opening === 'releases' ? text.opening : text.openRelease}
            </button>
            {updateResult?.automatic_update && <button className="primary" disabled={installing} aria-describedby="update-restart-effect" onClick={() => void installUpdate()}>{text.updateRestart}</button>}
          </div>
          <div className="update-summary" aria-live="polite">
            <div>
              <span className="update-label">{text.currentVersion}</span>
              <strong>{currentVersion}</strong>
            </div>
            {updateResult && (
              <div>
                <span className="update-label">{text.latestVersion}</span>
                <strong>{updateResult.latest_version ?? text.versionUnavailable}</strong>
              </div>
            )}
          </div>
        </div>
        {updateResult?.automatic_update && <p className="muted" id="update-restart-effect">{text.restartEffect}</p>}
        {updateResult && (
          <div className={`update-result ${updateResult.update_available ? 'update-available' : 'update-current'}`} role="status">
            <strong>{updateResult.update_available ? text.updateAvailable : text.upToDate}</strong>
            {updateResult.release_name && <span>{updateResult.release_name}</span>}
            {updateResult.published_at && <time dateTime={updateResult.published_at}>{fmt(text.published, { date: updateResult.published_at })}</time>}
            {updateResult.release_notes && <p className="update-notes">{updateResult.release_notes}</p>}
            {updateResult.automatic_update_reason && <p>{updateResult.automatic_update_reason}</p>}
          </div>
        )}
        {installing && <div role="status">
          {progress.phase === 'ready' ? text.closing : progress.phase === 'verifying' ? text.verifying : text.downloading}
          {progress.phase === 'downloading' && <progress aria-label={text.downloadProgress} value={progress.downloaded} max={progress.total} />}
        </div>}
        {(updateError || checkError) && <p className="inline-error update-error" role="alert">{updateError || checkError}</p>}
      </article>}

      <article className="card about-links-card">
        <div className="section-heading">
          <div>
            <p className="label">{text.linksLabel}</p>
            <h2>{text.resources}</h2>
            <p className="section-copy">{text.linksNote}</p>
          </div>
        </div>
        <div className="about-link-list">
          <button className="secondary" onClick={() => void openExternal('repository')} disabled={Boolean(opening)}>
            {text.repository} {opening === 'repository' ? '…' : '↗'}
          </button>
          <button className="secondary" onClick={() => void openExternal('license')} disabled={Boolean(opening)}>
            {text.apacheLicense} {opening === 'license' ? '…' : '↗'}
          </button>
          <button className="secondary" onClick={() => void openExternal('third_party_notices')} disabled={Boolean(opening)}>
            {text.notices} {opening === 'third_party_notices' ? '…' : '↗'}
          </button>
        </div>
      </article>
    </section>
  )
}

export default AboutPage
