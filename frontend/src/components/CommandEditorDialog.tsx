import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from 'react'

function isBackdrop(event: MouseEvent<HTMLDialogElement>) {
  if (event.target !== event.currentTarget) return false
  const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect()
  return event.clientX < left || event.clientX >= right || event.clientY < top || event.clientY >= bottom
}

export default function CommandEditorDialog({ id, title, dirty, busy, error, onClose, children }: {
  id: string
  title: string
  dirty: boolean
  busy: boolean
  error: string
  onClose: () => void
  children: ReactNode
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

  return <dialog ref={dialog} className="command-editor-dialog" id={id} aria-labelledby={titleId} aria-busy={busy}
    onPointerDown={(event) => { pressedBackdrop.current = isBackdrop(event) }}
    onClick={(event) => {
      const close = pressedBackdrop.current && isBackdrop(event)
      pressedBackdrop.current = false
      if (close && !busy) onClose()
    }}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="command-dialog-heading">
      <div><h2 id={titleId}>{title}</h2>{dirty && <span className="mini-badge dirty-badge">Unsaved changes</span>}</div>
      <button className="ghost command-dialog-close" type="button" aria-label="Close editor" disabled={busy} onClick={onClose}>×</button>
    </div>
    {error && <p className="command-dialog-error" role="alert">{error}</p>}
    <div className="command-dialog-body">{children}</div>
  </dialog>
}
