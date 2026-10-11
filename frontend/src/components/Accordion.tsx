import { type ReactNode, useEffect, useRef, useState } from 'react'

interface AccordionProps {
  id: string
  eyebrow: string
  title: string
  description?: string
  badges?: ReactNode
  children: ReactNode
  className?: string
}

/** A single-level, mounted accordion used for long settings editors. */
export default function Accordion({
  id,
  eyebrow,
  title,
  description,
  badges,
  children,
  className = '',
}: AccordionProps) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLElement | null>(null)
  const contentId = `${id}-content`

  useEffect(() => {
    const element = root.current
    if (!element) return
    const openFromNavigation = () => setOpen(true)
    element.addEventListener('accordion:open', openFromNavigation)
    return () => element.removeEventListener('accordion:open', openFromNavigation)
  }, [])

  return (
    <article
      ref={root}
      className={`card accordion-card ${className}`.trim()}
      id={id}
      data-accordion-id={id}
      data-accordion-open={open ? 'true' : 'false'}
    >
      <h2 className="accordion-header">
        <button
          type="button"
          className="accordion-trigger"
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((current) => !current)}
        >
          <span className="accordion-heading">
            <span className="label">{eyebrow}</span>
            <span className="accordion-title">{title}</span>
            {description && <span className="section-copy">{description}</span>}
          </span>
          <span className="accordion-trigger-side">
            {badges}
            <span className="accordion-caret" aria-hidden="true">v</span>
          </span>
        </button>
      </h2>
      <div id={contentId} className="accordion-content" hidden={!open}>
        {children}
      </div>
    </article>
  )
}
