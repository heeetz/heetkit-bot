import { type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

interface HelpTipProps {
  label: string
  children: ReactNode
  className?: string
}

/** Brief, noninteractive help that remains accessible outside clipping panels. */
export default function HelpTip({ label, children, className = '' }: HelpTipProps) {
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const tooltip = useRef<HTMLDivElement>(null)
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const triggerHovered = useRef(false)
  const tooltipHovered = useRef(false)
  const focused = useRef(false)
  const dismissed = useRef(false)
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null)

  const clearHover = () => {
    if (hoverTimer.current !== null) clearTimeout(hoverTimer.current)
    hoverTimer.current = null
  }
  const clearClose = () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current)
    closeTimer.current = null
  }
  const show = () => {
    clearHover()
    clearClose()
    dismissed.current = false
    setOpen(true)
  }
  const dismiss = () => {
    clearHover()
    clearClose()
    dismissed.current = true
    tooltipHovered.current = false
    setOpen(false)
    setPosition(null)
  }
  const scheduleClose = () => {
    clearClose()
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null
      if (!focused.current && !triggerHovered.current && !tooltipHovered.current) {
        setOpen(false)
        setPosition(null)
      }
    }, 150)
  }

  useEffect(() => () => {
    if (hoverTimer.current !== null) clearTimeout(hoverTimer.current)
    if (closeTimer.current !== null) clearTimeout(closeTimer.current)
  }, [])

  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const anchor = trigger.current
      const content = tooltip.current
      if (!anchor || !content) return
      if (anchor.getClientRects().length === 0) {
        setOpen(false)
        setPosition(null)
        return
      }
      const padding = 12
      const gap = 8
      const anchorRect = anchor.getBoundingClientRect()
      const contentRect = content.getBoundingClientRect()
      const below = window.innerHeight - anchorRect.bottom - gap - padding
      const above = anchorRect.top - gap - padding
      const proposedTop = contentRect.height <= below || below >= above
        ? anchorRect.bottom + gap
        : anchorRect.top - gap - contentRect.height
      const left = Math.max(padding, Math.min(
        anchorRect.left + (anchorRect.width - contentRect.width) / 2,
        window.innerWidth - contentRect.width - padding,
      ))
      const top = Math.max(padding, Math.min(
        proposedTop,
        window.innerHeight - contentRect.height - padding,
      ))
      setPosition((previous) => previous?.left === left && previous.top === top ? previous : { left, top })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    const observer = new ResizeObserver(place)
    if (trigger.current) observer.observe(trigger.current)
    if (tooltip.current) observer.observe(tooltip.current)
    const visibilityObserver = new MutationObserver(place)
    visibilityObserver.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['hidden'] })
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
      observer.disconnect()
      visibilityObserver.disconnect()
    }
  }, [open, children])

  useEffect(() => {
    if (!open) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      if (hoverTimer.current !== null) clearTimeout(hoverTimer.current)
      if (closeTimer.current !== null) clearTimeout(closeTimer.current)
      hoverTimer.current = null
      closeTimer.current = null
      dismissed.current = true
      tooltipHovered.current = false
      setOpen(false)
      setPosition(null)
    }
    document.addEventListener('keydown', onEscape, true)
    return () => document.removeEventListener('keydown', onEscape, true)
  }, [open])

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={`help-trigger ${className}`.trim()}
        aria-label={`Help: ${label}`}
        aria-describedby={open ? id : undefined}
        onPointerEnter={() => {
          triggerHovered.current = true
          dismissed.current = false
          clearClose()
          clearHover()
          if (!focused.current) {
            hoverTimer.current = setTimeout(() => {
              hoverTimer.current = null
              if (triggerHovered.current && !dismissed.current) setOpen(true)
            }, 900)
          }
        }}
        onPointerLeave={() => {
          triggerHovered.current = false
          clearHover()
          scheduleClose()
        }}
        onFocus={() => {
          focused.current = true
          show()
        }}
        onBlur={() => {
          focused.current = false
          scheduleClose()
        }}
        onClick={(event) => {
          event.stopPropagation()
          show()
        }}
        onKeyDown={(event) => {
          event.stopPropagation()
          if (event.key === 'Escape') {
            event.preventDefault()
            dismiss()
          }
        }}
        onKeyUp={(event) => event.stopPropagation()}
      >
        <span aria-hidden="true">?</span>
      </button>
      {open && createPortal(
        <div
          ref={tooltip}
          id={id}
          role="tooltip"
          className="help-tooltip"
          style={{
            position: 'fixed',
            left: position?.left ?? 12,
            top: position?.top ?? 12,
            visibility: position ? 'visible' : 'hidden',
            maxWidth: 'min(320px, calc(100vw - 24px))',
            maxHeight: 'calc(100vh - 24px)',
            overflowY: 'auto',
          }}
          onPointerEnter={() => {
            tooltipHovered.current = true
            clearClose()
          }}
          onPointerLeave={() => {
            tooltipHovered.current = false
            scheduleClose()
          }}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          {children}
        </div>,
        document.body,
      )}
    </>
  )
}
