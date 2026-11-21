import { useState, type FormEvent } from 'react'
import { waitForBridge, type LeaderboardPeriod, type LeaderboardSnapshot } from '../bridge'
import { leaderboardStates, useChatLeaderboards } from '../useChatLeaderboards'
import HelpTip from './HelpTip'
import { analyticsText } from '../i18n/analytics'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'

function LeaderboardTable({ title, period, detail, state }: {
  title: string
  period?: LeaderboardPeriod
  detail: string
  state: string
}) {
  const text = useCatalog(analyticsText).leaderboards
  return <article className="card leaderboard-card">
    <h2>{title}</h2>
    <p className="muted leaderboard-period"><span>{detail}</span><span>{state}{period?.partial && text.partial}</span></p>
    <div className="analytics-table leaderboard-table">
      <table aria-label={title}>
        <thead><tr><th scope="col">{text.place}</th><th scope="col">{text.nickname}</th><th scope="col">{text.messages}</th></tr></thead>
        <tbody>{period?.rows.length ? period.rows.map((row, index) => <tr key={`${row.nickname}-${index}`}>
          <td>{row.place}</td><th scope="row">{row.nickname}</th><td>{String(row.messages)}</td>
        </tr>) : <tr><td colSpan={3}>{period ? text.noRanked : text.noResults}</td></tr>}</tbody>
      </table>
    </div>
  </article>
}

function LeaderboardExclusions({ data, onSave }: { data: LeaderboardSnapshot | null; onSave: (names: string[]) => void }) {
  const text = useCatalog(analyticsText).leaderboards
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
      if (!result.ok) throw new Error(result.error || catalogFor(analyticsText).leaderboards.saveFailed)
      onSave(normalized)
      setDraft(null)
      setFeedback(catalogFor(analyticsText).leaderboards.saved)
    } catch (error) {
      setFailed(true)
      setFeedback(error instanceof Error ? error.message : catalogFor(analyticsText).leaderboards.saveFailed)
    } finally {
      setSaving(false)
    }
  }

  return <form className="card leaderboard-exclusions" onSubmit={(event) => void save(event)}>
    <div className="leaderboard-exclusions-row">
      <div className="form-field">
        <div className="custom-field-label">
          <label htmlFor="leaderboard-bots">{text.excluded}</label>
          <HelpTip label={text.exclusionsHelpLabel}><ul>{text.exclusionsHelp.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip>
        </div>
        <input id="leaderboard-bots" aria-describedby="leaderboard-bots-format" value={names}
          onChange={(event) => setDraft(event.target.value === saved ? null : event.target.value)}
          maxLength={1350} disabled={saving || !data} />
      </div>
      <div className="leaderboard-actions">
        <button className="secondary" type="button" disabled={!dirty || saving} onClick={() => {
          setDraft(null); setFeedback('')
        }}>{text.cancel}</button>
        <button className="primary" type="submit" disabled={!dirty || saving}>{text.save}</button>
      </div>
    </div>
    <p className="muted" id="leaderboard-bots-format">{text.format}</p>
    {feedback && <p role={failed ? 'alert' : 'status'} className={failed ? 'inline-error' : undefined}>{feedback}</p>}
  </form>
}

export default function ChatLeaderboards({ channel, countingEnabled }: { channel?: string | null; countingEnabled?: boolean }) {
  const text = useCatalog(analyticsText).leaderboards
  const { fmt, dateTime } = useI18n()
  const [refresh, setRefresh] = useState(0)
  const { data, unavailable, setData } = useChatLeaderboards(channel, refresh)

  if (channel === undefined) return null
  const stream = data?.stream
  const date = stream ? dateTime(stream.started_at, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) : null
  const streamDetail = date ? fmt(stream?.ends_at ? text.lastBroadcast : text.broadcast, { date }) : text.noBroadcast
  const states = leaderboardStates(channel, data, unavailable, countingEnabled)

  return <section id="analytics-chatters" className="leaderboard-section" aria-label={text.label}>
    <p className="muted leaderboard-time-basis">{text.timeBasis}</p>
    <div className="analytics-breakdowns leaderboard-row">
      <LeaderboardTable title={text.streamTop} period={stream} detail={streamDetail} state={states.stream} />
      <LeaderboardTable title={text.monthlyTop} period={data?.month} detail={data?.month.period ?? text.currentMonth} state={states.base} />
    </div>
    <LeaderboardExclusions data={data} onSave={(exclusions) => {
      setData((current) => current && { ...current, exclusions })
      setRefresh((count) => count + 1)
    }} />
  </section>
}
