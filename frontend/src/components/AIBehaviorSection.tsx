import type { ReactNode } from 'react'
import HelpTip from './HelpTip'

export default function AIBehaviorSection({ id, title, helpLabel, description, badges, className = '', footer, children }: {
  id: string
  title: string
  helpLabel: string
  description: ReactNode
  badges?: ReactNode
  className?: string
  footer?: ReactNode
  children: ReactNode
}) {
  return <div id={id} className={`ai-behavior-section ${className}`.trim()}>
    <div className="ai-behavior-fields">
      <div className="ai-behavior-section-heading">
        <div><h3>{title}</h3><HelpTip label={helpLabel}>{description}</HelpTip></div>
        {badges}
      </div>
      {children}
    </div>
    {footer && <div className="ai-behavior-footer">{footer}</div>}
  </div>
}
