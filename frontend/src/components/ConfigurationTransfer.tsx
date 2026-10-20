import { useRef, useState, type ChangeEvent } from 'react'

import {
  type ConfigurationImportPreviewResponse,
  waitForBridge,
} from '../bridge'

const MAX_ARCHIVE_BYTES = 1024 * 1024
const FALLBACK_EXPORT_FILENAME = 'heetkit-configuration.zip'

function bytesToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return window.btoa(binary)
}

function base64ToBlob(value: string): Blob {
  const binary = window.atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return new Blob([bytes], { type: 'application/zip' })
}

function safeExportFilename(filename: string): string {
  return /^[A-Za-z0-9][A-Za-z0-9._ -]{0,126}\.zip$/i.test(filename)
    && filename !== '.' && filename !== '..'
    ? filename
    : FALLBACK_EXPORT_FILENAME
}

interface SelectedImport {
  filename: string
  archiveBase64: string
  preview: ConfigurationImportPreviewResponse & {
    preview_token: string
    application_version: string
    format_version: number
    sections: NonNullable<ConfigurationImportPreviewResponse['sections']>
    effects: string[]
    preserved: string[]
  }
}

export default function ConfigurationTransfer() {
  const input = useRef<HTMLInputElement>(null)
  const [selection, setSelection] = useState<SelectedImport | null>(null)
  const [busy, setBusy] = useState<'export' | 'preview' | 'import' | ''>('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const resetSelection = () => {
    setSelection(null)
    if (input.current) input.current.value = ''
  }

  const exportConfiguration = async () => {
    setBusy('export')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.export_configuration()
      if (!result.ok) {
        throw new Error(result.error ?? 'The configuration archive could not be created.')
      }
      if (result.saved) {
        setNotice('Portable configuration saved. Keep it private if it contains filter text or block lists.')
        return
      }
      if (result.cancelled) {
        setNotice('Configuration export cancelled. No file was saved.')
        return
      }
      if (!result.archive_base64) throw new Error('The configuration archive could not be created.')
      const blob = base64ToBlob(result.archive_base64)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = safeExportFilename(result.filename ?? '')
      document.body.appendChild(anchor)
      try {
        anchor.click()
      } finally {
        anchor.remove()
        URL.revokeObjectURL(url)
      }
      setNotice('Portable configuration exported. Keep it private if it contains filter text or block lists.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The configuration archive could not be created.')
    } finally {
      setBusy('')
    }
  }

  const previewImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setSelection(null)
    setError('')
    setNotice('')
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setError('Choose a ZIP configuration archive.')
      event.target.value = ''
      return
    }
    if (file.size > MAX_ARCHIVE_BYTES) {
      setError('The configuration archive must be 1 MiB or smaller.')
      event.target.value = ''
      return
    }
    setBusy('preview')
    try {
      const archiveBase64 = bytesToBase64(await file.arrayBuffer())
      const api = await waitForBridge()
      const result = await api.preview_configuration_import(archiveBase64)
      if (!result.ok || !result.preview_token || !result.application_version
        || !Number.isInteger(result.format_version) || !Array.isArray(result.sections)) {
        throw new Error(result.error ?? 'The configuration archive could not be previewed.')
      }
      setSelection({
        filename: file.name,
        archiveBase64,
        preview: {
          ...result,
          preview_token: result.preview_token,
          application_version: result.application_version,
          format_version: result.format_version!,
          sections: result.sections,
          effects: Array.isArray(result.effects) ? result.effects : [],
          preserved: Array.isArray(result.preserved) ? result.preserved : [],
        },
      })
    } catch (reason) {
      resetSelection()
      setError(reason instanceof Error ? reason.message : 'The configuration archive could not be previewed.')
    } finally {
      setBusy('')
    }
  }

  const cancelImport = () => {
    resetSelection()
    setError('')
    setNotice('Configuration import cancelled. No settings were changed.')
  }

  const applyImport = async () => {
    if (!selection) return
    setBusy('import')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.apply_configuration_import(
        selection.archiveBase64,
        selection.preview.preview_token,
        true,
      )
      if (!result.ok) throw new Error(result.error ?? 'The configuration could not be imported.')
      window.location.reload()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The configuration could not be imported.')
      setBusy('')
    }
  }

  return (
    <section className="card settings-page" id="configuration-transfer" aria-labelledby="configuration-transfer-heading" aria-busy={Boolean(busy)}>
      <div className="section-heading">
        <div>
          <h2 id="configuration-transfer-heading">Configuration transfer</h2>
          <p className="section-copy">Move portable, non-secret settings between HeetKit Desktop and Server. This is separate from a full private profile backup.</p>
        </div>
      </div>
      <div className="configuration-transfer-warning">
        <strong>Review before sharing</strong>
        <p>Filter text and AI block lists may contain personal or private information. Exports exclude Twitch identity and channel, secrets and authentication, databases and privacy state, desktop window and startup settings, and machine-specific paths.</p>
      </div>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {notice && <p className="configuration-transfer-notice" role="status">{notice}</p>}
      <div className="configuration-transfer-actions">
        <button className="secondary" disabled={Boolean(busy)} onClick={() => void exportConfiguration()}>
          {busy === 'export' ? 'Exporting…' : 'Export configuration'}
        </button>
        <label className={`secondary file-button${busy ? ' disabled' : ''}`}>
          {busy === 'preview' ? 'Checking archive…' : 'Choose ZIP to import'}
          <input ref={input} type="file" accept=".zip,application/zip" disabled={Boolean(busy)} onChange={(event) => void previewImport(event)} />
        </label>
        <span className="settings-hint">ZIP only, up to 1 MiB.</span>
      </div>
      {selection && (
        <div className="configuration-import-preview" aria-labelledby="configuration-import-preview-heading">
          <div>
            <h3 id="configuration-import-preview-heading">Import preview</h3>
            <p className="settings-hint"><strong>{selection.filename}</strong> · HeetKit {selection.preview.application_version} · format {selection.preview.format_version}</p>
          </div>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Included settings</th><th>Incoming</th><th>Current (will be replaced)</th></tr></thead>
              <tbody>{selection.preview.sections.map((section) => (
                <tr key={section.name}><td><strong>{section.name}</strong>{section.details && section.details.length > 0
                  ? <span className="configuration-import-details">{section.details.join(' · ')}</span> : null}</td><td>{section.incoming_count}</td><td>{section.current_count}</td></tr>
              ))}</tbody>
            </table>
          </div>
          {selection.preview.effects.length > 0 && <div><strong>Effects</strong><ul>{selection.preview.effects.map((effect) => <li key={effect}>{effect}</li>)}</ul></div>}
          {selection.preview.preserved.length > 0 && <div><strong>Preserved</strong><ul>{selection.preview.preserved.map((item) => <li key={item}>{item}</li>)}</ul></div>}
          <p className="configuration-import-confirmation">Importing replaces every supported collection shown above and applies its active settings. The app will reload afterward to clear stale editors.</p>
          <div className="settings-actions">
            <button className="secondary" disabled={Boolean(busy)} onClick={cancelImport}>Cancel import</button>
            <button className="danger" disabled={Boolean(busy)} onClick={() => void applyImport()}>{busy === 'import' ? 'Importing…' : 'Confirm import and reload'}</button>
          </div>
        </div>
      )}
    </section>
  )
}
