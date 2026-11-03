import { useEffect, useRef, useState } from 'react'
import { type AnalyticsResponse, type AIBalanceResponse, waitForBridge } from '../bridge'
import { Select } from '../components/Select'
import Switch from '../components/Switch'
import HelpTip from '../components/HelpTip'
import Confirmation from '../components/Confirmation'
import './analytics.css'

const trends = [
  { value: 'command.attempts', label: 'Command attempts' },
  { value: 'command.success', label: 'Command successes' },
  { value: 'command.error', label: 'Command errors' },
  { value: 'users.new', label: 'Newly observed users' },
  { value: 'ai.requests', label: 'AI requests' },
  { value: 'ai.input_tokens', label: 'Reported input tokens' },
  { value: 'ai.output_tokens', label: 'Reported output tokens' },
  { value: 'ai.estimated_usd', label: 'Known spend subtotal (USD)' },
]
const count = (value = 0) => value.toLocaleString(undefined, { maximumFractionDigits: 0 })
const money = (value = 0) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD', minimumFractionDigits: 4, maximumFractionDigits: 4 })
const time = (value?: string | null) => value ? `${value.replace('T', ' ').replace(/(?:\.\d+)?(?:Z|\+00:00)$/, '')} UTC` : 'Unavailable'

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
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(180, entry.contentRect.width)))
    if (chart.current) observer.observe(chart.current)
    return () => observer.disconnect()
  }, [])
  const label = trends.find((item) => item.value === metric)!.label
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
  return <>
    <svg ref={chart} className="analytics-chart" viewBox={`0 0 ${width} 215`} role="img" aria-label={`${label} by UTC ${hourly ? 'hour' : 'day'}. Observed zeros are points; missing coverage and future hours are gaps. Values and coverage follow the trend selector.`}>
      <line x1="35" y1="180" x2={width - 35} y2="180" className="chart-axis" />
      <text x="35" y="18">{format(maximum)}</text>
      <text x="8" y="184">0</text>
      {data.series.map((row, index) => known[index] && <g key={row.day}>
        {index > 0 && known[index - 1] && <line x1={x(index - 1)} y1={y(data.series[index - 1].metrics[metric] || 0)} x2={x(index)} y2={y(row.metrics[metric] || 0)} className="chart-value" />}
        <circle cx={x(index)} cy={y(row.metrics[metric] || 0)} r="3" className="chart-point"><title>{row.day}: {format(row.metrics[metric])} UTC ({coverageState(row, index)})</title></circle>
      </g>)}
      <text x="0" y="205">{hourly ? '00:00 UTC' : data.start}</text><text x={width} y="205" textAnchor="end">{hourly ? '23:00 UTC' : data.end}</text>
    </svg>
    {selector}
    {metric === 'users.new' && <p className="muted">New retained presence records · prospective collection only <HelpTip label="Newly observed users">Newly observed in this channel in the bot’s retained database after successful eligible persistence. This is not Twitch’s first-time-chatter flag or lifetime unique viewers. A viewer can count again after their presence record expires. No historical backfill is invented.</HelpTip></p>}
    <details className="analytics-values"><summary>{hourly ? 'Hourly' : 'Daily'} values and coverage</summary><div className="analytics-table" tabIndex={0} role="region" aria-label="Trend values and coverage"><table><caption>{label} — UTC calendar {hourly ? 'hours' : 'days'}; observed values may cover only part of a bucket.</caption><thead><tr><th>{hourly ? 'Hour' : 'Day'}</th><th>Observed value</th><th>Coverage</th><th>App collection</th><th>Connected</th></tr></thead><tbody>{data.series.map((row, index) => <tr key={row.day}><th>{bucketLabel(row, hourly)}</th><td>{known[index] ? format(row.metrics[metric]) : 'Unknown'}</td><td>{coverageState(row, index)}</td><td>{Math.round(row.coverage_seconds / 60)} min</td><td>{Math.round((row.metrics['connection.seconds'] || 0) / 60)} min</td></tr>)}</tbody></table></div></details>
  </>
}

export default function AnalyticsPage() {
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
    <div className="ai-state-heading"><h2>Provider balance</h2><HelpTip label="Provider balance">Optional account-wide balance, independent of channel analytics and estimated spend. Refresh is on demand, cached for at least 60 seconds and has a bounded timeout. Last known balances can be stale. Keys stay in the backend.</HelpTip></div>
    <div className="balance-controls"><Select aria-label="Balance provider" value={provider} disabled={balanceBusy} onChange={(next) => { setProvider(next); setBalance(null) }} options={[{ value: 'deepseek', label: 'DeepSeek' }, { value: 'gemini', label: 'Gemini' }, { value: 'openai', label: 'OpenAI' }]} /><button className="secondary" aria-label="Refresh balance" disabled={balanceBusy || provider !== 'deepseek'} onClick={() => {
      setBalanceBusy(true)
      void (async () => {
        try { setBalance(await (await waitForBridge()).get_ai_balance(provider, true)) }
        catch { setBalance((previous) => ({ ok: false, provider, state: previous?.balances.length ? 'stale' : 'unavailable', balances: previous?.balances || [], updated_at: previous?.updated_at || null, error: 'Balance refresh unavailable. Retry later.' })) }
        finally { setBalanceBusy(false) }
      })()
    }}>{balanceBusy ? 'Refreshing…' : 'Refresh'}</button></div>
    <div role="status">{provider !== 'deepseek' ? <p>Unavailable — this provider has no supported balance API.</p> : !balance ? <p>Unavailable — refresh on demand.</p> : <>
      {balance.balances.map((item) => <div key={item.currency}><strong className="analytics-primary">{item.currency} {item.total_balance}</strong><HelpTip label={`${item.currency} balance details`}>Granted {item.granted_balance} · Topped up {item.topped_up_balance}</HelpTip></div>)}
      <p>{balance.state === 'stale' ? 'Stale — last known balance; refresh failed or cache expired.' : balance.state === 'available' ? 'Available' : 'Unavailable'} · Last updated: {time(balance.updated_at)}</p>
      {balance.error && <p className="inline-error">{balance.error}</p>}
    </>}</div>
  </article>
  return <div className="analytics-layout" aria-busy={busy}>
    <div className="analytics-toolbar"><label>UTC window<Select aria-label="UTC window" value={days} onChange={setDays} disabled={busy} options={[{ value: '1', label: 'Today' }, ...[7, 30, 60].map((n) => ({ value: String(n), label: `${n} days` }))]} /></label><button className="secondary" disabled={busy} onClick={() => void action()}>Refresh analytics</button></div>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {busy && !data && <p role="status">Loading analytics…</p>}
    {data && <article className="card analytics-trend">
      <Trend data={data} metric={metric} selector={<label className="analytics-trend-select">Trend<Select aria-label="Trend" value={metric} onChange={setMetric} options={trends} /></label>} />
      <p className="muted">{data.resolution === 'hour' ? `${data.end} · Hourly UTC observations. Earlier daily-only data has no hourly history.` : 'Daily UTC observations.'} Gaps are unknown; values reflect observed coverage.</p>
    </article>}
    <div className="analytics-cards">
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>Commands</h2><HelpTip label="Command totals">Observed window totals. Attempts include skips and do not equal successes plus errors. {count(total('command.skipped'))} skipped · {count(total('command.partial'))} partial · {count(total('command.uncertain'))} uncertain · {count(total('command.cancelled'))} cancelled · {count(total('command.incomplete'))} incomplete. Missing collection is never reconstructed.</HelpTip></div><strong className="analytics-primary">{value('command.attempts')} attempts</strong><p>{value('command.success')} success · {value('command.error')} errors</p></article>
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>Retained users now</h2><HelpTip label="Retained users now">Current channel presence snapshot, independent of the selected range or collection switch. Inactive records expire after 60 days. This is not a historical audience count.</HelpTip></div><strong className="analytics-primary">{data?.retained_users == null ? 'Unavailable' : count(data.retained_users)}</strong><p>Current channel snapshot</p></article>
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>AI usage</h2><HelpTip label="AI usage">{value('ai.attempts')} provider attempts. {value('ai.usage_unknown')} attempts with unknown/incomplete usage. Token subsets are not added twice. Spend remains available in the trend and provider breakdown; rates checked {data?.price_checked || 'unavailable'}. Playground is excluded.</HelpTip></div><strong className="analytics-primary">{value('ai.requests')} requests</strong><p>{!hasObservations || (total('ai.attempts') > 0 && !('ai.input_tokens' in totals)) ? 'Unknown' : count(total('ai.input_tokens'))} input / {!hasObservations || (total('ai.attempts') > 0 && !('ai.output_tokens' in totals)) ? 'Unknown' : count(total('ai.output_tokens'))} output tokens reported</p>{incomplete && <p className="muted">Incomplete — unknown usage, pricing or extra charges.</p>}</article>
      {balanceCard}
    </div>
    {data && <>
      {Object.keys(totals).length === 0 && <p role="status">No observed activity in this window. Missing coverage can also produce an empty window.</p>}
      <div className="analytics-breakdowns">
        <article className="card"><div className="ai-state-heading"><h2>Commands breakdown</h2></div><div className="analytics-table analytics-command-table" tabIndex={0} role="region" aria-label="Commands breakdown, scroll for more rows"><table><thead><tr><th>Command</th><th>Attempts</th><th>Success</th><th>Errors</th><th>Skipped</th></tr></thead><tbody>{data.commands.map((row) => <tr key={row.name}><th><span className="analytics-command-name">{row.label || 'Deleted or unavailable command'}</span><HelpTip label={`Command identity: ${row.label || 'unavailable command'}`}>Stable ID: {row.name}. Labels use the current configured name; historical names are not stored.</HelpTip></th>{['attempts', 'success', 'error', 'skipped'].map((key) => <td key={key}>{count(row.metrics[`command.${key}`])}</td>)}</tr>)}</tbody></table></div>{!data.commands.length && <p>No command observations.</p>}</article>
        <article className="card"><div className="ai-state-heading"><h2>Providers / models</h2><HelpTip label="Provider costs">Known USD subtotals are dated estimates, not invoices. Unknown usage, missing prices and extra charges can make them incomplete. Rates checked {data.price_checked}.</HelpTip></div><div className="analytics-table" tabIndex={0} role="region" aria-label="Providers and models"><table><thead><tr><th>Provider / model</th><th>Attempts</th><th>Errors</th><th>Known USD</th><th>Unknown usage / pricing</th></tr></thead><tbody>{data.providers.map((row) => <tr key={row.name}><th>{row.name}</th><td>{count(row.metrics['ai.attempts'])}</td><td>{count(row.metrics['ai.errors'])}</td><td>{'ai.estimated_usd' in row.metrics ? money(row.metrics['ai.estimated_usd']) : 'Unknown'}</td><td>{count(row.metrics['ai.usage_unknown'])} / {count(row.metrics['ai.price_missing'])}</td></tr>)}</tbody></table></div>{!data.providers.length && <p>No provider observations.</p>}</article>
      </div>
      <article className="card analytics-coverage">
        <div><div className="ai-state-heading"><h2>Collection & coverage</h2><HelpTip label="Analytics coverage">Private observed aggregates for the configured channel. Opt-outs, downtime, disabled collection and buffered crash losses are omitted. No historical chat is reconstructed. Reset clears every channel and Playground in this profile, including pending updates.</HelpTip></div><Switch checked={data.enabled} disabled={busy} ariaLabel="Collect analytics" onCheckedChange={(enabled) => void action(async () => (await waitForBridge()).configure_analytics(enabled))}><span>Collect analytics</span></Switch>{!data.enabled && <p>Collection disabled. Retained totals remain visible; disabled periods are missing.</p>}</div>
        <div><h3>Coverage</h3><p>{data.start} – {data.end} UTC</p><p>Data start: {time(data.metadata.data_start)}</p><p>{partial ? 'Partial window — missing observation coverage.' : 'Observed coverage only; today is in progress.'}</p><details><summary>Collection details</summary><p>Hourly data start: {time(data.metadata.hourly_start)} · Newly observed users start: {time(data.metadata.new_users_start)}</p><p>Pending: {data.pending} · Dropped: {data.dropped} · Write failures: {data.write_failures} · Unclean starts: {data.metadata.unclean_starts || '0'}</p><p>Last disabled: {time(data.metadata.last_disabled)} · Last enabled: {time(data.metadata.last_enabled)}</p><p>Snapshot: {time(data.as_of)}</p></details></div>
        <div className="analytics-operations"><h3>Status</h3>{!data.available && <p role="alert" className="inline-error">Analytics storage unavailable. Displayed values may be incomplete.</p>}{!data.channel_id && <p role="status">No configured channel ID. Channel analytics and retained-user coverage are unavailable.</p>}{!data.connected && <p>Disconnected — activity while disconnected is missing.</p>}{(data.dropped > 0 || data.write_failures > 0 || Number(data.metadata.unclean_starts) > 0) && <p role="alert" className="inline-error">Possible data loss · {data.dropped} dropped updates · {data.write_failures} write failures · {data.metadata.unclean_starts || '0'} unclean starts</p>}<button className="danger" disabled={busy} onClick={() => setReset(true)}>Reset all profile analytics</button></div>
      </article>
    </>}
    {reset && <Confirmation title="Reset all profile analytics?" description="Permanently clear aggregate totals for every channel and Playground in this profile, including pending updates. Personal AI memory, presence and opt-outs are unchanged. Operator-managed backups are separate copies." danger onCancel={() => setReset(false)} onConfirm={() => { setReset(false); void action(async () => (await waitForBridge()).reset_analytics(true)) }} />}
  </div>
}
