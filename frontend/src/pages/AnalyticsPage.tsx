import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { type AnalyticsResponse, type AIBalanceResponse, waitForBridge } from '../bridge'
import ChatLeaderboards from '../components/ChatLeaderboards'
import { Select } from '../components/Select'
import Switch from '../components/Switch'
import HelpTip from '../components/HelpTip'
import Confirmation from '../components/Confirmation'
import './analytics.css'

const trends = [
  { value: 'command.attempts', label: 'Command attempts', unit: 'command attempt' },
  { value: 'command.success', label: 'Command successes', unit: 'command success', plural: 'command successes' },
  { value: 'command.error', label: 'Command errors', unit: 'command error' },
  { value: 'users.new', label: 'Newly observed users', unit: 'newly observed user' },
  { value: 'ai.requests', label: 'AI requests', unit: 'AI request' },
  { value: 'ai.input_tokens', label: 'Reported input tokens', unit: 'reported input token' },
  { value: 'ai.output_tokens', label: 'Reported output tokens', unit: 'reported output token' },
  { value: 'ai.estimated_usd', label: 'Known spend subtotal (USD)' },
]
const count = (value = 0) => value.toLocaleString(undefined, { maximumFractionDigits: 0 })
const money = (value = 0) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD', minimumFractionDigits: 4, maximumFractionDigits: 4 })
const time = (value?: string | null) => value ? `${value.replace('T', ' ').replace(/(?:\.\d+)?(?:Z|\+00:00)$/, '')} UTC` : 'Unavailable'
const dataSinceTime = (value?: string | null) => value ? `${value.replace('T', ' ').replace(/(?:Z|\+00:00)$/, '')} UTC` : 'Unavailable'

type Bucket = AnalyticsResponse['series'][number]
const bucketStart = (row: Bucket) => Date.parse(row.day.includes('T') ? row.day : row.day + 'T00:00:00Z')
const bucketLabel = (row: Bucket, hourly: boolean) => hourly ? `${row.day.slice(11, 16)} UTC` : row.day
function observed(row: Bucket, metric: string, data: AnalyticsResponse) {
  if (bucketStart(row) > Date.parse(data.as_of)) return false
  if (metric in row.metrics) return true
  const coverage = metric === 'users.new' ? row.new_users_coverage_seconds : row.coverage_seconds
  if (!(coverage > 0 && row.metrics['connection.seconds'] > 0)) return false
  if (['ai.input_tokens', 'ai.output_tokens', 'ai.estimated_usd'].includes(metric) && row.metrics['ai.attempts'] > 0) return false
  return true
}
function Trend({ data, metric, selector }: { data: AnalyticsResponse; metric: string; selector: React.ReactNode }) {
  const chart = useRef<SVGSVGElement>(null)
  const [width, setWidth] = useState(760)
  const [selected, setSelected] = useState<number | null>(null)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(180, entry.contentRect.width)))
    if (chart.current) observer.observe(chart.current)
    return () => observer.disconnect()
  }, [])
  const trend = trends.find((item) => item.value === metric)!
  const { label } = trend
  const hourly = data.resolution === 'hour'
  const known = data.series.map((row) => observed(row, metric, data))
  const maximum = Math.max(1, ...data.series.map((row) => row.metrics[metric] || 0))
  const x = (index: number) => 35 + (index / Math.max(1, data.series.length - 1)) * (width - 70)
  const y = (value: number) => 180 - value / maximum * 150
  const format = (value = 0) => metric === 'ai.estimated_usd' ? money(value) : count(value)
  const coverageState = (row: Bucket, index: number) => {
    if (bucketStart(row) > Date.parse(data.as_of)) return 'Future hour'
    if (!known[index]) return 'Unknown — collection or reporting gap'
    const seconds = metric === 'users.new' ? row.new_users_coverage_seconds : row.coverage_seconds
    const elapsed = Math.min(hourly ? 3600 : 86400, (Date.parse(data.as_of) - bucketStart(row)) / 1000)
    return seconds < elapsed - 5 ? 'Partial observation' : 'Observed'
  }
  const bucket = selected === null ? undefined : data.series[selected]
  const value = bucket?.metrics[metric] ?? 0
  const tooltipValue = !trend.unit
    ? `${value.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 12 })} USD estimated spend`
    : `${count(value)} ${value === 1 ? trend.unit : trend.plural ?? `${trend.unit}s`}`
  const selectPointer = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const localX = (event.clientX - bounds.left) * width / bounds.width
    const index = Math.round((localX - x(0)) / (width - 70) * (data.series.length - 1))
    setSelected(Math.max(0, Math.min(data.series.length - 1, index)))
  }
  return <>
    <div className="analytics-plot">
      <svg ref={chart} className="analytics-chart" viewBox={`0 0 ${width} 215`} role="img" aria-label={`${label} by UTC ${hourly ? 'hour' : 'day'}. Observed zeros are points; missing coverage and future hours are gaps. Values and coverage follow the trend selector. Use the arrow keys to inspect values.`}
        tabIndex={data.series.length ? 0 : undefined}
        onPointerMove={(event) => { if (event.pointerType === 'mouse') selectPointer(event) }}
        onPointerUp={(event) => { if (event.pointerType !== 'mouse') selectPointer(event) }}
        onPointerLeave={(event) => { if (event.pointerType === 'mouse') setSelected(null) }}
        onBlur={() => setSelected(null)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setSelected(null)
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault()
            const delta = event.key === 'ArrowLeft' ? -1 : 1
            setSelected((index) => index === null ? (delta > 0 ? 0 : data.series.length - 1)
              : Math.max(0, Math.min(data.series.length - 1, index + delta)))
          }
        }}>
        <line x1="35" y1="180" x2={width - 35} y2="180" className="chart-axis" />
        <text x="35" y="18">{format(maximum)}</text>
        <text x="8" y="184">0</text>
        {data.series.map((row, index) => known[index] && <g key={row.day}>
          {index > 0 && known[index - 1] && <line x1={x(index - 1)} y1={y(data.series[index - 1].metrics[metric] || 0)} x2={x(index)} y2={y(row.metrics[metric] || 0)} className="chart-value" />}
          <circle cx={x(index)} cy={y(row.metrics[metric] || 0)} r="3" className="chart-point" />
        </g>)}
        {bucket && selected !== null && <g>
          <line x1={x(selected)} x2={x(selected)} y1="23" y2="180" className="chart-selection" />
          {known[selected] && <circle cx={x(selected)} cy={y(value)} r="5" className="chart-point" />}
        </g>}
        <text x="0" y="205">{hourly ? '00:00 UTC' : data.start}</text><text x={width} y="205" textAnchor="end">{hourly ? '23:00 UTC' : data.end}</text>
      </svg>
      <div aria-live="polite">
        {bucket && selected !== null && <div role="tooltip" className="chart-tooltip" style={{ '--bucket-position': `${x(selected) / width * 100}%`,
            top: known[selected] && y(value) < 72 ? 68 : 8 } as React.CSSProperties}>
          <strong>{known[selected] ? tooltipValue : `${label} unavailable`}</strong>
          <span>{bucketLabel(bucket, hourly)}</span>
        </div>}
      </div>
    </div>
    {selector}
    {metric === 'users.new' && <p className="muted">Counts new viewer records as HeetKit saves them for this channel.{' '}
      <HelpTip label="Who counts">A viewer can count again after their record expires, even if they have chatted here before. The trend starts when HeetKit began collecting this metric.</HelpTip></p>}
    <details className="analytics-values"><summary>{hourly ? 'Hourly' : 'Daily'} values and coverage</summary><div className="analytics-table" tabIndex={0} role="region" aria-label="Trend values and coverage"><table><caption>{label} — UTC calendar {hourly ? 'hours' : 'days'}; observed values may cover only part of a bucket.</caption><thead><tr><th>{hourly ? 'Hour' : 'Day'}</th><th>Observed value</th><th>Coverage</th><th>App collection</th><th>Connected</th></tr></thead><tbody>{data.series.map((row, index) => <tr key={row.day}><th>{bucketLabel(row, hourly)}</th><td>{known[index] ? format(row.metrics[metric]) : 'Unknown'}</td><td>{coverageState(row, index)}</td><td>{Math.round(row.coverage_seconds / 60)} min</td><td>{Math.round((row.metrics['connection.seconds'] || 0) / 60)} min</td></tr>)}</tbody></table></div></details>
  </>
}

export default function AnalyticsPage({ leaderboardChannel }: { leaderboardChannel?: string | null }) {
  const [days, setDays] = useState('7')
  const [metric, setMetric] = useState('command.attempts')
  const [data, setData] = useState<AnalyticsResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reset, setReset] = useState(false)
  const [provider, setProvider] = useState('deepseek')
  const [balance, setBalance] = useState<AIBalanceResponse | null>(null)
  const [balanceBusy, setBalanceBusy] = useState(false)
  useEffect(() => {
    if (!balance || balance.state !== 'available' || !balance.updated_at) return
    const timer = window.setTimeout(() => setBalance((current) => current?.state === 'available'
      ? { ...current, state: 'stale' } : current), Math.max(0, Date.parse(balance.updated_at) + 60000 - Date.now()))
    return () => window.clearTimeout(timer)
  }, [balance])
  const load = async (windowDays: number) => {
    const response = await (await waitForBridge()).get_analytics(windowDays)
    if (!response.ok) throw new Error(response.error || 'Analytics unavailable.')
    return response
  }
  useEffect(() => {
    let current = true
    setBusy(true); setError(''); setData(null)
    void load(Number(days)).then((response) => { if (current) setData(response) }).catch(() => {
      if (current) setError('Could not load analytics. Check the connection and retry.')
    }).finally(() => { if (current) setBusy(false) })
    return () => { current = false }
  }, [days])
  const action = async (operation?: () => Promise<{ ok: boolean; error?: string }>) => {
    setBusy(true); setError('')
    try {
      if (operation) { const result = await operation(); if (!result.ok) throw new Error(result.error || 'Analytics operation failed.') }
      setData(await load(Number(days)))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Analytics unavailable.') }
    finally { setBusy(false) }
  }
  const totals = data?.totals || {}
  const total = (key: string) => totals[key] || 0
  const incomplete = total('ai.estimate_incomplete') > 0 || total('ai.usage_unknown') > 0 || total('ai.price_missing') > 0
  const hasObservations = Boolean(data?.available && data.channel_id && (Object.keys(totals).length || data.series.some((row) => row.coverage_seconds > 0 && row.metrics['connection.seconds'] > 0)))
  const value = (key: string) => hasObservations ? count(total(key)) : 'Unknown'
  const partial = data && data.series.some((row) => {
    const elapsed = Math.min(data.resolution === 'hour' ? 3600 : 86400, (Date.parse(data.as_of) - bucketStart(row)) / 1000)
    return elapsed > 0 && row.coverage_seconds < elapsed - 5
  })
  const balanceCard = <article className="card analytics-summary analytics-balance">
    <div className="ai-state-heading"><h2>Provider balance</h2><HelpTip label="Balance refresh">The balance covers your whole provider account. HeetKit keeps the last reported balance when a refresh fails. Requests within 60 seconds may show the same balance.</HelpTip></div>
    <div className="balance-controls"><Select aria-label="Balance provider" value={provider} disabled={balanceBusy} onChange={(next) => { setProvider(next); setBalance(null) }} options={[{ value: 'deepseek', label: 'DeepSeek' }, { value: 'gemini', label: 'Gemini' }, { value: 'openai', label: 'OpenAI' }]} /><button className="secondary" aria-label="Refresh balance" disabled={balanceBusy || provider !== 'deepseek'} onClick={() => {
      setBalanceBusy(true)
      void (async () => {
        try { setBalance(await (await waitForBridge()).get_ai_balance(provider, true)) }
        catch { setBalance((previous) => ({ ok: false, provider, state: previous?.balances.length ? 'stale' : 'unavailable', balances: previous?.balances || [], updated_at: previous?.updated_at || null, error: 'Balance refresh unavailable. Retry later.' })) }
        finally { setBalanceBusy(false) }
      })()
    }}>{balanceBusy ? 'Refreshing…' : 'Refresh'}</button></div>
    <div role="status">{provider !== 'deepseek' ? <p>Unavailable — this provider has no supported balance API.</p> : !balance ? <p>Unavailable — refresh on demand.</p> : <>
      {balance.balances.map((item) => <div key={item.currency}><strong className="analytics-primary">{item.currency} {item.total_balance}</strong>
        <p>Granted {item.granted_balance} · Topped up {item.topped_up_balance}</p></div>)}
      <p>{balance.state === 'stale' ? 'Stale — last known balance; refresh failed or cache expired.' : balance.state === 'available' ? 'Available' : 'Unavailable'} · Last updated: {time(balance.updated_at)}</p>
      {balance.error && <p className="inline-error">{balance.error}</p>}
    </>}</div>
  </article>
  return <div className="analytics-layout" aria-busy={busy}>
    <div className="analytics-toolbar"><label>UTC window<Select aria-label="UTC window" value={days} onChange={setDays} disabled={busy} options={[{ value: '1', label: 'Today' }, ...[7, 30, 60].map((n) => ({ value: String(n), label: `${n} days` }))]} /></label><button className="secondary" disabled={busy} onClick={() => void action()}>Refresh analytics</button></div>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {busy && !data && <p role="status">Loading analytics…</p>}
    {data && <article className="card analytics-trend" id="analytics-trends">
      <Trend key={`${data.resolution}:${data.start}:${data.end}`} data={data} metric={metric} selector={<label className="analytics-trend-select">Trend<Select aria-label="Trend" value={metric} onChange={setMetric} options={trends} /></label>} />
      <p className="muted">{data.resolution === 'hour' ? `${data.end} · Hourly totals (UTC).` : 'Daily totals (UTC).'} Gaps show times with missing data.</p>
    </article>}
    <div className="analytics-cards">
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>Commands</h2><HelpTip label="Other outcomes">
        <p>Attempts include commands that were skipped, such as when a cooldown was active.</p>
        <p>{value('command.skipped')} skipped · {value('command.partial')} partial · {value('command.uncertain')} uncertain · {value('command.cancelled')} cancelled · {value('command.incomplete')} incomplete</p>
      </HelpTip></div><strong className="analytics-primary">{value('command.attempts')} attempts</strong><p>{value('command.success')} successes · {value('command.error')} errors</p></article>
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>Retained users now</h2><HelpTip label="How long records last">Viewer records expire after 60 days of inactivity. The selected date range and Collect analytics switch do not change this count.</HelpTip></div><strong className="analytics-primary">{data?.retained_users == null ? 'Unavailable' : count(data.retained_users)}</strong><p>Viewer records for this channel now</p></article>
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>AI usage</h2><HelpTip label="Usage details">
        <p>{value('ai.attempts')} provider attempts. Usage is unknown or incomplete for {value('ai.usage_unknown')} attempts.</p>
        <p>This card covers Twitch chat. See Providers / models for estimated costs.</p>
      </HelpTip></div><strong className="analytics-primary">{value('ai.requests')} requests</strong><p>{!hasObservations || (total('ai.attempts') > 0 && !('ai.input_tokens' in totals)) ? 'Unknown' : count(total('ai.input_tokens'))} input / {!hasObservations || (total('ai.attempts') > 0 && !('ai.output_tokens' in totals)) ? 'Unknown' : count(total('ai.output_tokens'))} output tokens reported</p>{incomplete && <p className="muted">Incomplete — unknown usage, pricing or extra charges.</p>}</article>
      {balanceCard}
    </div>
    <ChatLeaderboards key={leaderboardChannel ?? ''} channel={leaderboardChannel} countingEnabled={data?.count_chat_messages} />
    {data && <>
      {Object.keys(totals).length === 0 && <p role="status">No observed activity in this window. Missing coverage can also produce an empty window.</p>}
      <div className="analytics-breakdowns" id="analytics-breakdown">
        <article className="card"><div className="ai-state-heading"><h2>Commands breakdown</h2><HelpTip label="How attempts are counted">Each row uses the current command name and includes attempts through its aliases. Zero means HeetKit recorded no attempts in the selected dates. Activity during gaps is unknown.</HelpTip></div><div className="analytics-table analytics-command-table" tabIndex={0} role="region" aria-label="Commands breakdown, scroll for more rows"><table><thead><tr><th>Command</th><th>Attempts</th><th>Success</th><th>Errors</th><th>Skipped</th></tr></thead><tbody>{data.commands.map((row) => <tr key={row.name}><th><span className={`analytics-command-name${!row.label || row.label.startsWith('Deleted or unavailable command') ? ' analytics-command-unavailable' : ''}`} title={row.label || `Deleted or unavailable command (${row.name})`}>{row.label || `Deleted or unavailable command (${row.name})`}</span></th>{['attempts', 'success', 'error', 'skipped'].map((key) => <td key={key}>{data.available && data.channel_id ? count(row.metrics[`command.${key}`]) : 'Unavailable'}</td>)}</tr>)}</tbody></table></div>{!data.commands.length && <p>No commands configured or recorded in this range.</p>}</article>
        <article className="card"><div className="ai-state-heading"><h2>Providers / models</h2><HelpTip label="How costs are estimated">The estimate uses reported usage and known rates. Missing usage, missing rates and extra fees can make it incomplete. Rates checked {data.price_checked}.</HelpTip></div><div className="analytics-table" tabIndex={0} role="region" aria-label="Providers and models"><table><thead><tr><th>Provider / model</th><th>Attempts</th><th>Errors</th><th>Estimated USD</th><th>Unknown usage / pricing</th></tr></thead><tbody>{data.providers.map((row) => <tr key={row.name}><th>{row.name}</th><td>{count(row.metrics['ai.attempts'])}</td><td>{count(row.metrics['ai.errors'])}</td><td>{'ai.estimated_usd' in row.metrics ? money(row.metrics['ai.estimated_usd']) : 'Unknown'}</td><td>{count(row.metrics['ai.usage_unknown'])} / {count(row.metrics['ai.price_missing'])}</td></tr>)}</tbody></table></div>{!data.providers.length && <p>No provider observations.</p>}</article>
      </div>
      <article className="card analytics-coverage" id="analytics-collection">
        <div className="analytics-coverage-heading">
          <h2>Collection & coverage</h2>
          {(data.dropped > 0 || data.write_failures > 0 || Number(data.metadata.unclean_starts) > 0) && <p role="alert" className="analytics-data-loss">Possible data loss</p>}
        </div>
        <div className="analytics-coverage-zones">
          <div className="analytics-collection" role="group" aria-label="Collection" aria-describedby="analytics-save-timing">
            <div>
              <Switch checked={data.enabled} disabled={busy} ariaLabel="Collect analytics" ariaDescribedBy="collect-analytics-effect" onCheckedChange={(enabled) => void action(async () => (await waitForBridge()).configure_analytics(enabled))}>Collect analytics</Switch>
              <p className="muted" id="collect-analytics-effect">Records activity totals.</p>
            </div>
            <div>
              <Switch checked={data.count_chat_messages} disabled={busy} ariaLabel="Count chat messages" ariaDescribedBy="count-chat-effect" onCheckedChange={(enabled) => void action(async () => (await waitForBridge()).configure_leaderboard_counting(enabled))}>Count chat messages</Switch>
              <p className="muted" id="count-chat-effect">Pausing keeps existing totals.</p>
            </div>
            <p className="muted analytics-collection-note" id="analytics-save-timing">Changes save immediately.</p>
          </div>
          <section className="analytics-coverage-summary" aria-label="Coverage">
            <p>{!data.available || !data.channel_id ? 'Coverage unavailable' : partial ? 'Partial coverage' : 'Observed coverage'}{!data.enabled && ' · Collection paused'}</p>
            <p className="muted">{data.start} – {data.end} UTC</p>
          </section>
          {!data.available && <p role="alert" className="inline-error">Analytics storage unavailable. Displayed values may be incomplete.</p>}
          {!data.channel_id && <p role="status">No configured channel ID. Channel analytics and retained-user coverage are unavailable.</p>}
        </div>
        <div className="analytics-coverage-footer">
        <details className="analytics-collection-details"><summary>Collection details</summary><dl>
          <div><dt>Data since</dt><dd>{dataSinceTime(data.metadata.data_start)}</dd></div>
          <div><dt>Hourly data since</dt><dd>{time(data.metadata.hourly_start)}</dd></div>
          <div><dt>Newly observed users since</dt><dd>{time(data.metadata.new_users_start)}</dd></div>
          <div><dt>Connection</dt><dd>{data.connected ? 'Connected' : 'Disconnected · Coverage gap'}</dd></div>
          <div><dt>Channel</dt><dd>{data.channel_id || 'Unavailable · No configured channel ID'}</dd></div>
          <div><dt>Storage</dt><dd>{data.available ? 'Available' : 'Unavailable · Displayed values may be incomplete'}</dd></div>
          <div><dt>Pending updates</dt><dd>{data.pending}</dd></div>
          <div><dt>Dropped updates</dt><dd>{data.dropped}</dd></div>
          <div><dt>Write failures</dt><dd>{data.write_failures}</dd></div>
          <div><dt>Unclean starts</dt><dd>{data.metadata.unclean_starts || '0'}</dd></div>
          <div><dt>Last disabled</dt><dd>{time(data.metadata.last_disabled)}</dd></div>
          <div><dt>Last enabled</dt><dd>{time(data.metadata.last_enabled)}</dd></div>
          <div><dt>Snapshot</dt><dd>{time(data.as_of)}</dd></div>
        </dl></details>
          <button className="analytics-reset" disabled={busy} onClick={() => setReset(true)}>Reset all profile analytics</button>
        </div>
      </article>
    </>}
    {reset && <Confirmation title="Reset all profile analytics?" description="Permanently clear aggregate totals for every channel and Playground in this profile, including pending updates. Personal AI memory, presence and opt-outs are unchanged. Operator-managed backups are separate copies." danger onCancel={() => setReset(false)} onConfirm={() => { setReset(false); void action(async () => (await waitForBridge()).reset_analytics(true)) }} />}
  </div>
}
