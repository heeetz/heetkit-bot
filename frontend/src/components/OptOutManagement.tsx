import { useEffect, useRef, useState } from 'react'

import { type OptOutUser, waitForBridge } from '../bridge'
import AccordionHeader from './AccordionHeader'
import Confirmation from './Confirmation'
import HelpTip from './HelpTip'

const PAGE_SIZE = 50

export default function OptOutManagement({ active }: { active: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const [username, setUsername] = useState('')
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
    <AccordionHeader ariaLabel="Manage !optout" title={<strong>!optout</strong>} expanded={expanded} contentId="optout-management-content" onToggle={() => setExpanded(!expanded)}
      helpLabel="!optout management" help="Profile-wide storage privacy. Add erases this account's stored presence and AI history and prevents new storage in every channel. This is separate from command access restrictions. Self-service !optout is always available and appears last in public command help. Withdrawal allows future storage without restoring history or replaying old input." />
    {expanded && <div className="command-details optout-details" id="optout-management-content">
      <div className="optout-add-row">
        <div className="form-field"><div className="custom-field-label"><label htmlFor="optout-username">Twitch username</label><HelpTip label="Add storage opt-out">The server verifies the Twitch account. Adding deletes stored personal history and suppresses future storage across all channels in this profile.</HelpTip></div>
          <input ref={usernameInput} id="optout-username" disabled={busy} value={username} maxLength={26} autoComplete="off" placeholder="e.g. viewer_name" onChange={(event) => setUsername(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && username.trim() && !busy) { event.preventDefault(); void change('add') } }} /></div>
        <div className="row-actions"><button className="secondary" disabled={busy || !username} onClick={() => { setUsername(''); usernameInput.current?.focus() }}>Cancel</button><button className="primary" disabled={busy || !username.trim()} onClick={() => void change('add')}>{busy ? 'Working...' : 'Add'}</button></div>
      </div>
      <p className="settings-hint">Add erases this user's stored personal history across the profile and prevents future storage.</p>
      {error && <div className="inline-error" role="alert"><span>{error}</span><button className="secondary" disabled={busy || loading} onClick={() => void load()}>Retry list</button></div>}
      {notice && <p role="status">{notice}</p>}
      <h3>Opted-out users</h3>
      <div className="restriction-toolbar"><div className="form-field"><label htmlFor="optout-search">Search opted-out users</label><input id="optout-search" type="search" disabled={busy} value={query} placeholder="Stored Twitch username" onChange={(event) => { setQuery(event.target.value); setOffset(0) }} /></div><button className="secondary" disabled={busy || loading} onClick={() => void load()}>Refresh</button></div>
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
