import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from 'react'

function isBackdrop(event: MouseEvent<HTMLDialogElement>) {
  if (event.target !== event.currentTarget) return false
  const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect()
  return event.clientX < left || event.clientX >= right || event.clientY < top || event.clientY >= bottom
}

export default function EditorDialog({ id, title, closeLabel, dirtyLabel, busy, error, onClose, children, className = '' }: {
  id: string
  title: string
  closeLabel: string
  dirtyLabel?: string
  busy: boolean
  error?: string
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const pressedBackdrop = useRef(false)
  const titleId = useId()

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

  return <dialog ref={dialog} className={`command-editor-dialog ${className}`.trim()} id={id} aria-labelledby={titleId} aria-busy={busy}
    onPointerDown={(event) => { pressedBackdrop.current = isBackdrop(event) }}
    onClick={(event) => {
      const close = pressedBackdrop.current && isBackdrop(event)
      pressedBackdrop.current = false
      if (close && !busy) onClose()
    }}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="command-dialog-heading">
      <div><h2 id={titleId}>{title}</h2>{dirtyLabel && <span className="mini-badge dirty-badge">{dirtyLabel}</span>}</div>
      <button className="ghost command-dialog-close" type="button" aria-label={closeLabel} disabled={busy} onClick={onClose}>×</button>
    </div>
    {error && <p className="command-dialog-error" role="alert">{error}</p>}
    {children}
  </dialog>
}

export function EditorSections<Id extends string>({ id, label, sections, active, onSelect }: {
  id: string
  label: string
  sections: { id: Id; label: string; body: ReactNode }[]
  active: Id
  onSelect: (section: Id) => void
}) {
  const panels = useRef<HTMLDivElement>(null)

  return <div className="command-dialog-body">
    <nav className="command-dialog-sections" aria-label={label}>
      {sections.map(({ id: sectionId, label: sectionLabel }) => <button key={sectionId} id={`${id}-tab-${sectionId}`}
        type="button" aria-controls={`${id}-${sectionId}`} aria-current={active === sectionId ? 'true' : undefined}
        onClick={() => {
          onSelect(sectionId)
          panels.current?.scrollTo({ top: 0 })
        }}>{sectionLabel}</button>)}
    </nav>
    <div className="command-dialog-panels" ref={panels}>
      {sections.map(({ id: sectionId, body }) => <section key={sectionId} id={`${id}-${sectionId}`}
        className="command-dialog-panel" aria-labelledby={`${id}-tab-${sectionId}`} hidden={active !== sectionId}>{body}</section>)}
    </div>
  </div>
}
