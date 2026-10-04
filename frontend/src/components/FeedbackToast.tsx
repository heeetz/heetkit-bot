import { useEffect, useRef } from 'react'

interface FeedbackToastProps {
  error?: string
  notice?: string
  onDismiss: () => void
}

export default function FeedbackToast({ error = '', notice = '', onDismiss }: FeedbackToastProps) {
  const message = error || notice
  const dismiss = useRef(onDismiss)

  useEffect(() => {
    dismiss.current = onDismiss
  }, [onDismiss])

  useEffect(() => {
    if (!message) {
      return
    }
    const timer = window.setTimeout(() => dismiss.current(), 10000)
    return () => window.clearTimeout(timer)
  }, [message])

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
