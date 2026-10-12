import { type ReactNode, type Ref, useId } from 'react'
import HelpTip from './HelpTip'

interface AccordionHeaderProps {
  title: ReactNode
  expanded: boolean
  contentId: string
  onToggle: () => void
  help?: ReactNode
  helpLabel?: string
  badges?: ReactNode
  metadata?: ReactNode
  ariaLabel?: string
  triggerRef?: Ref<HTMLButtonElement>
}

/** Full-row button with sibling help, so help never nests inside a button. */
export default function AccordionHeader({ title, expanded, contentId, onToggle, help,
  helpLabel, badges, metadata, ariaLabel, triggerRef }: AccordionHeaderProps) {
  const titleId = useId()
  return (
    <div className="accordion-header">
      <div className="accordion-heading">
        <span className="accordion-title" id={titleId}>
          {title}
          {help && <HelpTip label={helpLabel ?? (typeof title === 'string' ? title : 'Section')}>{help}</HelpTip>}
        </span>
        {metadata}
      </div>
      {badges && <div className="accordion-badges">{badges}</div>}
      <button type="button" className="accordion-trigger" ref={triggerRef}
        aria-expanded={expanded} aria-controls={contentId}
        aria-label={ariaLabel} aria-labelledby={ariaLabel ? undefined : titleId}
        onClick={onToggle}>
        <svg className="accordion-caret" width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="m5 7.5 5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  )
}
