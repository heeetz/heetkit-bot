import { useEffect, useState } from 'react'
import { type BlockedAIUser, waitForBridge } from '../bridge'
import HelpTip from './HelpTip'

export default function BlockedAIUsers({ active, onOpenAsk }: { active: boolean; onOpenAsk?: () => void }) {
  const [users, setUsers] = useState<BlockedAIUser[] | null>(null)
  const [username, setUsername] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!active) return
    let current = true
    void (async () => {
      try {
        const result = await (await waitForBridge()).get_blocked_ai_users()
        if (!result.ok || !result.users) throw new Error(result.error ?? 'Could not load blocked AI users.')
        if (current) { setUsers(result.users); setError('') }
      } catch (reason) {
        if (current) setError(reason instanceof Error ? reason.message : 'Could not load blocked AI users.')
      }
    })()
    return () => { current = false }
  }, [active])

  const changeBlock = async (login: string, unblock = false) => {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = unblock ? await api.unblock_ai_user(login) : await api.block_ai_user(login)
      if (!result.ok || !result.users) throw new Error(result.error ?? 'Could not update blocked AI users.')
      setUsers(result.users)
      if (!unblock) setUsername('')
      setNotice(unblock ? `@${login} can use AI requests again.` : 'User blocked from AI requests.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not update blocked AI users.')
    } finally { setBusy(false) }
  }

  return <article className="card ai-user-blocks" id="ai-blocked-users" aria-busy={busy}>
    <div className="section-heading ai-access-heading">
      <div>
        <h2>AI access</h2>
        <HelpTip label="AI access">Blocking only affects AI command requests, including all aliases. It does not ban a Twitch user or delete their messages.</HelpTip>
      </div>
    </div>
    <p className="section-copy">Silently ignore these users' AI command requests.</p>
    <form className="ai-user-block-form" onSubmit={(event) => { event.preventDefault(); void changeBlock(username) }}>
      <label className="form-field">Twitch username
        <input value={username} disabled={busy || users === null} autoComplete="off" placeholder="username or @username" onChange={(event) => { setUsername(event.target.value); setError(''); setNotice('') }} />
      </label>
      <button className="primary" type="submit" disabled={busy || users === null || !username.trim()}>{busy ? 'Saving…' : 'Block user'}</button>
    </form>
    {error && <p className="inline-feedback error" role="alert">{error}</p>}
    {notice && <p className="inline-feedback" role="status">{notice}</p>}
    {users && users.length > 0 && <ul className="ai-user-block-list">{users.map((user) => <li key={user.username}>
          <span>@{user.username}</span>
          <button type="button" className="secondary" disabled={busy} aria-label={`Unblock ${user.username}`} onClick={() => void changeBlock(user.username, true)}>Unblock</button>
        </li>)}</ul>}
    <div className="ai-access-footer">
      {users === null ? <p className="muted">Blocked users are unavailable until loaded.</p>
        : users.length === 0 && <p className="muted">No blocked AI users.</p>}
      {onOpenAsk && <div className="ai-access-actions"><button className="secondary" onClick={onOpenAsk}>Edit AI command access and cooldowns</button></div>}
    </div>
  </article>
}
