import { type ReactNode, useEffect, useRef, useState } from 'react'
import AccordionHeader from './AccordionHeader'

interface AccordionProps {
  id: string
  title: string
  description?: string
  badges?: ReactNode
  children: ReactNode
  className?: string
}

/** A single-level, mounted accordion used for long settings editors. */
export default function Accordion({
  id,
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
      <AccordionHeader title={<span role="heading" aria-level={2}>{title}</span>}
        helpLabel={title} help={description} expanded={open} contentId={contentId}
        onToggle={() => setOpen((current) => !current)} badges={badges} ariaLabel={title} />
      <div id={contentId} className="accordion-content" hidden={!open}>
        {children}
      </div>
    </article>
  )
}
