import { useEffect } from 'react'

interface FeedbackToastProps {
  error?: string
  notice?: string
  onDismiss: () => void
}

export default function FeedbackToast({ error = '', notice = '', onDismiss }: FeedbackToastProps) {
  const message = error || notice

  useEffect(() => {
    if (!notice || error) {
      return
    }
    const timer = window.setTimeout(onDismiss, 4500)
    return () => window.clearTimeout(timer)
  }, [error, notice, onDismiss])

  if (!message) {
    return null
  }

  return (
    <div
      className={`feedback-toast ${error ? 'error' : 'success'}`}
      role={error ? 'alert' : 'status'}
      aria-live={error ? 'assertive' : 'polite'}
    >
      <span>{message}</span>
      <button type="button" aria-label="Dismiss message" onClick={onDismiss}>×</button>
    </div>
  )
}
