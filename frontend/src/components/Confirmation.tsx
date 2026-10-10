import { useEffect, useId, useRef, type KeyboardEvent } from 'react'

interface ConfirmationProps {
  title: string
  description: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function Confirmation({ title, description, danger = false, onConfirm, onCancel }: ConfirmationProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const element = dialog.current!
    element.showModal()
    cancel.current?.focus()
    return () => {
      element.close()
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [])

  const handleKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onCancel()
    } else if (event.key === 'Tab') {
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button'))
      const next = event.shiftKey ? buttons[0] : buttons[buttons.length - 1]
      if (document.activeElement === next) {
        event.preventDefault()
        const target = event.shiftKey ? buttons[buttons.length - 1] : buttons[0]
        target?.focus()
      }
    }
  }

  return (
    <dialog ref={dialog} className="confirmation-dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
      onKeyDown={handleKeyDown} onCancel={(event) => { event.preventDefault(); onCancel() }}>
      <h3 id={titleId}>{title}</h3>
      <p id={descriptionId}>{description}</p>
      <div className="confirmation-actions">
        <button ref={cancel} type="button" className="secondary" onClick={onCancel}>Cancel</button>
        <button type="button" className={danger ? 'danger' : 'primary'} onClick={onConfirm}>Confirm</button>
      </div>
    </dialog>
  )
}
