import { useEffect, useState } from 'react'
import { waitForBridge, type LogEntry } from '../bridge'
import { leaderboardStates, useChatLeaderboards } from '../useChatLeaderboards'
import { terminalCommandName, terminalCommandOutcome } from './LogEventSummary'

export function RecentCommands({ onOpenLogs }: { onOpenLogs: () => void }) {
  const [entries, setEntries] = useState<LogEntry[] | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    let active = true
    let timer = 0
    const refresh = async () => {
      try {
        if (document.hidden) return
        const result = await (await waitForBridge()).get_recent_commands()
        if (result.ok === false) throw new Error(result.error)
        if (active) {
          setEntries(result.entries)
          setUnavailable(false)
        }
      } catch {
        if (active) setUnavailable(true)
      } finally {
        if (active) timer = window.setTimeout(() => void refresh(), 5000)
      }
    }
    void refresh()
    return () => { active = false; window.clearTimeout(timer) }
  }, [])

  return (
    <article className="card dashboard-commands" aria-labelledby="dashboard-recent-commands">
      <div className="dashboard-card-heading">
        <h2 id="dashboard-recent-commands">Recent commands</h2>
        <button type="button" className="dashboard-link" onClick={onOpenLogs}>View logs</button>
      </div>
      <div className="dashboard-command-table">
        <table aria-labelledby="dashboard-recent-commands">
          <thead><tr><th scope="col">Time (UTC)</th><th scope="col">Command</th><th scope="col">Outcome</th></tr></thead>
          <tbody>
            {entries?.map((entry) => {
              const outcome = terminalCommandOutcome(entry)
              return <tr key={entry.id}>
                <td><time dateTime={entry.timestamp} title={entry.timestamp}>{entry.timestamp.slice(11, 19)}</time></td>
                <th scope="row">{terminalCommandName(entry)}</th>
                <td><span className={`dashboard-outcome ${outcome.tone ?? ''}`}><span aria-hidden="true" />{outcome.label}</span></td>
              </tr>
            })}
            {(!entries?.length || unavailable) && <tr><td colSpan={3} className="muted">
              {unavailable ? 'Recent commands are temporarily unavailable.' : entries ? 'No completed commands yet.' : 'Loading recent commands…'}
            </td></tr>}
          </tbody>
        </table>
      </div>
    </article>
  )
}

export function StreamActivity({ channel, onOpenAnalytics }: {
  channel?: string | null
  onOpenAnalytics: () => void
}) {
  const { data, unavailable } = useChatLeaderboards(channel)
  const { stream: state } = leaderboardStates(channel, data, unavailable)
  const stream = data?.stream?.ends_at === null ? data.stream : undefined
  const top = stream?.rows.slice(0, 3) ?? []
  const highest = Math.max(1, ...top.map(({ messages }) => messages))

  return (
    <article className="card dashboard-stream" aria-labelledby="dashboard-stream-activity">
      <div className="dashboard-card-heading">
        <h2 id="dashboard-stream-activity">Stream activity</h2>
        <button type="button" className="dashboard-link" onClick={onOpenAnalytics}>View analytics</button>
      </div>
      <p className="muted">{state}{stream?.partial && ' · Partial coverage'}</p>
      {top.length > 0 ? <table aria-label="Current stream top chatters">
        <thead><tr><th scope="col" colSpan={2}>Top chatters</th><th scope="col">Messages</th></tr></thead>
        <tbody>{top.map(({ nickname, messages }, index) => <tr key={`${nickname}-${index}`}>
          <th scope="row">{nickname}</th>
          <td aria-hidden="true" className="dashboard-chatter-meter"><span><span style={{ width: `${messages / highest * 100}%` }} /></span></td>
          <td>{String(messages)}</td>
        </tr>)}</tbody>
      </table> : <p>{stream ? 'No ranked messages yet.' : 'No current broadcast results.'}</p>}
    </article>
  )
}
