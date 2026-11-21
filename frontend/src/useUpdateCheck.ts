import { useCallback, useEffect, useRef, useState } from 'react'
import { type UpdateCheckResponse, waitForBridge } from './bridge'
import { aboutText } from './i18n/about'
import { catalogFor } from './i18n/core'

export default function useUpdateCheck(checkOnStartup = false) {
  const [result, setResult] = useState<UpdateCheckResponse | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)
  const startupChecked = useRef(false)

  const check = useCallback(async (quiet = false) => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setResult(null)
    setError('')
    try {
      const api = await waitForBridge()
      const response = await api.check_for_updates()
      if (!response.ok) throw new Error(response.error ?? catalogFor(aboutText).checkFailed)
      setResult(response)
    } catch (reason) {
      if (!quiet) setError(reason instanceof Error ? reason.message : catalogFor(aboutText).checkFailed)
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (checkOnStartup && !startupChecked.current) {
      startupChecked.current = true
      void check(true)
    }
  }, [check, checkOnStartup])

  return { result, error, busy, check }
}
