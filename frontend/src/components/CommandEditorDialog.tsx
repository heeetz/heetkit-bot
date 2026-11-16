import { useEffect, useId, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from 'react'
import { commandEditorCopy as copy } from '../i18n/commands.en'

export interface CommandEditorSection {
  id: keyof typeof copy.sections
  body: ReactNode
}

function isBackdrop(event: MouseEvent<HTMLDialogElement>) {
  if (event.target !== event.currentTarget) return false
  const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect()
  return event.clientX < left || event.clientX >= right || event.clientY < top || event.clientY >= bottom
}

export default function CommandEditorDialog({ id, title, dirty, busy, error, sections, saveLabel, saveDisabled, onSave, onClose }: {
  id: string
  title: string
  dirty: boolean
  busy: boolean
  error: string
  sections: CommandEditorSection[]
  saveLabel: string
  saveDisabled?: boolean
  onSave: () => void
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const panels = useRef<HTMLDivElement>(null)
  const pressedBackdrop = useRef(false)
  const titleId = useId()
  const [section, setSection] = useState<CommandEditorSection['id']>('general')
  const [validationError, setValidationError] = useState('')
  const activeSection = sections.some((item) => item.id === section) ? section : 'general'

  const showSection = (next: CommandEditorSection['id']) => {
    setSection(next)
    panels.current?.scrollTo({ top: 0 })
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy || saveDisabled) return
    // All draft fields stay mounted, including native inputs in inactive sections.
    const invalid = event.currentTarget.querySelector<HTMLInputElement | HTMLTextAreaElement>('input:invalid, textarea:invalid')
    if (invalid) {
      const target = sections.find((item) => invalid.closest(`#${id}-${item.id}`))
      if (target) showSection(target.id)
      setValidationError(invalid.validationMessage)
      requestAnimationFrame(() => invalid.focus())
      return
    }
    setValidationError('')
    onSave()
  }

  useEffect(() => {
    const element = dialog.current!
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    element.showModal()
    element.querySelector<HTMLElement>('[data-editor-focus]')?.focus({ preventScroll: true })
    return () => {
      element.close()
      if (opener?.isConnected) opener.focus({ preventScroll: true })
    }
  }, [])

  return <dialog ref={dialog} className="command-editor-dialog" id={id} aria-labelledby={titleId} aria-busy={busy}
    onPointerDown={(event) => { pressedBackdrop.current = isBackdrop(event) }}
    onClick={(event) => {
      const close = pressedBackdrop.current && isBackdrop(event)
      pressedBackdrop.current = false
      if (close && !busy) onClose()
    }}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="command-dialog-heading">
      <div><h2 id={titleId}>{title}</h2>{dirty && <span className="mini-badge dirty-badge">{copy.unsaved}</span>}</div>
      <button className="ghost command-dialog-close" type="button" aria-label={copy.close} disabled={busy} onClick={onClose}>×</button>
    </div>
    {(validationError || error) && <p className="command-dialog-error" role="alert">{validationError || error}</p>}
    <form className="command-editor-form" noValidate onSubmit={submit} onInput={() => setValidationError('')}>
      <div className="command-dialog-body">
        <nav className="command-dialog-sections" aria-label={copy.sectionsLabel}>
          {sections.map(({ id: sectionId }) => <button key={sectionId} id={`${id}-tab-${sectionId}`}
            type="button" aria-controls={`${id}-${sectionId}`} aria-current={activeSection === sectionId ? 'true' : undefined}
            onClick={() => showSection(sectionId)}>{copy.sections[sectionId]}</button>)}
        </nav>
        <div className="command-dialog-panels" ref={panels}>
          {sections.map(({ id: sectionId, body }) => <section key={sectionId} id={`${id}-${sectionId}`}
            className="command-dialog-panel" aria-labelledby={`${id}-tab-${sectionId}`} hidden={activeSection !== sectionId}>
            <fieldset disabled={busy}>{body}</fieldset>
          </section>)}
        </div>
      </div>
      <div className="command-dialog-footer">
        <button type="button" className="secondary" disabled={busy} onClick={onClose}>{copy.cancel}</button>
        <button type="submit" className="primary" disabled={busy || saveDisabled}>{busy ? copy.saving : saveLabel}</button>
      </div>
    </form>
  </dialog>
}
