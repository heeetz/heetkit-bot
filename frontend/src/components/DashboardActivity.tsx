import { useEffect, useState } from 'react'
import { waitForBridge, type LogEntry } from '../bridge'
import { leaderboardStates, useChatLeaderboards } from '../useChatLeaderboards'
import { terminalCommandName, terminalCommandOutcome } from './LogEventSummary'
import { dashboard } from '../i18n/dashboard'
import { useCatalog, useI18n } from '../i18n/core'

const commandTime = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

export function RecentCommands({ onOpenLogs }: { onOpenLogs: () => void }) {
  const text = useCatalog(dashboard).commands
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
        <h2 id="dashboard-recent-commands">{text.title}</h2>
        <button type="button" className="dashboard-link" onClick={onOpenLogs}>{text.viewLogs}</button>
      </div>
      <div className="dashboard-command-table">
        <table aria-labelledby="dashboard-recent-commands">
          <thead><tr><th scope="col">{text.time}</th><th scope="col">{text.user}</th><th scope="col">{text.command}</th><th scope="col">{text.outcome}</th></tr></thead>
          <tbody>
            {entries?.map((entry) => {
              const outcome = terminalCommandOutcome(entry)
              return <tr key={entry.id}>
                <td><time dateTime={entry.timestamp} title={entry.timestamp}>{commandTime.format(new Date(entry.timestamp))}</time></td>
                <td className="dashboard-command-user">{typeof entry.context.username === 'string' ? entry.context.username : '—'}</td>
                <th scope="row">{terminalCommandName(entry)}</th>
                <td><span className={`dashboard-outcome ${outcome.tone ?? ''}`}><span aria-hidden="true" />{text.outcomes[outcome.key]}</span></td>
              </tr>
            })}
            {(!entries?.length || unavailable) && <tr><td colSpan={4} className="muted">
              {unavailable ? text.unavailable : entries ? text.empty : text.loading}
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
  const text = useCatalog(dashboard).stream
  const { number } = useI18n()
  const { data, unavailable } = useChatLeaderboards(channel)
  const { stream: state } = leaderboardStates(channel, data, unavailable)
  const stream = data?.stream?.ends_at === null ? data.stream : undefined
  const top = stream?.rows.slice(0, 3) ?? []
  const highest = Math.max(1, ...top.map(({ messages }) => messages))

  return (
    <article className="card dashboard-stream" aria-labelledby="dashboard-stream-activity">
      <div className="dashboard-card-heading">
        <h2 id="dashboard-stream-activity">{text.title}</h2>
        <button type="button" className="dashboard-link" onClick={onOpenAnalytics}>{text.viewAnalytics}</button>
      </div>
      <p className="muted">{state}{stream?.partial && text.partial}</p>
      {top.length > 0 ? <table aria-label={text.topChattersLabel}>
        <thead><tr><th scope="col" colSpan={2}>{text.topChatters}</th><th scope="col">{text.messages}</th></tr></thead>
        <tbody>{top.map(({ nickname, messages }, index) => <tr key={`${nickname}-${index}`}>
          <th scope="row">{nickname}</th>
          <td aria-hidden="true" className="dashboard-chatter-meter"><span><span style={{ width: `${messages / highest * 100}%` }} /></span></td>
          <td>{number(messages)}</td>
        </tr>)}</tbody>
      </table> : <p>{stream ? text.noRanked : text.noBroadcast}</p>}
    </article>
  )
}
