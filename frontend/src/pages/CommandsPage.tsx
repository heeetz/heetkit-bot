import { useEffect, useState } from 'react'

import {
  type ActionResult,
  type CommandInfo,
  type CommandsResponse,
  type CustomCommandInfo,
  type CustomCommandInput,
  type CustomCommandsResponse,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'

interface CommandDraft {
  enabled: boolean
  permission: string
  perUserSeconds: string
  globalSeconds: string
}

type Drafts = Record<string, CommandDraft>

interface CustomDraft {
  id: string | null
  name: string
  enabled: boolean
  responses: string[]
  permission: string
  perUserSeconds: string
  globalSeconds: string
  aliases: string
}

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

function newCustomDraft(permission: string): CustomDraft {
  return {
    id: null,
    name: '',
    enabled: true,
    responses: [''],
    permission,
    perUserSeconds: '0',
    globalSeconds: '0',
    aliases: '',
  }
}

function customDraftFromCommand(command: CustomCommandInfo): CustomDraft {
  return {
    id: command.id,
    name: command.name,
    enabled: command.enabled,
    responses: [...command.responses],
    permission: command.permission,
    perUserSeconds: String(command.per_user_seconds),
    globalSeconds: String(command.global_seconds),
    aliases: command.aliases.join(', '),
  }
}

const variableHelp: Record<string, string> = {
  sender: 'The chatter who used the command.',
  target: 'The first argument, or the sender when no target is given.',
  args: 'All words after the command.',
  arg1: 'The first argument. Missing arguments are blank.',
  arg2: 'The second argument. Missing arguments are blank.',
  random_user: 'A recent eligible chatter.',
}

export default function CommandsPage({ active }: CommandsPageProps) {
  const [data, setData] = useState<CommandsResponse | null>(null)
  const [customData, setCustomData] = useState<CustomCommandsResponse | null>(null)
  const [drafts, setDrafts] = useState<Drafts>({})
  const [customDraft, setCustomDraft] = useState<CustomDraft | null>(null)
  const [busyCommand, setBusyCommand] = useState('')
  const [busyCustom, setBusyCustom] = useState(false)
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

  const loadCustomCommands = async () => {
    const api = await waitForBridge()
    setCustomData(await api.get_custom_commands())
  }

  useEffect(() => {
    if (!active) {
      return
    }
    let mounted = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const [response, customResponse] = await Promise.all([
          api.get_commands(),
          api.get_custom_commands(),
        ])
        if (mounted) {
          setData(response)
          setCustomData(customResponse)
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

  const updateCustomDraft = (values: Partial<CustomDraft>) => {
    setCustomDraft((current) => current ? { ...current, ...values } : current)
    setError('')
    setNotice('')
  }

  const saveCustom = async () => {
    if (!customDraft) return
    const name = customDraft.name.trim()
    const responses = customDraft.responses.map((response) => response.trim()).filter(Boolean)
    const perUserSeconds = parsedCooldown(customDraft.perUserSeconds)
    const globalSeconds = parsedCooldown(customDraft.globalSeconds)
    if (!name || responses.length === 0 || perUserSeconds === null || globalSeconds === null) {
      setError('Enter a command name, at least one response, and non-negative cooldowns.')
      return
    }

    const command: CustomCommandInput = {
      id: customDraft.id,
      name,
      enabled: customDraft.enabled,
      responses,
      permission: customDraft.permission,
      per_user_seconds: perUserSeconds,
      global_seconds: globalSeconds,
      aliases: customDraft.aliases.split(/[\n,]/).map((alias) => alias.trim()).filter(Boolean),
    }
    setBusyCustom(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.save_custom_command(command)
      if (!result.ok) throw new Error(result.error ?? 'Could not save custom command.')
      await loadCustomCommands()
      setCustomDraft(null)
      setNotice(`Saved ${customData?.command_prefix ?? '!'}${name}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save custom command.')
    } finally {
      setBusyCustom(false)
    }
  }

  const toggleCustom = async (command: CustomCommandInfo) => {
    setBusyCustom(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.save_custom_command({
        id: command.id,
        name: command.name,
        enabled: !command.enabled,
        responses: command.responses,
        permission: command.permission,
        per_user_seconds: command.per_user_seconds,
        global_seconds: command.global_seconds,
        aliases: command.aliases,
      })
      if (!result.ok) throw new Error(result.error ?? 'Could not update custom command.')
      await loadCustomCommands()
      setCustomDraft((current) => current?.id === command.id ? { ...current, enabled: !command.enabled } : current)
      setNotice(`${customData?.command_prefix ?? '!'}${command.name} ${command.enabled ? 'disabled' : 'enabled'}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not update custom command.')
    } finally {
      setBusyCustom(false)
    }
  }

  const deleteCustom = async (command: CustomCommandInfo) => {
    if (!window.confirm(`Delete ${customData?.command_prefix ?? '!'}${command.name}? This cannot be undone.`)) return
    setBusyCustom(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.delete_custom_command(command.id)
      if (!result.ok) throw new Error(result.error ?? 'Could not delete custom command.')
      await loadCustomCommands()
      setCustomDraft((current) => current?.id === command.id ? null : current)
      setNotice(`Deleted ${customData?.command_prefix ?? '!'}${command.name}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not delete custom command.')
    } finally {
      setBusyCustom(false)
    }
  }

  return (
    <div className="commands-layout">
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
    <section className="card command-editor-card">
      <div className="section-heading">
        <div>
          <p className="label">BUILT-IN COMMANDS</p>
          <h2>Built-in commands</h2>
          <p className="section-copy">Apply changes for this session, save them across restarts, or restore the built-in defaults.</p>
        </div>
        <span className="read-only-badge">{data ? `${data.commands.length} commands` : 'Loading…'}</span>
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
                <Switch
                  className="toggle-field"
                  checked={draft.enabled}
                  ariaLabel={`Enable ${data.command_prefix}${command.name}`}
                  onCheckedChange={(enabled) => updateDraft(command.name, { enabled })}
                >
                  <span>{draft.enabled ? 'Enabled' : 'Disabled'}</span>
                </Switch>
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
    <section className="card command-editor-card">
      <div className="section-heading">
        <div>
          <p className="label">CUSTOM COMMANDS</p>
          <h2>Your commands</h2>
          <p className="section-copy">Create chat responses using safe text templates. Changes here are saved across restarts.</p>
        </div>
        <button className="primary" disabled={!customData || busyCustom} onClick={() => setCustomDraft(newCustomDraft(customData?.permissions[0] ?? 'EVERYONE'))}>New command</button>
      </div>
      {!customData ? <p className="muted">Loading custom commands…</p> : customData.commands.length === 0 ? (
        <div className="empty-state-inline">
          <strong>No custom commands yet</strong>
          <p>Create a command to add a response to chat.</p>
        </div>
      ) : (
        <div className="custom-command-list">
          {customData.commands.map((command) => (
            <article className="custom-command-row" key={command.id}>
              <div className="custom-command-summary">
                <div className="custom-command-heading">
                  <strong>{customData.command_prefix}{command.name}</strong>
                  <span className={`state-pill ${command.enabled ? 'enabled' : ''}`}>{command.enabled ? 'Enabled' : 'Disabled'}</span>
                  {command.response_mode === 'random' && <span className="mini-badge">Random response</span>}
                </div>
                {command.aliases.length > 0 && <p className="command-meta">Aliases: {command.aliases.map((alias) => `${customData.command_prefix}${alias}`).join(', ')}</p>}
                <p className="custom-command-response">{command.responses[0]}</p>
                {command.responses.length > 1 && <small className="muted">{command.responses.length} response templates · one chosen at random</small>}
              </div>
              <div className="row-actions">
                <button className="secondary" disabled={busyCustom} onClick={() => setCustomDraft(customDraftFromCommand(command))}>Edit</button>
                <button className="secondary" disabled={busyCustom} onClick={() => void toggleCustom(command)}>{command.enabled ? 'Disable' : 'Enable'}</button>
                <button className="ghost" disabled={busyCustom} onClick={() => void deleteCustom(command)}>Delete</button>
              </div>
            </article>
          ))}
        </div>
      )}
      {customDraft && customData && (
        <div className="custom-command-editor">
          <div className="section-heading">
            <div>
              <h3>{customDraft.id ? 'Edit command' : 'New command'}</h3>
              <p className="section-copy">Write the name without the {customData.command_prefix} prefix. Separate aliases with commas.</p>
            </div>
            <button className="ghost" disabled={busyCustom} onClick={() => setCustomDraft(null)}>Cancel</button>
          </div>
          <div className="custom-command-fields">
            <label className="form-field">Command name
              <span className="custom-name-input"><span>{customData.command_prefix}</span><input value={customDraft.name} onChange={(event) => updateCustomDraft({ name: event.target.value })} placeholder="hello" /></span>
            </label>
            <label className="form-field">Aliases, separated by commas
              <input value={customDraft.aliases} onChange={(event) => updateCustomDraft({ aliases: event.target.value })} placeholder="hi, hey" />
            </label>
            <label className="form-field">Permission
              <select value={customDraft.permission} onChange={(event) => updateCustomDraft({ permission: event.target.value })}>
                {customData.permissions.map((permission) => <option key={permission} value={permission}>{permission.toLowerCase()}</option>)}
              </select>
            </label>
            <Switch checked={customDraft.enabled} ariaLabel="Enable custom command" onCheckedChange={(enabled) => updateCustomDraft({ enabled })}>
              <span>{customDraft.enabled ? 'Enabled' : 'Disabled'}</span>
            </Switch>
            <label className="form-field">Per-user cooldown (seconds)
              <input type="number" min="0" step="0.5" value={customDraft.perUserSeconds} onChange={(event) => updateCustomDraft({ perUserSeconds: event.target.value })} />
            </label>
            <label className="form-field">Global cooldown (seconds)
              <input type="number" min="0" step="0.5" value={customDraft.globalSeconds} onChange={(event) => updateCustomDraft({ globalSeconds: event.target.value })} />
            </label>
          </div>
          <div className="custom-response-heading">
            <div>
              <h3>Response templates</h3>
              <p className="section-copy">When you add more than one response, the bot chooses one at random.</p>
            </div>
            <button className="secondary" disabled={busyCustom} onClick={() => updateCustomDraft({ responses: [...customDraft.responses, ''] })}>Add response</button>
          </div>
          <div className="custom-response-list">
            {customDraft.responses.map((response, index) => (
              <div className="custom-response-row" key={index}>
                <label className="form-field">Response {index + 1}
                  <textarea rows={3} value={response} onChange={(event) => updateCustomDraft({ responses: customDraft.responses.map((item, itemIndex) => itemIndex === index ? event.target.value : item) })} placeholder="Hello, {sender}!" />
                </label>
                <button className="ghost" disabled={busyCustom || customDraft.responses.length === 1} onClick={() => updateCustomDraft({ responses: customDraft.responses.filter((_, itemIndex) => itemIndex !== index) })}>Remove</button>
              </div>
            ))}
          </div>
          <div className="custom-variable-help">
            <strong>Available variables</strong>
            <p>Insert these into any response. Other variable names are rejected when you save.</p>
            <div className="custom-variable-list">
              {customData.variables.map((variable) => {
                const name = variable.replace(/^\{|\}$/g, '')
                return <div key={variable}><code>{variable.startsWith('{') ? variable : `{${variable}}`}</code><span>{variableHelp[name] ?? 'A positional argument from the command.'}</span></div>
              })}
            </div>
          </div>
          <div className="settings-actions">
            <button className="primary" disabled={busyCustom} onClick={() => void saveCustom()}>{busyCustom ? 'Saving…' : 'Save command'}</button>
          </div>
        </div>
      )}
    </section>
    </div>
  )
}
