import { useEffect, useState } from 'react'

import {
  type ActionResult,
  type CommandInfo,
  type CommandsResponse,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'

interface CommandDraft {
  enabled: boolean
  permission: string
  perUserSeconds: string
  globalSeconds: string
}

type Drafts = Record<string, CommandDraft>

interface CommandsPageProps {
  active: boolean
}

function draftFromCommand(command: CommandInfo): CommandDraft {
  return {
    enabled: command.enabled,
    permission: command.permission,
    perUserSeconds: String(command.cooldown.per_user_seconds),
    globalSeconds: String(command.cooldown.global_seconds),
  }
}

function parsedCooldown(value: string): number | null {
  if (value.trim() === '') {
    return null
  }
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : null
}

function draftIsDirty(command: CommandInfo, draft: CommandDraft): boolean {
  return draft.enabled !== command.enabled
    || draft.permission !== command.permission
    || parsedCooldown(draft.perUserSeconds) !== command.cooldown.per_user_seconds
    || parsedCooldown(draft.globalSeconds) !== command.cooldown.global_seconds
}

export default function CommandsPage({ active }: CommandsPageProps) {
  const [data, setData] = useState<CommandsResponse | null>(null)
  const [drafts, setDrafts] = useState<Drafts>({})
  const [busyCommand, setBusyCommand] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const loadCommands = async (completedCommand: string) => {
    const api = await waitForBridge()
    const response = await api.get_commands()
    setData(response)
    setDrafts((currentDrafts) => Object.fromEntries(response.commands.map((command) => {
      const previousCommand = data?.commands.find((item) => item.name === command.name)
      const previousDraft = currentDrafts[command.name]
      const keepDraft = command.name !== completedCommand
        && previousCommand
        && previousDraft
        && draftIsDirty(previousCommand, previousDraft)
      return [command.name, keepDraft ? previousDraft : draftFromCommand(command)]
    })))
  }

  useEffect(() => {
    if (!active) {
      return
    }
    let mounted = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const response = await api.get_commands()
        if (mounted) {
          setData(response)
          setDrafts((currentDrafts) => Object.fromEntries(response.commands.map((command) => {
            const previousCommand = data?.commands.find((item) => item.name === command.name)
            const previousDraft = currentDrafts[command.name]
            const keepDraft = previousCommand
              && previousDraft
              && draftIsDirty(previousCommand, previousDraft)
            return [command.name, keepDraft ? previousDraft : draftFromCommand(command)]
          })))
          setError('')
        }
      } catch (reason) {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : 'Could not load commands.')
        }
      }
    }
    void load()
    return () => { mounted = false }
  }, [active])

  const updateDraft = (commandName: string, values: Partial<CommandDraft>) => {
    setDrafts((current) => ({
      ...current,
      [commandName]: { ...current[commandName], ...values },
    }))
    setError('')
    setNotice('')
  }

  const runAction = async (
    command: CommandInfo,
    action: 'apply' | 'save' | 'reset',
  ) => {
    const draft = drafts[command.name]
    if (!draft) {
      return
    }
    const perUserSeconds = parsedCooldown(draft.perUserSeconds)
    const globalSeconds = parsedCooldown(draft.globalSeconds)
    if (action !== 'reset' && (perUserSeconds === null || globalSeconds === null)) {
      setError('Cooldown values must be non-negative numbers.')
      return
    }
    if (action === 'reset' && !window.confirm(`Reset !${command.name} to its built-in defaults?`)) {
      return
    }

    setBusyCommand(command.name)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      let result: ActionResult
      if (action === 'reset') {
        result = await api.reset_command_settings(command.name)
      } else if (action === 'save') {
        result = await api.save_command_settings(
          command.name,
          draft.enabled,
          perUserSeconds!,
          globalSeconds!,
          draft.permission,
        )
      } else {
        result = await api.apply_command_settings(
          command.name,
          draft.enabled,
          perUserSeconds!,
          globalSeconds!,
          draft.permission,
        )
      }
      if (!result.ok) {
        throw new Error(result.error ?? 'Command settings could not be updated.')
      }
      await loadCommands(command.name)
      setNotice(action === 'apply'
        ? `Applied !${command.name} for this session.`
        : action === 'save'
          ? `Saved !${command.name}.`
          : `Reset !${command.name} to built-in defaults.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Command settings could not be updated.')
    } finally {
      setBusyCommand('')
    }
  }

  return (
    <section className="card command-editor-card">
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <div className="section-heading">
        <div>
          <p className="label">REGISTERED COMMANDS</p>
          <h2>Runtime command settings</h2>
          <p className="section-copy">Apply changes for this session, save them across restarts, or reset to code defaults.</p>
        </div>
        <span className="read-only-badge">Registry driven</span>
      </div>
      {!data ? <p className="muted">Loading command registry…</p> : (
        <div className="command-list">
          {data.commands.map((command) => {
            const draft = drafts[command.name] ?? draftFromCommand(command)
            const perUserValid = parsedCooldown(draft.perUserSeconds) !== null
            const globalValid = parsedCooldown(draft.globalSeconds) !== null
            const dirty = draftIsDirty(command, draft)
            const busy = busyCommand === command.name
            return (
              <article className={`command-row ${dirty ? 'dirty' : ''}`} key={command.name}>
                <div className="command-title">
                  <strong>{data.command_prefix}{command.name}</strong>
                  <div className="command-meta">
                    {command.hidden && <span className="mini-badge">Hidden</span>}
                    {command.has_saved_override && <span className="mini-badge saved-badge">Saved override</span>}
                    {!command.saved && <span className="mini-badge runtime-badge">Runtime only</span>}
                    {dirty && <span className="mini-badge dirty-badge">Edited</span>}
                    {command.aliases.length > 0 && <span>Aliases: {command.aliases.map((alias) => `${data.command_prefix}${alias}`).join(', ')}</span>}
                  </div>
                </div>
                <label className="toggle-field">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(event) => updateDraft(command.name, { enabled: event.target.checked })}
                  />
                  <span>{draft.enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
                <label>
                  Permission
                  <select value={draft.permission} onChange={(event) => updateDraft(command.name, { permission: event.target.value })}>
                    {data.permissions.map((permission) => <option key={permission} value={permission}>{permission.toLowerCase()}</option>)}
                  </select>
                </label>
                <label>
                  Per-user cooldown
                  <span className="number-with-unit">
                    <input className={perUserValid ? '' : 'invalid'} type="number" min="0" step="0.5" value={draft.perUserSeconds} onChange={(event) => updateDraft(command.name, { perUserSeconds: event.target.value })} />
                    <span>sec</span>
                  </span>
                </label>
                <label>
                  Global cooldown
                  <span className="number-with-unit">
                    <input className={globalValid ? '' : 'invalid'} type="number" min="0" step="0.5" value={draft.globalSeconds} onChange={(event) => updateDraft(command.name, { globalSeconds: event.target.value })} />
                    <span>sec</span>
                  </span>
                </label>
                <div className="row-actions">
                  <button className="secondary" disabled={busy || !dirty || !perUserValid || !globalValid} onClick={() => void runAction(command, 'apply')}>Apply</button>
                  <button className="primary" disabled={busy || (!dirty && command.saved) || !perUserValid || !globalValid} onClick={() => void runAction(command, 'save')}>Save</button>
                  <button className="ghost" disabled={busy || (!dirty && !command.has_saved_override && command.saved)} onClick={() => void runAction(command, 'reset')}>Reset</button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
