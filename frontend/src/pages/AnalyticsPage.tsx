import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { type AnalyticsResponse, waitForBridge } from '../bridge'
import ChatLeaderboards from '../components/ChatLeaderboards'
import { Select } from '../components/Select'
import Switch from '../components/Switch'
import HelpTip from '../components/HelpTip'
import Confirmation from '../components/Confirmation'
import './analytics.css'
import { analyticsText } from '../i18n/analytics'
import { useCatalog, useI18n, type Plural } from '../i18n/core'

type TrendText = { label: string; amount: Plural }
const trendKeys = ['command.attempts', 'command.success', 'command.error', 'users.new', 'ai.requests', 'ai.input_tokens', 'ai.output_tokens'] as const

/** Locale-aware number helpers and UTC timestamps for the current UI language. */
function useFormatters() {
  const text = useCatalog(analyticsText)
  const { fmt, number } = useI18n()
  const count = (value = 0) => number(value, { maximumFractionDigits: 0 })
  const time = (value?: string | null) => value ? fmt(text.utc, { time: value.replace('T', ' ').replace(/(?:\.\d+)?(?:Z|\+00:00)$/, '') }) : text.unavailable
  const dataSinceTime = (value?: string | null) => value ? fmt(text.utc, { time: value.replace('T', ' ').replace(/(?:Z|\+00:00)$/, '') }) : text.unavailable
  const trends = trendKeys.map((value) => ({ value, ...(text.trends[value] as TrendText) }))
  return { text, count, time, dataSinceTime, trends }
}

type Bucket = AnalyticsResponse['series'][number]
const bucketStart = (row: Bucket) => Date.parse(row.day.includes('T') ? row.day : row.day + 'T00:00:00Z')
const bucketLabel = (row: Bucket, hourly: boolean) => hourly ? `${row.day.slice(11, 16)} UTC` : row.day
function observed(row: Bucket, metric: string, data: AnalyticsResponse) {
  if (bucketStart(row) > Date.parse(data.as_of)) return false
  if (metric in row.metrics) return true
  const coverage = metric === 'users.new' ? row.new_users_coverage_seconds : row.coverage_seconds
  if (!(coverage > 0 && row.metrics['connection.seconds'] > 0)) return false
  if (['ai.input_tokens', 'ai.output_tokens'].includes(metric) && row.metrics['ai.attempts'] > 0) return false
  return true
}
function Trend({ data, metric, selector }: { data: AnalyticsResponse; metric: string; selector: React.ReactNode }) {
  const chart = useRef<SVGSVGElement>(null)
  const [width, setWidth] = useState(760)
  const [selected, setSelected] = useState<number | null>(null)
  const { text, count, trends } = useFormatters()
  const { fmt, plural } = useI18n()
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
  const format = count
  const coverageState = (row: Bucket, index: number) => {
    if (bucketStart(row) > Date.parse(data.as_of)) return text.futureHour
    if (!known[index]) return text.unknownGap
    const seconds = metric === 'users.new' ? row.new_users_coverage_seconds : row.coverage_seconds
    const elapsed = Math.min(hourly ? 3600 : 86400, (Date.parse(data.as_of) - bucketStart(row)) / 1000)
    return seconds < elapsed - 5 ? text.partialObservation : text.observed
  }
  const bucket = selected === null ? undefined : data.series[selected]
  const value = bucket?.metrics[metric] ?? 0
  const tooltipValue = plural(trend.amount, value, { count: count(value) })
  const selectPointer = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const localX = (event.clientX - bounds.left) * width / bounds.width
    const index = Math.round((localX - x(0)) / (width - 70) * (data.series.length - 1))
    setSelected(Math.max(0, Math.min(data.series.length - 1, index)))
  }
  return <>
    <div className="analytics-plot">
      <svg ref={chart} className="analytics-chart" viewBox={`0 0 ${width} 215`} role="img" aria-label={fmt(hourly ? text.chartHourly : text.chartDaily, { label })}
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
          <strong>{known[selected] ? tooltipValue : fmt(text.labelUnavailable, { label })}</strong>
          <span>{bucketLabel(bucket, hourly)}</span>
        </div>}
      </div>
    </div>
    {selector}
    {metric === 'users.new' && <p className="muted">{text.newUsersNote}{' '}
      <HelpTip label={text.whoCounts}><ul>{text.whoCountsHelp.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip></p>}
    <details className="analytics-values"><summary>{hourly ? text.hourlyValues : text.dailyValues}</summary><div className="analytics-table" tabIndex={0} role="region" aria-label={text.trendTable}><table><caption>{fmt(hourly ? text.captionHours : text.captionDays, { label })}</caption><thead><tr><th>{hourly ? text.hour : text.day}</th><th>{text.observedValue}</th><th>{text.coverage}</th><th>{text.appCollection}</th><th>{text.connected}</th></tr></thead><tbody>{data.series.map((row, index) => <tr key={row.day}><th>{bucketLabel(row, hourly)}</th><td>{known[index] ? format(row.metrics[metric]) : text.unknown}</td><td>{coverageState(row, index)}</td><td>{fmt(text.minutes, { minutes: String(Math.round(row.coverage_seconds / 60)) })}</td><td>{fmt(text.minutes, { minutes: String(Math.round((row.metrics['connection.seconds'] || 0) / 60)) })}</td></tr>)}</tbody></table></div></details>
  </>
}

export default function AnalyticsPage({ leaderboardChannel }: { leaderboardChannel?: string | null }) {
  const { text, count, time, dataSinceTime, trends } = useFormatters()
  const { fmt, plural } = useI18n()
  const [days, setDays] = useState('7')
  const [metric, setMetric] = useState('command.attempts')
  const [data, setData] = useState<AnalyticsResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reset, setReset] = useState(false)
  const load = async (windowDays: number) => {
    const response = await (await waitForBridge()).get_analytics(windowDays)
    if (!response.ok) throw new Error(response.error || text.analyticsUnavailable)
    return response
  }
  useEffect(() => {
    let current = true
    setBusy(true); setError(''); setData(null)
    void load(Number(days)).then((response) => { if (current) setData(response) }).catch(() => {
      if (current) setError(text.loadFailed)
    }).finally(() => { if (current) setBusy(false) })
    return () => { current = false }
  }, [days])
  const action = async (operation?: () => Promise<{ ok: boolean; error?: string }>) => {
    setBusy(true); setError('')
    try {
      if (operation) { const result = await operation(); if (!result.ok) throw new Error(result.error || text.operationFailed) }
      setData(await load(Number(days)))
    } catch (reason) { setError(reason instanceof Error ? reason.message : text.analyticsUnavailable) }
    finally { setBusy(false) }
  }
  const totals = data?.totals || {}
  const total = (key: string) => totals[key] || 0
  const hasObservations = Boolean(data?.available && data.channel_id && (Object.keys(totals).length || data.series.some((row) => row.coverage_seconds > 0 && row.metrics['connection.seconds'] > 0)))
  const value = (key: string) => hasObservations ? count(total(key)) : text.unknown
  const partial = data && data.series.some((row) => {
    const elapsed = Math.min(data.resolution === 'hour' ? 3600 : 86400, (Date.parse(data.as_of) - bucketStart(row)) / 1000)
    return elapsed > 0 && row.coverage_seconds < elapsed - 5
  })
  return <div className="analytics-layout" aria-busy={busy}>
    <div className="analytics-toolbar"><label>{text.utcWindow}<Select aria-label={text.utcWindow} value={days} onChange={setDays} disabled={busy} options={[{ value: '1', label: text.today }, ...[7, 30, 60].map((n) => ({ value: String(n), label: plural(text.days, n) }))]} /></label><button className="secondary" disabled={busy} onClick={() => void action()}>{text.refreshAnalytics}</button></div>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {busy && !data && <p role="status">{text.loading}</p>}
    {data && <article className="card analytics-trend" id="analytics-trends">
      <Trend key={`${data.resolution}:${data.start}:${data.end}`} data={data} metric={metric} selector={<label className="analytics-trend-select">{text.trend}<Select aria-label={text.trend} value={metric} onChange={setMetric} options={trends} /></label>} />
      <p className="muted">{data.resolution === 'hour' ? fmt(text.hourlyNote, { date: data.end }) : text.dailyNote}</p>
    </article>}
    <div className="analytics-cards">
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>{text.commands}</h2><HelpTip label={text.otherOutcomes}>
        <p>{text.otherOutcomesNote}</p>
        <p>{fmt(text.otherOutcomesValues, { skipped: value('command.skipped'), partial: value('command.partial'), uncertain: value('command.uncertain'), cancelled: value('command.cancelled'), incomplete: value('command.incomplete') })}</p>
      </HelpTip></div><strong className="analytics-primary">{fmt(text.attempts, { count: value('command.attempts') })}</strong><p>{fmt(text.successes, { success: value('command.success'), errors: value('command.error') })}</p></article>
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>{text.retainedUsers}</h2><HelpTip label={text.recordsLast}>{text.recordsHelp}</HelpTip></div><strong className="analytics-primary">{data?.retained_users == null ? text.unavailable : count(data.retained_users)}</strong><p>{text.viewerRecords}</p></article>
      <article className="card analytics-summary"><div className="ai-state-heading"><h2>{text.aiUsage}</h2><HelpTip label={text.usageDetails}>
        <ul>
          <li>{fmt(text.usageAttempts, { attempts: value('ai.attempts'), unknown: value('ai.usage_unknown') })}</li>
          <li>{text.usageScope}</li>
        </ul>
      </HelpTip></div><strong className="analytics-primary">{fmt(text.requests, { count: value('ai.requests') })}</strong><p>{fmt(text.tokens, {
        input: !hasObservations || (total('ai.attempts') > 0 && !('ai.input_tokens' in totals)) ? text.unknown : count(total('ai.input_tokens')),
        output: !hasObservations || (total('ai.attempts') > 0 && !('ai.output_tokens' in totals)) ? text.unknown : count(total('ai.output_tokens')),
      })}</p></article>
    </div>
    <ChatLeaderboards key={leaderboardChannel ?? ''} channel={leaderboardChannel} countingEnabled={data?.count_chat_messages} />
    {data && <>
      {Object.keys(totals).length === 0 && <p role="status">{text.noActivity}</p>}
      <div className="analytics-breakdowns" id="analytics-breakdown">
        <article className="card"><div className="ai-state-heading"><h2>{text.commandsBreakdown}</h2><HelpTip label={text.attemptsCounted}><ul>{text.attemptsHelp.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip></div><div className="analytics-table analytics-command-table" tabIndex={0} role="region" aria-label={text.breakdownTable}><table><thead><tr><th>{text.command}</th><th>{text.attemptsColumn}</th><th>{text.success}</th><th>{text.errors}</th><th>{text.skipped}</th></tr></thead><tbody>{data.commands.map((row) => <tr key={row.name}><th><span className={`analytics-command-name${!row.label || row.label.startsWith('Deleted or unavailable command') ? ' analytics-command-unavailable' : ''}`} title={row.label || fmt(text.deletedCommand, { name: row.name })}>{row.label || fmt(text.deletedCommand, { name: row.name })}</span></th>{['attempts', 'success', 'error', 'skipped'].map((key) => <td key={key}>{data.available && data.channel_id ? count(row.metrics[`command.${key}`]) : text.unavailable}</td>)}</tr>)}</tbody></table></div>{!data.commands.length && <p>{text.noCommands}</p>}</article>
        <article className="card"><div className="ai-state-heading"><h2>{text.providersModels}</h2></div><div className="analytics-table" tabIndex={0} role="region" aria-label={text.providersTable}><table><thead><tr><th>{text.providerModel}</th><th>{text.attemptsColumn}</th><th>{text.errors}</th><th>{text.unknownUsage}</th></tr></thead><tbody>{data.providers.map((row) => <tr key={row.name}><th>{row.name}</th><td>{count(row.metrics['ai.attempts'])}</td><td>{count(row.metrics['ai.errors'])}</td><td>{count(row.metrics['ai.usage_unknown'])}</td></tr>)}</tbody></table></div>{!data.providers.length && <p>{text.noProviders}</p>}</article>
      </div>
      <article className="card analytics-coverage" id="analytics-collection">
        <div className="analytics-coverage-heading">
          <h2>{text.collectionCoverage}</h2>
          {(data.dropped > 0 || data.write_failures > 0 || Number(data.metadata.unclean_starts) > 0) && <p role="alert" className="analytics-data-loss">{text.dataLoss}</p>}
        </div>
        <div className="analytics-coverage-zones">
          <div className="analytics-collection" role="group" aria-label={text.collection} aria-describedby="analytics-save-timing">
            <div>
              <Switch checked={data.enabled} disabled={busy} ariaLabel={text.collectAnalytics} ariaDescribedBy="collect-analytics-effect" onCheckedChange={(enabled) => void action(async () => (await waitForBridge()).configure_analytics(enabled))}>{text.collectAnalytics}</Switch>
              <p className="muted" id="collect-analytics-effect">{text.collectEffect}</p>
            </div>
            <div>
              <Switch checked={data.count_chat_messages} disabled={busy} ariaLabel={text.countChat} ariaDescribedBy="count-chat-effect" onCheckedChange={(enabled) => void action(async () => (await waitForBridge()).configure_leaderboard_counting(enabled))}>{text.countChat}</Switch>
              <p className="muted" id="count-chat-effect">{text.countChatEffect}</p>
            </div>
            <p className="muted analytics-collection-note" id="analytics-save-timing">{text.savesImmediately}</p>
          </div>
          <section className="analytics-coverage-summary" aria-label={text.coverageLabel}>
            <p>{!data.available || !data.channel_id ? text.coverageUnavailable : partial ? text.partialCoverage : text.observedCoverage}{!data.enabled && text.collectionPaused}</p>
            <p className="muted">{fmt(text.range, { start: data.start, end: data.end })}</p>
          </section>
          {!data.available && <p role="alert" className="inline-error">{text.storageUnavailable}</p>}
          {!data.channel_id && <p role="status">{text.noChannelId}</p>}
        </div>
        <div className="analytics-coverage-footer">
        <details className="analytics-collection-details"><summary>{text.collectionDetails}</summary><dl>
          <div><dt>{text.dataSince}</dt><dd>{dataSinceTime(data.metadata.data_start)}</dd></div>
          <div><dt>{text.hourlySince}</dt><dd>{time(data.metadata.hourly_start)}</dd></div>
          <div><dt>{text.newUsersSince}</dt><dd>{time(data.metadata.new_users_start)}</dd></div>
          <div><dt>{text.connection}</dt><dd>{data.connected ? text.connected : text.disconnectedGap}</dd></div>
          <div><dt>{text.channel}</dt><dd>{data.channel_id || text.channelUnavailable}</dd></div>
          <div><dt>{text.storage}</dt><dd>{data.available ? text.available : text.storageIncomplete}</dd></div>
          <div><dt>{text.pending}</dt><dd>{data.pending}</dd></div>
          <div><dt>{text.dropped}</dt><dd>{data.dropped}</dd></div>
          <div><dt>{text.writeFailures}</dt><dd>{data.write_failures}</dd></div>
          <div><dt>{text.uncleanStarts}</dt><dd>{data.metadata.unclean_starts || '0'}</dd></div>
          <div><dt>{text.lastDisabled}</dt><dd>{time(data.metadata.last_disabled)}</dd></div>
          <div><dt>{text.lastEnabled}</dt><dd>{time(data.metadata.last_enabled)}</dd></div>
          <div><dt>{text.snapshot}</dt><dd>{time(data.as_of)}</dd></div>
        </dl></details>
          <button className="analytics-reset" disabled={busy} onClick={() => setReset(true)}>{text.resetAll}</button>
        </div>
      </article>
    </>}
    {reset && <Confirmation title={text.resetTitle} description={text.resetDescription} danger onCancel={() => setReset(false)} onConfirm={() => { setReset(false); void action(async () => (await waitForBridge()).reset_analytics(true)) }} />}
  </div>
}
