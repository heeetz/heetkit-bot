import { useEffect, useRef, useState } from 'react'

import { type OptOutUser, waitForBridge } from '../bridge'
import AccordionHeader from './AccordionHeader'
import Confirmation from './Confirmation'
import HelpTip from './HelpTip'

const PAGE_SIZE = 50

export default function OptOutManagement({ active }: { active: boolean }) {
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
      if (!result.ok) throw new Error(result.error || 'Could not load opted-out users.')
      if (result.total > 0 && offset >= result.total) {
        setOffset(Math.floor((result.total - 1) / PAGE_SIZE) * PAGE_SIZE)
        return
      }
      setUsers(result.users); setTotal(result.total); setLoaded(true); setError('')
    } catch (reason) {
      if (current === revision.current) setError(reason instanceof Error ? reason.message : 'Could not load opted-out users.')
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
      if (!result.ok) throw new Error(result.error || 'Could not change this storage opt-out.')
      if (action === 'add') setUsername('')
      setNotice(action === 'add' ? 'Storage opt-out added. Stored personal data was erased across this profile.' : 'Opt-out withdrawn. Future storage is allowed; erased history is not restored.')
      setWithdrawTarget(null); succeeded = true
    } catch (reason) {
      setWithdrawTarget(null)
      setError(reason instanceof Error ? reason.message : 'Could not change this storage opt-out.')
    } finally {
      pending.current = false; setBusy(false); if (succeeded) void load()
    }
  }

  return <article className="command-card optout-management" id="optout-management">
    <AccordionHeader ariaLabel="Manage !optout" title="Storage opt-outs" expanded={expanded} contentId="optout-management-content" onToggle={() => setExpanded(!expanded)}
      helpLabel="How opt-outs work" help={<ul><li>An opt-out erases the account’s presence, AI history and leaderboard counts in this profile.</li><li>Withdrawing allows storage again but does not bring erased data back.</li></ul>} />
    {expanded && <div className="command-details optout-details" id="optout-management-content">
      <div className="optout-fields">
        <div className="form-field optout-field">
          <div className="custom-field-label">
            <label htmlFor="optout-username">Twitch username</label>
            <HelpTip label="Verify account">HeetKit must match this username to a real Twitch account before changing its opt-out.</HelpTip>
          </div>
          <input ref={usernameInput} id="optout-username" aria-describedby="optout-add-effect" disabled={busy} value={username} maxLength={26} autoComplete="off" placeholder="e.g. viewer_name" onChange={(event) => setUsername(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && username.trim() && !busy) { event.preventDefault(); void change('add') } }} />
          <div className="optout-field-footer">
            <span className="settings-hint" id="optout-add-effect">Adding permanently deletes this account’s stored history and prevents new storage across this profile.</span>
            <div className="row-actions">
              <button className="secondary" disabled={busy || !username} onClick={() => { setUsername(''); usernameInput.current?.focus() }}>Cancel</button>
              <button className="primary" disabled={busy || !username.trim()} onClick={() => void change('add')}>{busy ? 'Working...' : 'Add'}</button>
            </div>
          </div>
        </div>
        <div className="form-field optout-field">
          <label htmlFor="optout-search">Search opted-out users</label>
          <input id="optout-search" type="search" disabled={busy} value={query} placeholder="Stored Twitch username" onChange={(event) => { setQuery(event.target.value); setOffset(0) }} />
          <div className="row-actions"><button className="secondary" disabled={busy || loading} onClick={() => void load()}>Refresh</button></div>
        </div>
      </div>
      {error && <div className="inline-error" role="alert"><span>{error}</span><button className="secondary" disabled={busy || loading} onClick={() => void load()}>Retry list</button></div>}
      {notice && <p role="status">{notice}</p>}
      <h3>Opted-out users</h3>
      {loading && <p role="status">Loading opted-out users...</p>}
      {loaded && users.length > 0 && <div className="optout-table-wrap"><table className="optout-table"><thead><tr><th scope="col">#</th><th scope="col">Twitch username</th><th scope="col">Opt-out date (local time)</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead><tbody>{users.map((user, index) => <tr key={user.twitch_user_id}>
        <td>{offset + index + 1}</td><td>{user.username ?? <span className="muted">Username unavailable</span>}</td><td>{user.opted_out_at ? <time dateTime={user.opted_out_at}>{new Date(user.opted_out_at).toLocaleString()}</time> : <span className="muted">Historical date unknown</span>}</td>
        <td><button className="ghost destructive" aria-label={`Withdraw opt-out ${offset + index + 1}${user.username ? ` for ${user.username}` : ''}`} disabled={busy} onClick={() => setWithdrawTarget(user)}>Withdraw</button></td>
      </tr>)}</tbody></table></div>}
      {loaded && !users.length && !loading && <p>{query ? 'No opted-out users match this search.' : 'No opted-out users.'}</p>}
      {total > PAGE_SIZE && <div className="optout-pagination"><span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span><div className="row-actions"><button className="secondary" disabled={busy || loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button><button className="secondary" disabled={busy || loading || offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div></div>}
      {withdrawTarget && <Confirmation title="Withdraw storage opt-out?" description={`Future data storage will be allowed for ${withdrawTarget.username ?? 'this verified account (username unavailable)'} across this profile. Erased history will not be restored, and old input will not be replayed.`} danger onCancel={() => { if (!busy) setWithdrawTarget(null) }} onConfirm={() => void change('withdraw')} />}
    </div>}
  </article>
}
import { useRestartDraft } from '../desktopRestart'
