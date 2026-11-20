import { useState, type FormEvent } from 'react'
import { waitForBridge, type LeaderboardPeriod, type LeaderboardSnapshot } from '../bridge'
import { leaderboardStates, useChatLeaderboards } from '../useChatLeaderboards'
import HelpTip from './HelpTip'

function LeaderboardTable({ title, period, detail, state }: {
  title: string
  period?: LeaderboardPeriod
  detail: string
  state: string
}) {
  return <article className="card leaderboard-card">
    <h2>{title}</h2>
    <p className="muted leaderboard-period"><span>{detail}</span><span>{state}{period?.partial && ' · Partial coverage'}</span></p>
    <div className="analytics-table leaderboard-table">
      <table aria-label={title}>
        <thead><tr><th scope="col">Place</th><th scope="col">Nickname</th><th scope="col">Messages</th></tr></thead>
        <tbody>{period?.rows.length ? period.rows.map((row, index) => <tr key={`${row.nickname}-${index}`}>
          <td>{row.place}</td><th scope="row">{row.nickname}</th><td>{String(row.messages)}</td>
        </tr>) : <tr><td colSpan={3}>{period ? 'No ranked messages yet.' : 'No results available.'}</td></tr>}</tbody>
      </table>
    </div>
  </article>
}

function LeaderboardExclusions({ data, onSave }: { data: LeaderboardSnapshot | null; onSave: (names: string[]) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [failed, setFailed] = useState(false)
  const saved = data?.exclusions.join(', ') ?? ''
  const names = draft ?? saved
  const dirty = names !== saved

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!data || !dirty || saving) return
    setSaving(true)
    setFeedback('')
    setFailed(false)
    try {
      const normalized = Array.from(new Set(names.split(/[\n,]+/)
        .map((name) => name.trim().replace(/^@/, '').toLowerCase()).filter(Boolean)))
      const result = await (await waitForBridge()).save_leaderboard_settings(data.channel_id, normalized)
      if (!result.ok) throw new Error(result.error || 'Could not save exclusions. Try again.')
      onSave(normalized)
      setDraft(null)
      setFeedback('Exclusions saved.')
    } catch (error) {
      setFailed(true)
      setFeedback(error instanceof Error ? error.message : 'Could not save exclusions. Try again.')
    } finally {
      setSaving(false)
    }
  }

  return <form className="card leaderboard-exclusions" onSubmit={(event) => void save(event)}>
    <div className="leaderboard-exclusions-row">
      <div className="form-field">
        <div className="custom-field-label">
          <label htmlFor="leaderboard-bots">Excluded bot names</label>
          <HelpTip label="How exclusions work">HeetKit automatically excludes its sending account. Verified accounts stay excluded after a rename.</HelpTip>
        </div>
        <input id="leaderboard-bots" aria-describedby="leaderboard-bots-format" value={names}
          onChange={(event) => setDraft(event.target.value === saved ? null : event.target.value)}
          maxLength={1350} disabled={saving || !data} />
      </div>
      <div className="leaderboard-actions">
        <button className="secondary" type="button" disabled={!dirty || saving} onClick={() => {
          setDraft(null); setFeedback('')
        }}>Cancel</button>
        <button className="primary" type="submit" disabled={!dirty || saving}>Save exclusions</button>
      </div>
    </div>
    <p className="muted" id="leaderboard-bots-format">Separate up to 50 Twitch logins with commas. Removing an exclusion shows the counts HeetKit kept and resumes counting for that account.</p>
    {feedback && <p role={failed ? 'alert' : 'status'} className={failed ? 'inline-error' : undefined}>{feedback}</p>}
  </form>
}

export default function ChatLeaderboards({ channel, countingEnabled }: { channel?: string | null; countingEnabled?: boolean }) {
  const [refresh, setRefresh] = useState(0)
  const { data, unavailable, setData } = useChatLeaderboards(channel, refresh)

  if (channel === undefined) return null
  const stream = data?.stream
  const date = stream ? new Date(stream.started_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) : null
  const streamDetail = date ? `${stream?.ends_at ? 'Last broadcast' : 'Broadcast'} · ${date}` : 'No confirmed broadcast'
  const states = leaderboardStates(channel, data, unavailable, countingEnabled)

  return <section id="analytics-chatters" className="leaderboard-section" aria-label="Chat leaderboards">
    <p className="muted leaderboard-time-basis">Times shown in UTC (GMT+0). Monthly reset: 1st at 00:00 UTC.</p>
    <div className="analytics-breakdowns leaderboard-row">
      <LeaderboardTable title="Stream top 10 chatters" period={stream} detail={streamDetail} state={states.stream} />
      <LeaderboardTable title="Monthly top 10 chatters" period={data?.month} detail={data?.month.period ?? 'Current calendar month'} state={states.base} />
    </div>
    <LeaderboardExclusions data={data} onSave={(exclusions) => {
      setData((current) => current && { ...current, exclusions })
      setRefresh((count) => count + 1)
    }} />
  </section>
}
