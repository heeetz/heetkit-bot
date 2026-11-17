import type { ReactNode } from 'react'
import HelpTip from './HelpTip'

export default function AIBehaviorSection({ id, title, description, badges, className = '', footer, children }: {
  id: string
  title: string
  description: string
  badges?: ReactNode
  className?: string
  footer?: ReactNode
  children: ReactNode
}) {
  return <div id={id} className={`ai-behavior-section ${className}`.trim()}>
    <div className="ai-behavior-fields">
      <div className="ai-behavior-section-heading">
        <div><h3>{title}</h3><HelpTip label={title}>{description}</HelpTip></div>
        {badges}
      </div>
      {children}
    </div>
    {footer && <div className="ai-behavior-footer">{footer}</div>}
  </div>
}
