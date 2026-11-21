import { useEffect, useRef, useState } from 'react'

import { type OptOutUser, waitForBridge } from '../bridge'
import AccordionHeader from './AccordionHeader'
import Confirmation from './Confirmation'
import HelpTip from './HelpTip'
import { commandsText } from '../i18n/commands'
import { useCatalog, useI18n } from '../i18n/core'

const PAGE_SIZE = 50

export default function OptOutManagement({ active }: { active: boolean }) {
  const text = useCatalog(commandsText).optOut
  const { fmt, dateTime } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const [username, setUsername] = useState('')
  useRestartDraft('Local privacy', Boolean(username.trim()))
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [users, setUsers] = useState<OptOutUser[]>([])
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [withdrawTarget, setWithdrawTarget] = useState<OptOutUser | null>(null)
  const revision = useRef(0)
  const pending = useRef(false)
  const usernameInput = useRef<HTMLInputElement>(null)

  const load = async () => {
    if (pending.current) return
    const current = ++revision.current
    setLoading(true)
    try {
      const result = await (await waitForBridge()).get_opt_outs(query.trim(), offset, PAGE_SIZE)
      if (current !== revision.current) return
      if (!result.ok) throw new Error(result.error || text.loadFailed)
      if (result.total > 0 && offset >= result.total) {
        setOffset(Math.floor((result.total - 1) / PAGE_SIZE) * PAGE_SIZE)
        return
      }
      setUsers(result.users); setTotal(result.total); setLoaded(true); setError('')
    } catch (reason) {
      if (current === revision.current) setError(reason instanceof Error ? reason.message : text.loadFailed)
    } finally { if (current === revision.current) setLoading(false) }
  }

  useEffect(() => {
    if (!active || !expanded) return
    setLoaded(false)
    const debounce = window.setTimeout(() => void load(), 200)
    const refresh = window.setInterval(() => void load(), 15_000)
    const onFocus = () => void load()
    window.addEventListener('focus', onFocus)
    return () => { window.clearTimeout(debounce); window.clearInterval(refresh); window.removeEventListener('focus', onFocus); revision.current++ }
  }, [active, expanded, query, offset])

  const change = async (action: 'add' | 'withdraw') => {
    if (pending.current) return
    pending.current = true; revision.current++; setLoading(false); setBusy(true); setError(''); setNotice('')
    let succeeded = false
    try {
      const api = await waitForBridge()
      const result = action === 'add'
        ? await api.add_opt_out(username.trim())
        : await api.withdraw_opt_out(withdrawTarget!.twitch_user_id, true)
      if (!result.ok) throw new Error(result.error || text.changeFailed)
      if (action === 'add') setUsername('')
      setNotice(action === 'add' ? text.added : text.withdrawn)
      setWithdrawTarget(null); succeeded = true
    } catch (reason) {
      setWithdrawTarget(null)
      setError(reason instanceof Error ? reason.message : text.changeFailed)
    } finally {
      pending.current = false; setBusy(false); if (succeeded) void load()
    }
  }

  return <article className="command-card optout-management" id="optout-management">
    <AccordionHeader ariaLabel={text.manage} title={text.title} expanded={expanded} contentId="optout-management-content" onToggle={() => setExpanded(!expanded)}
      helpLabel={text.helpLabel} help={<ul>{text.help.map((item) => <li key={item}>{item}</li>)}</ul>} />
    {expanded && <div className="command-details optout-details" id="optout-management-content">
      <div className="optout-fields">
        <div className="form-field optout-field">
          <div className="custom-field-label">
            <label htmlFor="optout-username">{text.username}</label>
            <HelpTip label={text.verifyLabel}>{text.verifyHelp}</HelpTip>
          </div>
          <input ref={usernameInput} id="optout-username" aria-describedby="optout-add-effect" disabled={busy} value={username} maxLength={26} autoComplete="off" placeholder={text.usernamePlaceholder} onChange={(event) => setUsername(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && username.trim() && !busy) { event.preventDefault(); void change('add') } }} />
          <div className="optout-field-footer">
            <span className="settings-hint" id="optout-add-effect">{text.addEffect}</span>
            <div className="row-actions">
              <button className="secondary" disabled={busy || !username} onClick={() => { setUsername(''); usernameInput.current?.focus() }}>{text.cancel}</button>
              <button className="primary" disabled={busy || !username.trim()} onClick={() => void change('add')}>{busy ? text.working : text.add}</button>
            </div>
          </div>
        </div>
        <div className="form-field optout-field">
          <label htmlFor="optout-search">{text.search}</label>
          <input id="optout-search" type="search" disabled={busy} value={query} placeholder={text.searchPlaceholder} onChange={(event) => { setQuery(event.target.value); setOffset(0) }} />
          <div className="row-actions"><button className="secondary" disabled={busy || loading} onClick={() => void load()}>{text.refresh}</button></div>
        </div>
      </div>
      {error && <div className="inline-error" role="alert"><span>{error}</span><button className="secondary" disabled={busy || loading} onClick={() => void load()}>{text.retry}</button></div>}
      {notice && <p role="status">{notice}</p>}
      <h3>{text.listTitle}</h3>
      {loading && <p role="status">{text.loading}</p>}
      {loaded && users.length > 0 && <div className="optout-table-wrap"><table className="optout-table"><thead><tr><th scope="col">#</th><th scope="col">{text.columnUsername}</th><th scope="col">{text.columnDate}</th><th scope="col"><span className="sr-only">{text.columnActions}</span></th></tr></thead><tbody>{users.map((user, index) => <tr key={user.twitch_user_id}>
        <td>{offset + index + 1}</td><td>{user.username ?? <span className="muted">{text.usernameUnavailable}</span>}</td><td>{user.opted_out_at ? <time dateTime={user.opted_out_at}>{dateTime(user.opted_out_at)}</time> : <span className="muted">{text.dateUnknown}</span>}</td>
        <td><button className="ghost destructive" aria-label={user.username ? fmt(text.withdrawNamed, { index: String(offset + index + 1), name: user.username }) : fmt(text.withdrawIndex, { index: String(offset + index + 1) })} disabled={busy} onClick={() => setWithdrawTarget(user)}>{text.withdraw}</button></td>
      </tr>)}</tbody></table></div>}
      {loaded && !users.length && !loading && <p>{query ? text.noMatches : text.empty}</p>}
      {total > PAGE_SIZE && <div className="optout-pagination"><span>{fmt(text.page, { start: String(offset + 1), end: String(Math.min(offset + PAGE_SIZE, total)), total: String(total) })}</span><div className="row-actions"><button className="secondary" disabled={busy || loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>{text.previous}</button><button className="secondary" disabled={busy || loading || offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>{text.next}</button></div></div>}
      {withdrawTarget && <Confirmation title={text.withdrawTitle} description={fmt(text.withdrawDescription, { name: withdrawTarget.username ?? text.unnamedAccount })} danger onCancel={() => { if (!busy) setWithdrawTarget(null) }} onConfirm={() => void change('withdraw')} />}
    </div>}
  </article>
}
import { useRestartDraft } from '../desktopRestart'
