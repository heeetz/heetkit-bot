import { useEffect, useRef, useState } from 'react'

import {
  type ActionResult,
  type CommandInfo,
  type CommandsResponse,
  type CustomCommandInfo,
  type CustomCommandInput,
  type CustomCommandsResponse,
  type CustomResponseMode,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Confirmation from '../components/Confirmation'
import Switch from '../components/Switch'

interface CommandDraft {
  enabled: boolean
  permission: string
  perUserSeconds: string
  globalSeconds: string
  responsePool: string | null
  aliases: string
  displayName: string
  burstIntervalMs: string
}

type Drafts = Record<string, CommandDraft>

interface CustomDraft {
  id: string | null
  name: string
  enabled: boolean
  responses: string
  message: string
  responseMode: CustomResponseMode
  burstCount: string
  burstAllowOverride: boolean
  burstIntervalMs: string
  permission: string
  perUserSeconds: string
  globalSeconds: string
  aliases: string
}

interface CommandsPageProps {
  active: boolean
  revealCommand?: string
  onAIEnabledChanged?: (enabled: boolean) => void
}

interface CommandConfirmation {
  title: string
  description: string
  danger?: boolean
}

function draftFromCommand(command: CommandInfo): CommandDraft {
  return {
    enabled: command.enabled,
    permission: command.permission,
    perUserSeconds: String(command.cooldown.per_user_seconds),
    globalSeconds: String(command.cooldown.global_seconds),
    responsePool: command.response_pool ? responsePoolText(command.response_pool) : null,
    aliases: command.aliases.join(', '),
    displayName: command.display_name ?? '',
    burstIntervalMs: String(command.burst_interval_ms ?? 0),
  }
}

function responsePoolText(responsePool: NonNullable<CommandInfo['response_pool']>): string {
  return responsePool.response_mode === 'random'
    ? responsePool.responses.join('\n')
    : responsePool.responses[0] ?? ''
}

function parseResponsePool(responsePool: NonNullable<CommandInfo['response_pool']>, draft: string): string[] {
  if (responsePool.response_mode === 'random') {
    return draft.split(/\r?\n/).map((response) => response.trim()).filter(Boolean)
  }
  return draft.trim() === '' ? [] : [draft]
}

function parsedCooldown(value: string): number | null {
  if (value.trim() === '') {
    return null
  }
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : null
}

function settingsDraftIsDirty(command: CommandInfo, draft: CommandDraft): boolean {
  return draft.enabled !== command.enabled
    || draft.permission !== command.permission
    || parsedCooldown(draft.perUserSeconds) !== command.cooldown.per_user_seconds
    || parsedCooldown(draft.globalSeconds) !== command.cooldown.global_seconds
    || JSON.stringify(parseAliases(draft.aliases)) !== JSON.stringify(command.aliases)
    || draft.displayName !== (command.display_name ?? '')
    || parsedBurstInterval(draft.burstIntervalMs) !== (command.burst_interval_ms ?? 0)
}

function responseDraftIsDirty(command: CommandInfo, draft: CommandDraft): boolean {
  return command.response_pool !== null
    && draft.responsePool !== null
    && responsePoolText(command.response_pool) !== draft.responsePool
}

function draftIsDirty(command: CommandInfo, draft: CommandDraft): boolean {
  return settingsDraftIsDirty(command, draft) || responseDraftIsDirty(command, draft)
}

type CompletedCommandArea = 'settings' | 'responses'

function newCustomDraft(permission: string): CustomDraft {
  return {
    id: null,
    name: '',
    enabled: true,
    responses: '',
    message: '',
    responseMode: 'single',
    burstCount: '1',
    burstAllowOverride: false,
    burstIntervalMs: '0',
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
    responses: command.responses.join('\n'),
    message: command.response_mode === 'random' ? '' : command.responses[0] ?? '',
    responseMode: command.response_mode,
    burstCount: String(command.burst_count ?? 1),
    burstAllowOverride: command.burst_allow_override ?? false,
    burstIntervalMs: String(command.burst_interval_ms ?? 0),
    permission: command.permission,
    perUserSeconds: String(command.per_user_seconds),
    globalSeconds: String(command.global_seconds),
    aliases: command.aliases.join(', '),
  }
}

const variableHelp: Record<string, string> = {
  sender: 'User who invoked the command.',
  target: 'First argument or sender.',
  args: 'Complete command arguments.',
  random_user: 'Random recent eligible chatter.',
}

const commonVariables = ['sender', 'target', 'args', 'random_user']
const burstPermissions = ['MODERATOR', 'BROADCASTER']

function parsedBurstCount(value: string): number | null {
  if (value.trim() === '') return null
  const count = Number(value)
  return Number.isInteger(count) && count >= 1 && count <= 10 ? count : null
}

function parsedBurstInterval(value: string): number | null {
  if (value.trim() === '') return null
  const interval = Number(value)
  return Number.isInteger(interval) && interval >= 0 && interval <= 1000 ? interval : null
}

function parseAliases(value: string): string[] {
  return value.split(/[\n,]/).map((alias) => alias.trim()).filter(Boolean)
}

function canEditIdentity(command: CommandInfo): boolean {
  return !command.hidden && command.name !== 'ask' && command.identity_editable !== false
}

function commandPermissions(data: CommandsResponse, command: CommandInfo): string[] {
  const minimum = command.minimum_permission ?? (command.name === 'tg' ? 'MODERATOR' : command.name === 'erase' ? 'BROADCASTER' : 'USER')
  const levels = ['USER', 'SUBSCRIBER', 'VIP', 'MODERATOR', 'BROADCASTER']
  return data.permissions.filter((permission) => levels.indexOf(permission) >= levels.indexOf(minimum))
}

export default function CommandsPage({ active, revealCommand, onAIEnabledChanged }: CommandsPageProps) {
  const [data, setData] = useState<CommandsResponse | null>(null)
  const [customData, setCustomData] = useState<CustomCommandsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [drafts, setDrafts] = useState<Drafts>({})
  const [customDraft, setCustomDraft] = useState<CustomDraft | null>(null)
  const customBaseline = useRef<CustomDraft | null>(null)
  const customEditorToggle = useRef<HTMLButtonElement>(null)
  const builtinEditorToggles = useRef<Record<string, HTMLButtonElement | null>>({})
  const [busyCommand, setBusyCommand] = useState('')
  const [busyCustom, setBusyCustom] = useState(false)
  const [expandedCommands, setExpandedCommands] = useState<Record<string, boolean>>({})
  const commandSnapshot = useRef<Record<string, CommandInfo>>({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [confirmation, setConfirmation] = useState<CommandConfirmation | null>(null)
  const confirmationResult = useRef<((confirmed: boolean) => void) | null>(null)

  useEffect(() => () => { confirmationResult.current?.(false) }, [])

  useEffect(() => {
    if (active && revealCommand) setExpandedCommands((current) => ({ ...current, [revealCommand]: true }))
  }, [active, revealCommand])

  const confirmAction = (request: CommandConfirmation): Promise<boolean> => new Promise((resolve) => {
    confirmationResult.current = resolve
    setConfirmation(request)
  })

  const finishConfirmation = (confirmed: boolean) => {
    setConfirmation(null)
    confirmationResult.current?.(confirmed)
    confirmationResult.current = null
  }

  const loadCommands = async (completedCommand = '', completedArea?: CompletedCommandArea) => {
    const api = await waitForBridge()
    const response = await api.get_commands()
    const previousCommands = commandSnapshot.current
    setData(response)
    setDrafts((currentDrafts) => Object.fromEntries(response.commands.map((command) => {
      const previousCommand = previousCommands[command.name]
      const previousDraft = currentDrafts[command.name]
      const nextDraft = draftFromCommand(command)
      if (command.name !== completedCommand && previousCommand && previousDraft) {
        if (settingsDraftIsDirty(previousCommand, previousDraft)) {
          if (command.name !== 'ask') nextDraft.enabled = previousDraft.enabled
          nextDraft.permission = previousDraft.permission
          nextDraft.perUserSeconds = previousDraft.perUserSeconds
          nextDraft.globalSeconds = previousDraft.globalSeconds
          nextDraft.aliases = previousDraft.aliases
          nextDraft.displayName = previousDraft.displayName
          nextDraft.burstIntervalMs = previousDraft.burstIntervalMs
        }
        if (responseDraftIsDirty(previousCommand, previousDraft)) {
          nextDraft.responsePool = previousDraft.responsePool
        }
      } else if (command.name === completedCommand && completedArea === 'settings' && previousCommand && previousDraft && responseDraftIsDirty(previousCommand, previousDraft)) {
        nextDraft.responsePool = previousDraft.responsePool
      } else if (command.name === completedCommand && completedArea === 'responses' && previousCommand && previousDraft && settingsDraftIsDirty(previousCommand, previousDraft)) {
        if (command.name !== 'ask') nextDraft.enabled = previousDraft.enabled
        nextDraft.permission = previousDraft.permission
        nextDraft.perUserSeconds = previousDraft.perUserSeconds
        nextDraft.globalSeconds = previousDraft.globalSeconds
        nextDraft.aliases = previousDraft.aliases
        nextDraft.displayName = previousDraft.displayName
        nextDraft.burstIntervalMs = previousDraft.burstIntervalMs
      }
      return [command.name, nextDraft]
    })))
    commandSnapshot.current = Object.fromEntries(response.commands.map((command) => [command.name, command]))
    const ask = response.commands.find((command) => command.name === 'ask')
    if (ask) onAIEnabledChanged?.(ask.enabled)
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
    setLoading(true)
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
          const previousCommands = commandSnapshot.current
          setDrafts((currentDrafts) => Object.fromEntries(response.commands.map((command) => {
            const previousCommand = previousCommands[command.name]
            const previousDraft = currentDrafts[command.name]
            const keepDraft = previousCommand
              && previousDraft
              && draftIsDirty(previousCommand, previousDraft)
            const draft = keepDraft ? { ...previousDraft } : draftFromCommand(command)
            if (command.name === 'ask') draft.enabled = command.enabled
            return [command.name, draft]
          })))
          commandSnapshot.current = Object.fromEntries(response.commands.map((command) => [command.name, command]))
          setError('')
        }
      } catch (reason) {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : 'Could not load commands.')
        }
      } finally {
        if (mounted) setLoading(false)
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

  const changeAIEnabled = async (enabled: boolean) => {
    setBusyCommand('ask')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.set_ai_enabled(enabled)
      if (!result.ok) throw new Error(result.error ?? 'AI command enabled setting could not be saved.')
      await loadCommands()
      setNotice('AI command enabled setting saved. Other command drafts are kept.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI command enabled setting could not be saved.')
    } finally {
      setBusyCommand('')
    }
  }

  const runAction = async (
    command: CommandInfo,
    action: 'save' | 'reset',
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
    const burstInterval = parsedBurstInterval(draft.burstIntervalMs)
    if (action !== 'reset' && command.name === 'tg' && burstInterval === null) {
      setError('Burst interval must be a whole number from 0 to 1000 ms.')
      return
    }
    const metadata = {
      ...(canEditIdentity(command) ? { aliases: parseAliases(draft.aliases), display_name: draft.displayName } : {}),
      ...(command.name === 'tg' ? { burst_interval_ms: burstInterval! } : {}),
    }
    if (action === 'reset' && !await confirmAction({
      title: `Reset !${command.name} settings?`,
      description: 'Reset only this command’s settings to factory defaults, including its enabled state. Its saved message is kept.',
      danger: true,
    })) {
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
      } else {
        result = await api.save_command_settings(
          command.name,
          draft.enabled,
          perUserSeconds!,
          globalSeconds!,
          draft.permission,
          metadata,
        )
      }
      if (!result.ok) {
        throw new Error(result.error ?? 'Command settings could not be updated.')
      }
      await loadCommands(command.name, 'settings')
      setNotice(action === 'save'
          ? `Saved !${command.name}.`
          : `Reset !${command.name} settings to built-in defaults. Its message was kept.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Command settings could not be updated.')
    } finally {
      setBusyCommand('')
    }
  }

  const runResponseAction = async (
    command: CommandInfo,
    action: 'save' | 'reset',
  ) => {
    const draft = drafts[command.name]
    const responsePool = command.response_pool
    if (!draft || !responsePool || draft.responsePool === null) {
      return
    }
    const responses = parseResponsePool(responsePool, draft.responsePool)
    const responseNoun = responsePool.response_mode === 'random' ? 'responses' : 'message'
    if (action !== 'reset' && responses.length === 0) {
      setError(`Keep at least one non-empty ${responseNoun}.`)
      return
    }
    if (action === 'reset' && !await confirmAction({
      title: `Reset !${command.name} ${responseNoun}?`,
      description: 'Replace saved responses with factory defaults. Other command settings are kept.',
      danger: true,
    })) {
      return
    }

    setBusyCommand(command.name)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      let result: ActionResult
      if (action === 'reset') {
        result = await api.reset_command_responses(command.name)
      } else {
        result = await api.save_command_responses(command.name, responses)
      }
      if (!result.ok) {
        throw new Error(result.error ?? `Command ${responseNoun} could not be updated.`)
      }
      await loadCommands(command.name, 'responses')
      setNotice(action === 'save'
          ? `Saved !${command.name} ${responseNoun}.`
          : `Reset !${command.name} ${responseNoun} to built-in defaults.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Command ${responseNoun} could not be updated.`)
    } finally {
      setBusyCommand('')
    }
  }

  const updateCustomDraft = (values: Partial<CustomDraft>) => {
    setCustomDraft((current) => current ? { ...current, ...values } : current)
    setError('')
    setNotice('')
  }

  const replaceCustomDraft = async (draft: CustomDraft | null) => {
    if (customDraft && JSON.stringify(customDraft) !== JSON.stringify(customBaseline.current)
      && !await confirmAction({ title: 'Discard unsaved command changes?', description: 'Your current draft will be lost.', danger: true })) return
    customBaseline.current = draft ? { ...draft } : null
    setCustomDraft(draft)
    if (!draft) customEditorToggle.current?.focus()
    setError('')
    setNotice('')
  }

  const changeCustomMode = (responseMode: CustomResponseMode) => {
    if (!customDraft) return
    updateCustomDraft({
      responseMode,
      responses: customDraft.responses.trim() ? customDraft.responses : customDraft.message,
      message: customDraft.message.trim() ? customDraft.message : customDraft.responses.split(/\r?\n/).map((response) => response.trim()).find(Boolean) ?? '',
      permission: responseMode === 'burst' && !burstPermissions.includes(customDraft.permission)
        ? 'MODERATOR' : customDraft.permission,
    })
  }

  const saveCustom = async () => {
    if (!customDraft) return
    const name = customDraft.name.trim()
    const responses = customDraft.responseMode === 'random'
      ? customDraft.responses.split(/\r?\n/).map((response) => response.trim()).filter(Boolean)
      : customDraft.message.trim() ? [customDraft.message] : []
    const perUserSeconds = parsedCooldown(customDraft.perUserSeconds)
    const globalSeconds = parsedCooldown(customDraft.globalSeconds)
    if (!name || responses.length === 0 || perUserSeconds === null || globalSeconds === null) {
      setError('Enter a command name, at least one response, and non-negative cooldowns.')
      return
    }
    if (responses.length > 10) {
      setError('Keep 1 to 10 response templates.')
      return
    }
    const burstCount = parsedBurstCount(customDraft.burstCount)
    const burstInterval = parsedBurstInterval(customDraft.burstIntervalMs)
    if (customDraft.responseMode === 'burst' && (burstCount === null || !burstPermissions.includes(customDraft.permission))) {
      setError('Burst requires a whole repeat count from 1 to 10 and Moderator or Broadcaster permission.')
      return
    }
    if (customDraft.responseMode === 'burst' && burstInterval === null) {
      setError('Burst interval must be a whole number from 0 to 1000 ms.')
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
      aliases: parseAliases(customDraft.aliases),
      response_mode: customDraft.responseMode,
      ...(customDraft.responseMode === 'burst' ? { burst_count: burstCount!, burst_allow_override: customDraft.burstAllowOverride, burst_interval_ms: burstInterval! } : {}),
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
      customBaseline.current = null
      customEditorToggle.current?.focus()
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
        response_mode: command.response_mode,
        ...(command.response_mode === 'burst' ? { burst_count: command.burst_count ?? 1, burst_allow_override: command.burst_allow_override ?? false, burst_interval_ms: command.burst_interval_ms ?? 0 } : {}),
      })
      if (!result.ok) throw new Error(result.error ?? 'Could not update custom command.')
      await loadCustomCommands()
      setCustomDraft((current) => current?.id === command.id ? { ...current, enabled: !command.enabled } : current)
      if (customBaseline.current?.id === command.id) customBaseline.current = { ...customBaseline.current, enabled: !command.enabled }
      setNotice(`${customData?.command_prefix ?? '!'}${command.name} ${command.enabled ? 'disabled' : 'enabled'}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not update custom command.')
    } finally {
      setBusyCustom(false)
    }
  }

  const deleteCustom = async (command: CustomCommandInfo) => {
    if (!await confirmAction({
      title: `Delete ${customData?.command_prefix ?? '!'}${command.name}?`,
      description: 'Permanently delete this custom command. This cannot be undone.',
      danger: true,
    })) return
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

  const runFactoryAction = async (action: 'remove' | 'restore' | 'resetAll', command?: CommandInfo) => {
    const hasDirtyDraft = command && drafts[command.name] && draftIsDirty(command, drafts[command.name])
    const request: CommandConfirmation = action === 'remove' ? {
      title: `Remove and disable !${command!.name}?`,
      description: `Disable and hide this built-in command. You can restore it from Factory commands.${hasDirtyDraft ? ' Unsaved changes will be discarded.' : ''}`,
      danger: true,
    } : action === 'restore' ? {
      title: `Restore defaults and enable !${command!.name}?`,
      description: `Replace this command’s settings with factory defaults and enable it. Its saved message is kept.${hasDirtyDraft ? ' Unsaved changes will be discarded.' : ''}`,
      danger: true,
    } : {
      title: 'Restore all factory defaults?',
      description: 'Replace all built-in settings and messages with factory defaults, including enabled states. Removed commands return. Unsaved built-in drafts will be discarded. Custom commands are kept.',
      danger: true,
    }
    if (!await confirmAction(request)) return
    setBusyCommand(command?.name ?? 'factory')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = action === 'remove'
        ? await api.remove_builtin_command(command!.name)
        : action === 'restore' ? await api.restore_builtin_command(command!.name)
          : await api.reset_all_builtin_commands()
      if (!result.ok) {
        // Settings and response pools have independent atomic stores.
        if (action === 'resetAll') await loadCommands()
        throw new Error(result.error ?? 'Factory command could not be updated.')
      }
      if (action === 'resetAll') {
        commandSnapshot.current = {}
        setDrafts({})
      }
      await loadCommands(command?.name)
      if (command) setExpandedCommands((current) => ({ ...current, [command.name]: false }))
      setNotice(action === 'remove'
        ? `Removed and disabled !${command!.name}. Restore it from Factory commands.`
        : action === 'restore' ? `Restored !${command!.name} default settings and enabled it. Its saved message was kept.` : 'Restored all factory command settings and messages.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Factory command could not be updated.')
    } finally {
      setBusyCommand('')
    }
  }

  const renderBuiltin = (command: CommandInfo) => {
    if (!data) return null
    const draft = drafts[command.name] ?? draftFromCommand(command)
    const perUserValid = parsedCooldown(draft.perUserSeconds) !== null
    const globalValid = parsedCooldown(draft.globalSeconds) !== null
    const intervalValid = command.name !== 'tg' || parsedBurstInterval(draft.burstIntervalMs) !== null
    const settingsDirty = settingsDraftIsDirty(command, draft)
    const responseDirty = responseDraftIsDirty(command, draft)
    const dirty = settingsDirty || responseDirty
    const responsePool = command.response_pool
    const responseDraft = draft.responsePool
    const parsedResponses = responsePool && responseDraft !== null ? parseResponsePool(responsePool, responseDraft) : []
    const responseValid = parsedResponses.length > 0
    const isRandom = responsePool?.response_mode === 'random'
    const expanded = Boolean(expandedCommands[command.name])
    const busy = busyCommand !== ''
    const detailsId = `command-details-${command.name}`
    return (
      <article className={`command-card ${dirty ? 'dirty' : ''}`} key={command.name} id={`command-editor-${command.name}`}>
        <div className="command-summary-row">
          <button
            type="button"
            className="command-summary"
            ref={(element) => { builtinEditorToggles.current[command.name] = element }}
            aria-expanded={expanded}
            aria-controls={detailsId}
            aria-label={`${expanded ? 'Collapse' : 'Edit'} ${data.command_prefix}${command.name}`}
            onClick={() => setExpandedCommands((current) => ({ ...current, [command.name]: !expanded }))}
          >
            <span className="command-summary-title">
              <strong>{data.command_prefix}{command.name}</strong>
              {command.display_name && <span className="command-display-name">{command.display_name}</span>}
              <span className={`state-pill ${draft.enabled ? 'enabled' : ''}`}>{draft.enabled ? 'Enabled' : 'Disabled'}</span>
              {!command.available && <span className="state-pill unavailable-pill">Unavailable</span>}
            </span>
            <span className="command-summary-meta">
              {command.hidden && <span className="mini-badge">Hidden</span>}
              {(command.has_saved_override || responsePool?.has_saved_override) && <span className="mini-badge saved-badge">Saved override</span>}
              {(!command.saved || (responsePool && !responsePool.saved)) && <span className="mini-badge runtime-badge">Runtime only</span>}
              {dirty && <span className="mini-badge dirty-badge">Edited</span>}
              <span>Permission: {draft.permission.toLowerCase()}</span>
              <span>Cooldown: {draft.perUserSeconds}s / {draft.globalSeconds}s</span>
              {command.aliases.length > 0 && <span>Aliases: {command.aliases.map((alias) => `${data.command_prefix}${alias}`).join(', ')}</span>}
            </span>
            <span className="command-expand-label" aria-hidden="true">{expanded ? '▴' : 'Edit'}</span>
          </button>
        </div>
        {expanded && <div className="command-details" id={detailsId}>
          <div className="command-fields">
            <Switch
              className="toggle-field"
              checked={draft.enabled}
              disabled={busy}
              ariaLabel={`Enable ${data.command_prefix}${command.name}`}
              onCheckedChange={(enabled) => command.name === 'ask'
                ? void changeAIEnabled(enabled) : updateDraft(command.name, { enabled })}
            >
              <span>{draft.enabled ? 'Enabled' : 'Disabled'}</span>
            </Switch>
            <label>
              Permission
              <select disabled={busy} value={draft.permission} onChange={(event) => updateDraft(command.name, { permission: event.target.value })}>
                {commandPermissions(data, command).map((permission) => <option key={permission} value={permission}>{permission.toLowerCase()}</option>)}
              </select>
            </label>
            <label>
              Per-user cooldown
              <span className="number-with-unit">
                <input disabled={busy} className={perUserValid ? '' : 'invalid'} type="number" min="0" step="0.5" value={draft.perUserSeconds} onChange={(event) => updateDraft(command.name, { perUserSeconds: event.target.value })} />
                <span>sec</span>
              </span>
            </label>
            <label>
              Global cooldown
              <span className="number-with-unit">
                <input disabled={busy} className={globalValid ? '' : 'invalid'} type="number" min="0" step="0.5" value={draft.globalSeconds} onChange={(event) => updateDraft(command.name, { globalSeconds: event.target.value })} />
                <span>sec</span>
              </span>
            </label>
          </div>
          {command.name === 'ask' && <p className="setting-effect">Enabled state is saved immediately and shared with Dashboard and AI. Save applies only your other settings edits.</p>}
          {canEditIdentity(command) && <div className="command-identity-fields">
            <label className="form-field">Name in UI
              <input disabled={busy} value={draft.displayName} maxLength={80} onChange={(event) => updateDraft(command.name, { displayName: event.target.value })} placeholder="Optional label" />
              <span className="custom-field-hint">Label only; command stays {data.command_prefix}{command.name}.</span>
            </label>
            <label className="form-field">Aliases, separated by commas
              <input disabled={busy} value={draft.aliases} onChange={(event) => updateDraft(command.name, { aliases: event.target.value })} placeholder="Optional alternate commands" />
            </label>
          </div>}
          {command.name === 'tg' && <label className="form-field command-burst-interval">Burst interval (ms)
            <input disabled={busy} type="number" min="0" max="1000" step="1" aria-invalid={!intervalValid} className={intervalValid ? '' : 'invalid'} value={draft.burstIntervalMs} onChange={(event) => updateDraft(command.name, { burstIntervalMs: event.target.value })} />
            <span className="custom-field-hint">0–1000 ms between request starts; 0 sends concurrently.</span>
          </label>}
          {command.hidden && <p className="command-behavior-note">Protected administrative command; identity is fixed.</p>}
          {command.help_text && <p className="command-behavior-note">{command.help_text}</p>}
          {!responsePool && <p className="command-behavior-note">Dynamic response; cannot be edited as a text template.</p>}
          {(command.minimum_permission && command.minimum_permission !== 'USER') && <p className="command-behavior-note">Minimum permission: {command.minimum_permission.toLowerCase()}.</p>}
          {!command.available && <p className="command-unavailable"><strong>Unavailable:</strong> {command.unavailable_reason ?? 'The optional AI provider is not configured. Add a key to enable AI features.'}</p>}
          {!command.hidden && responsePool && responseDraft !== null && <div className="command-response-editor">
            <div className="custom-response-heading">
              <div>
                <h3>{isRandom ? 'Response pool' : 'Command message'}</h3>
                <p className="section-copy">{isRandom
                  ? `One response per line; one is chosen at random. Maximum ${responsePool.max_responses}.`
                  : 'The full message is sent as one response.'}</p>
              </div>
              <div className="command-response-badges">
                {responsePool.has_saved_override && <span className="mini-badge saved-badge">Saved override</span>}
                {!responsePool.saved && <span className="mini-badge runtime-badge">Runtime only</span>}
                {responseDirty && <span className="mini-badge dirty-badge">Edited</span>}
              </div>
            </div>
            <label className="form-field command-response-field">{isRandom ? 'Responses' : 'Message'}
              <textarea
                className="command-response-textarea"
                disabled={busy}
                rows={isRandom ? 7 : 5}
                value={responseDraft}
                onChange={(event) => updateDraft(command.name, { responsePool: event.target.value })}
                placeholder={isRandom ? 'One response per line' : 'Command message'}
              />
            </label>
            <p className="command-meta">{isRandom ? `${parsedResponses.length} responses ready` : responseValid ? 'Message ready' : 'Message required'}</p>
          </div>}
          <div className="command-editor-actions">
            {!command.hidden && responsePool && responseDraft !== null && <div className="command-response-footer">
              <span className="command-action-hint">{isRandom ? 'Responses' : 'Message'}</span>
              <div className="command-action-group" role="group" aria-label={`${data.command_prefix}${command.name} response actions`}>
                <button className="ghost" disabled={busy || (!responseDirty && !responsePool.has_saved_override && responsePool.saved)} onClick={() => void runResponseAction(command, 'reset')}>{isRandom ? 'Reset responses' : 'Reset message'}</button>
                <button className="primary" disabled={busy || (!responseDirty && responsePool.saved) || !responseValid} onClick={() => void runResponseAction(command, 'save')}>Save</button>
              </div>
            </div>}
            <div className="command-action-footer">
              <span className="command-action-hint">Settings</span>
              <div className="command-action-group" role="group" aria-label={`${data.command_prefix}${command.name} settings actions`}>
                {!command.hidden && <button className="ghost command-remove" disabled={busy} onClick={() => void runFactoryAction('remove', command)}>Remove and disable</button>}
                <button className="secondary" disabled={busy} onClick={() => { setExpandedCommands((current) => ({ ...current, [command.name]: false })); builtinEditorToggles.current[command.name]?.focus() }}>Collapse editor</button>
                <button className="ghost" disabled={busy || (!settingsDirty && !command.has_saved_override && command.saved)} onClick={() => void runAction(command, 'reset')}>Reset settings</button>
                <button className="primary" disabled={busy || (!settingsDirty && command.saved) || !perUserValid || !globalValid || !intervalValid} onClick={() => void runAction(command, 'save')}>Save</button>
              </div>
            </div>
          </div>
          <p className="settings-hint">Collapse editor keeps your unsaved draft. Settings and messages are saved or reset separately.</p>
        </div>}
      </article>
    )

  }

  return (
    <div className="commands-layout" aria-busy={loading}>
      {confirmation && <Confirmation {...confirmation} onConfirm={() => finishConfirmation(true)} onCancel={() => finishConfirmation(false)} />}
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
    <section className="card command-editor-card" id="custom-commands">
      <div className="section-heading">
        <div>
          <p className="label">CUSTOM COMMANDS</p>
          <h2>Your commands</h2>
          <p className="section-copy">Create responses with template variables. Save applies changes immediately.</p>
        </div>
        <button ref={customEditorToggle} className="primary" disabled={!customData || busyCustom} aria-expanded={Boolean(customDraft)} aria-controls="custom-command-editor" onClick={() => void replaceCustomDraft(customDraft ? null : newCustomDraft(customData?.permissions[0] ?? 'USER'))}>{customDraft ? 'Discard draft' : 'New command'}</button>
      </div>
      {customDraft && customData && (
        <div className="custom-command-editor" id="custom-command-editor">
          <div className="section-heading">
            <div>
              <h3>{customDraft.id ? 'Edit command' : 'New command'}</h3>
              <p className="section-copy">Names omit {customData.command_prefix}; separate aliases with commas.</p>
            </div>
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
                {customData.permissions.filter((permission) => customDraft.responseMode !== 'burst' || burstPermissions.includes(permission)).map((permission) => <option key={permission} value={permission}>{permission.toLowerCase()}</option>)}
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
              <h3>Response</h3>
            </div>
          </div>
          <label className="form-field custom-response-mode">Response mode
            <select value={customDraft.responseMode} onChange={(event) => changeCustomMode(event.target.value as CustomResponseMode)}>
              <option value="single">Single</option>
              <option value="random">Random</option>
              <option value="burst">Burst</option>
            </select>
          </label>
          <p className="custom-mode-example">
            {customDraft.responseMode === 'random'
              ? `${customData.command_prefix}${customDraft.name || 'hello'} picks one response at random. Enter 1 to 10 non-empty lines; blank lines are ignored.`
              : customDraft.responseMode === 'burst'
                ? `${customData.command_prefix}${customDraft.name || 'promo'} sends this message ${customDraft.burstCount || 'N'} times ${parsedBurstInterval(customDraft.burstIntervalMs) === 0 ? 'concurrently' : `with ${customDraft.burstIntervalMs || 'N'} ms between request starts`}. Requires Moderator or Broadcaster permission.`
                : `${customData.command_prefix}${customDraft.name || 'hello'} sends this message once.`}
          </p>
          <label className="form-field custom-response-field">{customDraft.responseMode === 'random' ? 'Responses' : 'Message'}
            <textarea className="custom-response-textarea" rows={customDraft.responseMode === 'random' ? 7 : 4} value={customDraft.responseMode === 'random' ? customDraft.responses : customDraft.message} onChange={(event) => updateCustomDraft(customDraft.responseMode === 'random' ? { responses: event.target.value } : { message: event.target.value })} placeholder="Hello, {sender}!" />
          </label>
          {customDraft.responseMode === 'burst' && <div className="custom-burst-controls">
            <label className="form-field">Default repeat count
              <input type="number" min="1" max="10" step="1" className={parsedBurstCount(customDraft.burstCount) === null ? 'invalid' : ''} aria-invalid={parsedBurstCount(customDraft.burstCount) === null} value={customDraft.burstCount} onChange={(event) => updateCustomDraft({ burstCount: event.target.value })} />
              <span className="custom-field-hint">1–10 copies.</span>
            </label>
            <label className="form-field">Burst interval (ms)
              <input type="number" min="0" max="1000" step="1" className={parsedBurstInterval(customDraft.burstIntervalMs) === null ? 'invalid' : ''} aria-invalid={parsedBurstInterval(customDraft.burstIntervalMs) === null} value={customDraft.burstIntervalMs} onChange={(event) => updateCustomDraft({ burstIntervalMs: event.target.value })} />
              <span className="custom-field-hint">0–1000 ms between request starts; 0 sends concurrently.</span>
            </label>
            <div>
              <Switch checked={customDraft.burstAllowOverride} ariaLabel="Allow argument count override" onCheckedChange={(burstAllowOverride) => updateCustomDraft({ burstAllowOverride })}>
                <span>Allow argument count override</span>
              </Switch>
              <p className="custom-field-hint">{customDraft.burstAllowOverride
                ? `${customData.command_prefix}${customDraft.name || 'promo'} 10 sends 10 copies. The first argument sets the count; a target can follow, e.g. 10 @alice.`
                : 'Uses the default repeat count for every invocation.'}</p>
            </div>
          </div>}
          <div className="custom-variable-help">
            <strong>Available variables</strong>
            <p>Use these in any message.</p>
            <div className="custom-variable-list">
              {commonVariables.filter((name) => customData.variables.some((variable) => variable.replace(/^\{|\}$/g, '') === name)).map((name) => <div key={name}><code>{`{${name}}`}</code><span>{variableHelp[name]}</span></div>)}
            </div>
            <details className="custom-advanced-variables">
              <summary>Advanced variables</summary>
              <div className="custom-variable-list">
                {customData.variables.map((variable) => variable.replace(/^\{|\}$/g, '')).filter((name) => !commonVariables.includes(name)).map((name) => <div key={name}><code>{`{${name}}`}</code><span>{/^arg[1-9]$/.test(name) ? `Argument ${name.slice(3)}; blank when missing.` : 'A supported template variable.'}</span></div>)}
              </div>
            </details>
          </div>
          <div className="settings-actions custom-editor-actions">
            <button className="primary" disabled={busyCustom || (customDraft.responseMode === 'burst' && (parsedBurstCount(customDraft.burstCount) === null || parsedBurstInterval(customDraft.burstIntervalMs) === null))} onClick={() => void saveCustom()}>{busyCustom ? 'Saving…' : 'Save command'}</button>
            <button className="secondary" disabled={busyCustom} onClick={() => void replaceCustomDraft(null)}>Discard and close</button>
          </div>
        </div>
      )}
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
                  {command.response_mode === 'burst' && <span className="mini-badge">Burst · {command.burst_count ?? 1} copies</span>}
                </div>
                {command.aliases.length > 0 && <p className="command-meta">Aliases: {command.aliases.map((alias) => `${customData.command_prefix}${alias}`).join(', ')}</p>}
                <p className="custom-command-response">{command.responses[0]}</p>
                {command.responses.length > 1 && <small className="muted">{command.responses.length} response templates · one chosen at random</small>}
                {command.response_mode === 'burst' && <small className="muted">{command.burst_allow_override ? 'Argument count override enabled' : 'Default repeat count'} · {command.burst_interval_ms ?? 0} ms interval · {command.permission.toLowerCase()}</small>}
              </div>
              <div className="row-actions">
                <button className="secondary" disabled={busyCustom} onClick={() => replaceCustomDraft(customDraftFromCommand(command))}>Edit</button>
                <button className="secondary" disabled={busyCustom} onClick={() => void toggleCustom(command)}>{command.enabled ? 'Disable' : 'Enable'}</button>
                <button className="ghost" disabled={busyCustom} onClick={() => void deleteCustom(command)}>Delete</button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
    <section className="card command-editor-card" id="builtin-commands">
      <div className="section-heading">
        <div>
          <p className="label">BUILT-IN COMMANDS</p>
          <h2>Built-in commands</h2>
          <p className="section-copy">Save applies changes immediately and keeps them across restarts.</p>
        </div>
        <span className="read-only-badge">{data ? `${data.commands.filter((command) => !command.hidden && !command.removed).length} active commands` : 'Loading…'}</span>
      </div>
      {!data ? <p className="muted">Loading command registry…</p> : (
        <div className="command-list">
          {data.commands.filter((command) => !command.hidden && !command.removed).map(renderBuiltin)}
        </div>
      )}
      {data && <details className="factory-commands">
        <summary>Factory commands</summary>
        <p className="section-copy">Individual restoration replaces settings with defaults and enables the command, keeping its saved message. Full restoration resets every built-in setting and message.</p>
        <div className="factory-command-list">
          {data.commands.filter((command) => !command.hidden).map((command) => <div className="factory-command-row" key={command.name} id={command.removed ? `command-editor-${command.name}` : undefined}>
            <div><strong>{data.command_prefix}{command.name}</strong><span className="custom-field-hint">{command.removed ? 'Removed' : !command.enabled ? 'Disabled' : 'Active'}{command.has_saved_override ? ' · Customized settings' : ''}</span></div>
            <button className="secondary" disabled={busyCommand !== '' || (!command.removed && !command.has_saved_override && command.saved)} onClick={() => void runFactoryAction('restore', command)}>Restore defaults and enable</button>
          </div>)}
        </div>
        <div className="settings-actions"><button className="ghost" disabled={busyCommand !== ''} onClick={() => void runFactoryAction('resetAll')}>Restore all factory defaults</button></div>
        <p className="custom-field-hint">Complete reset restores built-in settings and messages. Your custom commands are kept.</p>
      </details>}
      {data && data.commands.some((command) => command.hidden) && <details className="factory-commands administrative-commands">
        <summary>Administrative commands</summary>
        <p className="section-copy">Protected commands retain their original names, minimum permissions and implementations.</p>
        <div className="command-list">{data.commands.filter((command) => command.hidden).map(renderBuiltin)}</div>
      </details>}
    </section>
    </div>
  )
}
