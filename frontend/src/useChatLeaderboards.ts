import { useEffect, useState } from 'react'
import { waitForBridge, type LeaderboardSnapshot } from './bridge'

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
          throw new Error('Could not refresh leaderboards.')
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
  const unavailableState = channel === null ? 'Choose a Twitch channel'
    : unavailable ? 'Temporarily unavailable' : !data ? 'Loading…' : ''
  const paused = countingEnabled === false ? 'Counting paused' : ''
  const inactive = [paused, unavailableState].filter(Boolean).join(' · ')
  const base = inactive || (data?.connected ? 'Collecting' : 'Disconnected')
  const stream = inactive || (!data?.connected ? base : data.stream_status === 'live' ? 'Collecting'
    : data.stream_status === 'offline' ? 'Offline' : 'Stream status unknown')
  return { base, stream }
}
