import { useEffect, useState } from 'react'
import { waitForBridge, type LeaderboardSnapshot } from './bridge'
import { dashboard } from './i18n/dashboard'
import { catalogFor } from './i18n/core'

export function useChatLeaderboards(channel?: string | null, refresh = 0) {
  const [data, setData] = useState<LeaderboardSnapshot | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    if (channel == null) return
    let current = true
    let timer = 0
    const poll = async () => {
      try {
        if (document.hidden) return
        const result = await (await waitForBridge()).get_leaderboards()
        if (!result.ok || result.leaderboards?.channel_id !== channel) {
          throw new Error(catalogFor(dashboard).leaderboard.refreshFailed)
        }
        if (current) {
          setData(result.leaderboards)
          setUnavailable(false)
        }
      } catch {
        if (current) setUnavailable(true)
      } finally {
        if (current) timer = window.setTimeout(() => void poll(), 5000)
      }
    }
    void poll()
    return () => { current = false; window.clearTimeout(timer) }
  }, [channel, refresh])

  return { data: data?.channel_id === channel ? data : null, unavailable, setData }
}

export function leaderboardStates(channel: string | null | undefined, data: LeaderboardSnapshot | null,
  unavailable: boolean, countingEnabled = data?.counting_enabled) {
  const text = catalogFor(dashboard).leaderboard
  const unavailableState = channel === null ? text.chooseChannel
    : unavailable ? text.unavailable : !data ? text.loading : ''
  const paused = countingEnabled === false ? text.paused : ''
  const inactive = [paused, unavailableState].filter(Boolean).join(' · ')
  const base = inactive || (data?.connected ? text.collecting : text.disconnected)
  const stream = inactive || (!data?.connected ? base : data.stream_status === 'live' ? text.collecting
    : data.stream_status === 'offline' ? text.offline : text.unknown)
  return { base, stream }
}
