import type { ReactNode } from 'react'

interface SwitchProps {
  checked: boolean
  disabled?: boolean
  onCheckedChange: (checked: boolean) => void
  children: ReactNode
  className?: string
  ariaLabel?: string
}

export default function Switch({
  checked,
  disabled = false,
  onCheckedChange,
  children,
  className = '',
  ariaLabel,
}: SwitchProps) {
  const classes = ['switch-control', className, disabled ? 'is-disabled' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <label className={classes}>
      <input
        className="switch-input"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(event) => onCheckedChange(event.target.checked)}
      />
      <span className="switch-track" aria-hidden="true">
        <span className="switch-thumb" />
      </span>
      <span className="switch-content">{children}</span>
    </label>
  )
}
