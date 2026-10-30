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
  { value: 'ai.requests', label: 'AI requests' },
  { value: 'ai.input_tokens', label: 'Reported input tokens' },
  { value: 'ai.output_tokens', label: 'Reported output tokens' },
  { value: 'ai.estimated_usd', label: 'Known spend subtotal (USD)' },
]
const count = (value = 0) => value.toLocaleString(undefined, { maximumFractionDigits: 0 })
const money = (value = 0) => value.toLocaleString(undefined, { style: 'currency', currency: 'USD', minimumFractionDigits: 4, maximumFractionDigits: 4 })
const time = (value?: string | null) => value ? `${value.replace('T', ' ').replace(/(?:\.\d+)?(?:Z|\+00:00)$/, '')} UTC` : 'Unavailable'

function Trend({ data, metric }: { data: AnalyticsResponse; metric: string }) {
  const chart = useRef<SVGSVGElement>(null)
  const [width, setWidth] = useState(760)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(180, entry.contentRect.width)))
    if (chart.current) observer.observe(chart.current)
    return () => observer.disconnect()
  }, [])
  const label = trends.find((item) => item.value === metric)!.label
  const known = data.series.map((row) => Object.keys(row.metrics).length > 0)
  const maximum = Math.max(1, ...data.series.map((row) => row.metrics[metric] || 0))
  const x = (index: number) => 35 + (index / Math.max(1, data.series.length - 1)) * (width - 70)
  const y = (value: number) => 180 - value / maximum * 150
  return <>
    <svg ref={chart} className="analytics-chart" viewBox={`0 0 ${width} 215`} role="img" aria-label={`${label} by UTC day. Missing coverage is shown as gaps; daily values follow in the data table.`}>
      <line x1="35" y1="180" x2={width - 35} y2="180" className="chart-axis" />
      <text x="35" y="18">{metric === 'ai.estimated_usd' ? money(maximum) : count(maximum)}</text>
      {data.series.map((row, index) => known[index] && <g key={row.day}>
        {index > 0 && known[index - 1] && <line x1={x(index - 1)} y1={y(data.series[index - 1].metrics[metric] || 0)} x2={x(index)} y2={y(row.metrics[metric] || 0)} className="chart-value" />}
        <circle cx={x(index)} cy={y(row.metrics[metric] || 0)} r="3" className="chart-point"><title>{row.day}: {row.metrics[metric] || 0} (observed only)</title></circle>
      </g>)}
      <text x="0" y="205">{data.start}</text><text x={width} y="205" textAnchor="end">{data.end}</text>
    </svg>
    <details><summary>Daily values and coverage</summary><div className="analytics-table"><table><caption>{label} — UTC calendar days</caption><thead><tr><th>Day</th><th>Observed value</th><th>App coverage</th><th>Connected</th></tr></thead><tbody>{data.series.map((row, index) => <tr key={row.day}><th>{row.day}</th><td>{known[index] ? metric === 'ai.estimated_usd' ? money(row.metrics[metric]) : count(row.metrics[metric]) : 'Unknown'}</td><td>{Math.round(row.coverage_seconds / 60)} min</td><td>{Math.round((row.metrics['connection.seconds'] || 0) / 60)} min</td></tr>)}</tbody></table></div></details>
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
  const partial = data && (!data.metadata.data_start || data.metadata.data_start.slice(0, 10) >= data.start
    || data.series.some((row) => row.coverage_seconds < Math.min(86400, (Date.parse(data.as_of) - Date.parse(row.day + 'T00:00:00Z')) / 1000) - 5))
  return <div className="analytics-layout" aria-busy={busy}>
    <div className="analytics-toolbar"><label>UTC window<Select aria-label="UTC window" value={days} onChange={setDays} disabled={busy} options={[{ value: '1', label: 'Today' }, ...[7, 30, 60].map((n) => ({ value: String(n), label: `${n} days` }))]} /></label><button className="secondary" disabled={busy} onClick={() => void action()}>Refresh analytics</button></div>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {busy && !data && <p role="status">Loading analytics…</p>}
    {data && <>
      <article className="card analytics-coverage">
        <div className="ai-state-heading"><h2>Collection & coverage</h2><HelpTip label="Analytics coverage">Private observed aggregates for the configured channel. Opt-outs, downtime, disabled collection and buffered crash losses are omitted. Historical chat is never reconstructed. Command attempts include skips, so attempts do not equal successes plus errors. Playground usage is separate and excluded here. Retained users is the current presence snapshot, independent of this window.</HelpTip></div>
        <Switch checked={data.enabled} disabled={busy} ariaLabel="Collect analytics" onCheckedChange={(enabled) => void action(async () => (await waitForBridge()).configure_analytics(enabled))}><span>Collect analytics</span></Switch>
        {!data.available && <p role="alert" className="inline-error">Analytics storage unavailable. Displayed values may be incomplete.</p>}
        {!data.enabled && <p>Collection disabled. Retained totals remain visible; disabled periods are missing.</p>}
        {!data.channel_id && <p role="status">No configured channel ID. Channel analytics and retained-user coverage are unavailable.</p>}
        {!data.connected && <p>Disconnected — activity while disconnected is missing.</p>}
        <p>{data.start} – {data.end} UTC · Profile data start: {time(data.metadata.data_start)}</p>
        <p>{partial ? 'Partial window — collection began within this window or observation coverage is missing. ' : ''}Observed data only; today is still in progress. Missing coverage is not zero activity.</p>
        <p>Pending updates: {data.pending} · Dropped updates: {data.dropped} · Write failures: {data.write_failures} · Unclean starts: {data.metadata.unclean_starts || '0'}</p>
        {(data.metadata.last_disabled || data.metadata.last_enabled) && <p>Last disabled: {time(data.metadata.last_disabled)} · Last enabled: {time(data.metadata.last_enabled)}</p>}
        <p className="muted">Snapshot: {time(data.as_of)}. Retained users are never a historical curve.</p>
        <button className="danger" disabled={busy} onClick={() => setReset(true)}>Reset all profile analytics</button>
      </article>
      {data.channel_id && data.available && <>
      {Object.keys(totals).length === 0 && <p role="status">No observed activity in this window. Missing coverage can also produce an empty window.</p>}
      <div className="analytics-cards">
        <article className="card"><h2>Commands</h2><strong>{count(total('command.attempts'))} attempts</strong><p>{count(total('command.success'))} success · {count(total('command.error'))} errors</p><p>{count(total('command.skipped'))} skipped · {count(total('command.partial'))} partial · {count(total('command.uncertain'))} uncertain · {count(total('command.cancelled'))} cancelled · {count(total('command.incomplete'))} incomplete</p></article>
        <article className="card"><h2>Retained users now</h2><strong>{data.retained_users === null ? 'Unavailable' : count(data.retained_users)}</strong><p>Current channel snapshot · 60-day inactive expiry</p></article>
        <article className="card"><h2>AI usage</h2><strong>{count(total('ai.requests'))} requests · {count(total('ai.attempts'))} provider attempts</strong><p>{count(total('ai.input_tokens'))} input / {count(total('ai.output_tokens'))} output tokens reported</p><p>{count(total('ai.usage_unknown'))} attempts with unknown/incomplete usage. Token subsets are not added twice.</p></article>
        <article className="card"><h2>AI spend estimate</h2><strong>{total('ai.attempts') > 0 && !('ai.estimated_usd' in totals) ? 'Unknown' : money(total('ai.estimated_usd'))} known subtotal</strong><p>{incomplete ? 'Incomplete — unknown usage, pricing or extra charges.' : 'Dated estimate; not an invoice.'}</p><p>{count(total('ai.price_missing'))} attempts with unknown pricing. Rates checked {data.price_checked}.</p></article>
      </div>
      <article className="card"><label>Trend<Select aria-label="Trend" value={metric} onChange={setMetric} options={trends} /></label><Trend data={data} metric={metric} /></article>
      <div className="analytics-breakdowns">
        <article className="card"><h2>Commands breakdown</h2><div className="analytics-table"><table><thead><tr><th>Command ID</th><th>Attempts</th><th>Success</th><th>Errors</th><th>Skipped</th></tr></thead><tbody>{data.commands.map((row) => <tr key={row.name}><th>{row.name}</th>{['attempts', 'success', 'error', 'skipped'].map((key) => <td key={key}>{count(row.metrics[`command.${key}`])}</td>)}</tr>)}</tbody></table></div>{!data.commands.length && <p>No command observations.</p>}</article>
        <article className="card"><h2>Providers / models</h2><div className="analytics-table"><table><thead><tr><th>Provider / model</th><th>Attempts</th><th>Errors</th><th>Known USD</th><th>Unknown usage / pricing</th></tr></thead><tbody>{data.providers.map((row) => <tr key={row.name}><th>{row.name}</th><td>{count(row.metrics['ai.attempts'])}</td><td>{count(row.metrics['ai.errors'])}</td><td>{'ai.estimated_usd' in row.metrics ? money(row.metrics['ai.estimated_usd']) : 'Unknown'}</td><td>{count(row.metrics['ai.usage_unknown'])} / {count(row.metrics['ai.price_missing'])}</td></tr>)}</tbody></table></div>{!data.providers.length && <p>No provider observations.</p>}</article>
      </div>
      </>}
    </>}
    <article className="card"><div className="ai-state-heading"><h2>Provider balance</h2><HelpTip label="Provider balance">Optional account-wide balance, independent of this channel's estimated spend. DeepSeek supports balance queries using the existing secure connection. Refresh is on demand, cached for at least 60 seconds and has a bounded timeout. A balance API is never required for AI replies. Keys stay in the backend.</HelpTip></div>
      <div className="analytics-toolbar"><label>Balance provider<Select aria-label="Balance provider" value={provider} disabled={balanceBusy} onChange={(value) => { setProvider(value); setBalance(null) }} options={[{ value: 'deepseek', label: 'DeepSeek' }, { value: 'gemini', label: 'Gemini' }, { value: 'openai', label: 'OpenAI' }]} /></label><button className="secondary" disabled={balanceBusy || provider !== 'deepseek'} onClick={() => {
        setBalanceBusy(true)
        void (async () => {
          try { setBalance(await (await waitForBridge()).get_ai_balance(provider, true)) }
          catch { setBalance({ ok: false, provider, state: 'unavailable', balances: [], updated_at: null, error: 'Balance refresh unavailable. Retry later.' }) }
          finally { setBalanceBusy(false) }
        })()
      }}>{balanceBusy ? 'Refreshing balance…' : 'Refresh balance'}</button></div>
      <div role="status">{provider !== 'deepseek' ? 'Unavailable — this provider has no supported balance API.' : !balance ? 'Unavailable — refresh on demand.' : <><p>{balance.state === 'stale' ? 'Stale — last known balance; refresh failed or cache expired.' : balance.state === 'available' ? 'Available' : 'Unavailable'} · Last updated: {time(balance.updated_at)}</p>{balance.balances.map((item) => <p key={item.currency}><strong>{item.currency} {item.total_balance}</strong> · Granted {item.granted_balance} · Topped up {item.topped_up_balance}</p>)}{balance.error && <p>{balance.error}</p>}</>}</div>
    </article>
    {reset && <Confirmation title="Reset all profile analytics?" description="Permanently clear aggregate totals for every channel and Playground in this profile, including pending updates. Personal AI memory, presence and opt-outs are unchanged. Operator-managed backups are separate copies." danger onCancel={() => setReset(false)} onConfirm={() => { setReset(false); void action(async () => (await waitForBridge()).reset_analytics(true)) }} />}
  </div>
}
