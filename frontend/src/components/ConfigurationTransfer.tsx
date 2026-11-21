import { useRef, useState, type ChangeEvent } from 'react'
import { useCatalog, useI18n } from '../i18n/core'
import { settingsText } from '../i18n/settings'

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
  useRestartDraft('Configuration import', Boolean(selection))
  const [busy, setBusy] = useState<'export' | 'preview' | 'import' | ''>('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const text = useCatalog(settingsText).transfer
  const { fmt } = useI18n()

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
        throw new Error(result.error ?? text.createFailed)
      }
      if (result.saved) {
        setNotice(text.saved)
        return
      }
      if (result.cancelled) {
        setNotice(text.exportCancelled)
        return
      }
      if (!result.archive_base64) throw new Error(text.createFailed)
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
      setNotice(text.exported)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.createFailed)
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
      setError(text.chooseZip)
      event.target.value = ''
      return
    }
    if (file.size > MAX_ARCHIVE_BYTES) {
      setError(text.tooLarge)
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
        throw new Error(result.error ?? text.previewFailed)
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
      setError(reason instanceof Error ? reason.message : text.previewFailed)
    } finally {
      setBusy('')
    }
  }

  const cancelImport = () => {
    resetSelection()
    setError('')
    setNotice(text.importCancelled)
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
      if (!result.ok) throw new Error(result.error ?? text.importFailed)
      window.location.reload()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.importFailed)
      setBusy('')
    }
  }

  return (
    <section className="card settings-page" id="configuration-transfer" aria-labelledby="configuration-transfer-heading" aria-busy={Boolean(busy)}>
      <div className="section-heading">
        <div>
          <h2 id="configuration-transfer-heading">{text.title}</h2>
          <p className="section-copy">{text.intro}</p>
        </div>
      </div>
      <div className="configuration-transfer-warning">
        <strong>{text.reviewTitle}</strong>
        <p>{text.reviewText}</p>
      </div>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {notice && <p className="configuration-transfer-notice" role="status">{notice}</p>}
      <div className="configuration-transfer-actions">
        <button className="secondary" disabled={Boolean(busy)} onClick={() => void exportConfiguration()}>
          {busy === 'export' ? text.exporting : text.export}
        </button>
        <label className={`secondary file-button${busy ? ' disabled' : ''}`}>
          {busy === 'preview' ? text.checking : text.choose}
          <input ref={input} type="file" accept=".zip,application/zip" disabled={Boolean(busy)} onChange={(event) => void previewImport(event)} />
        </label>
        <span className="settings-hint">{text.limitHint}</span>
      </div>
      {selection && (
        <div className="configuration-import-preview" aria-labelledby="configuration-import-preview-heading">
          <div>
            <h3 id="configuration-import-preview-heading">{text.previewTitle}</h3>
            <p className="settings-hint"><strong>{selection.filename}</strong>{fmt(text.previewMeta, { version: selection.preview.application_version, format: String(selection.preview.format_version) })}</p>
          </div>
          <div className="table-scroll">
            <table>
              <thead><tr><th>{text.included}</th><th>{text.incoming}</th><th>{text.current}</th></tr></thead>
              <tbody>{selection.preview.sections.map((section) => (
                <tr key={section.name}><td><strong>{section.name}</strong>{section.details && section.details.length > 0
                  ? <span className="configuration-import-details">{section.details.join(' · ')}</span> : null}</td><td>{section.incoming_count}</td><td>{section.current_count}</td></tr>
              ))}</tbody>
            </table>
          </div>
          {selection.preview.effects.length > 0 && <div><strong>{text.effects}</strong><ul>{selection.preview.effects.map((effect) => <li key={effect}>{effect}</li>)}</ul></div>}
          {selection.preview.preserved.length > 0 && <div><strong>{text.preserved}</strong><ul>{selection.preview.preserved.map((item) => <li key={item}>{item}</li>)}</ul></div>}
          <p className="configuration-import-confirmation">{text.confirmation}</p>
          <div className="settings-actions">
            <button className="secondary" disabled={Boolean(busy)} onClick={cancelImport}>{text.cancelImport}</button>
            <button className="danger" disabled={Boolean(busy)} onClick={() => void applyImport()}>{busy === 'import' ? text.importing : text.confirm}</button>
          </div>
        </div>
      )}
    </section>
  )
}
import { useRestartDraft } from '../desktopRestart'
