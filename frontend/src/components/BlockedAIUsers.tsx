import { useEffect, useState } from 'react'
import { type BlockedAIUser, waitForBridge } from '../bridge'
import HelpTip from './HelpTip'
import { aiText } from '../i18n/ai'
import { common as commonText } from '../i18n/common'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'

export default function BlockedAIUsers({ active, onOpenAsk }: { active: boolean; onOpenAsk?: () => void }) {
  const [users, setUsers] = useState<BlockedAIUser[] | null>(null)
  const [username, setUsername] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const text = useCatalog(aiText).blocked
  const common = useCatalog(commonText)
  const { fmt } = useI18n()

  useEffect(() => {
    if (!active) return
    let current = true
    void (async () => {
      try {
        const result = await (await waitForBridge()).get_blocked_ai_users()
        if (!result.ok || !result.users) throw new Error(result.error ?? catalogFor(aiText).blocked.loadFailed)
        if (current) { setUsers(result.users); setError('') }
      } catch (reason) {
        if (current) setError(reason instanceof Error ? reason.message : catalogFor(aiText).blocked.loadFailed)
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
      if (!result.ok || !result.users) throw new Error(result.error ?? text.updateFailed)
      setUsers(result.users)
      if (!unblock) setUsername('')
      setNotice(unblock ? fmt(text.unblocked, { name: login }) : text.blockedNotice)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.updateFailed)
    } finally { setBusy(false) }
  }

  return <article className="card ai-user-blocks" id="ai-blocked-users" aria-busy={busy}>
    <div className="section-heading ai-access-heading">
      <div>
        <h2>{text.title}</h2>
        <HelpTip label={text.title}><ul>{text.help.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip>
      </div>
    </div>
    <p className="section-copy">{text.copy}</p>
    <form className="ai-user-block-form" onSubmit={(event) => { event.preventDefault(); void changeBlock(username) }}>
      <label className="form-field">{text.username}
        <input value={username} disabled={busy || users === null} autoComplete="off" placeholder={text.placeholder} onChange={(event) => { setUsername(event.target.value); setError(''); setNotice('') }} />
      </label>
      <button className="primary" type="submit" disabled={busy || users === null || !username.trim()}>{busy ? common.saving : text.block}</button>
    </form>
    {error && <p className="inline-feedback error" role="alert">{error}</p>}
    {notice && <p className="inline-feedback" role="status">{notice}</p>}
    {users && users.length > 0 && <ul className="ai-user-block-list">{users.map((user) => <li key={user.username}>
          <span>@{user.username}</span>
          <button type="button" className="secondary" disabled={busy} aria-label={fmt(text.unblockUser, { name: user.username })} onClick={() => void changeBlock(user.username, true)}>{text.unblock}</button>
        </li>)}</ul>}
    <div className="ai-access-footer">
      {users === null ? <p className="muted">{text.notLoaded}</p>
        : users.length === 0 && <p className="muted">{text.empty}</p>}
      {onOpenAsk && <div className="ai-access-actions"><button className="secondary" onClick={onOpenAsk}>{text.editAccess}</button></div>}
    </div>
  </article>
}
