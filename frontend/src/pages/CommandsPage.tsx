import { useEffect, useRef, useState } from 'react'
import { useRestartDraft } from '../desktopRestart'

import {
  type CommandInfo,
  type ChatReaction,
  type ChatReactionsResponse,
  type CommandsResponse,
  type CustomCommandInfo,
  type CustomCommandInput,
  type CustomCommandsResponse,
  type CustomResponseMode,
  type StreamAvailability,
  type SendAs,
  isBrowserMode,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Confirmation from '../components/Confirmation'
import { Select } from '../components/Select'
import Switch from '../components/Switch'
import HelpTip from '../components/HelpTip'
import AnnouncementsPanel from '../components/AnnouncementsPanel'
import ChatReactions, { newReactionDraft, probabilityText, reactionDraftFrom, type ReactionDraft } from '../components/ChatReactions'
import CommandList, { type CommandEntry } from '../components/CommandList'
import CommandEditorDialog, { type CommandEditorSection } from '../components/CommandEditorDialog'
import { commandEditorCopy as copy } from '../i18n/commands.en'
import CommandRestrictions from '../components/CommandRestrictions'
import OptOutManagement from '../components/OptOutManagement'

interface CommandDraft {
  primaryName: string
  enabled: boolean
  permission: string
  perUserSeconds: string
  globalSeconds: string
  responsePool: string | null
  aliases: string
  displayName: string
  burstIntervalMs: string
  burstMaxCount: string
  streamAvailability: StreamAvailability
  sendAs: SendAs
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
  streamAvailability: StreamAvailability
  sendAs: SendAs
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

const DEFAULT_TG_BURST_MAX_COUNT = 10

const streamAvailabilityOptions: { value: StreamAvailability; label: string }[] = [
  { value: 'anytime', label: 'Anytime' },
  { value: 'live_only', label: 'Live only' },
  { value: 'offline_only', label: 'Offline only' },
]

const sendAsOptions: { value: SendAs; label: string }[] = [
  { value: 'chat', label: 'Chat message' },
  { value: 'mention', label: 'Mention sender' },
  { value: 'reply', label: 'Reply to message' },
]

function SendAsField({ id, value, onChange, disabled }: { id: string; value: SendAs; onChange: (value: SendAs) => void; disabled?: boolean }) {
  return <div className="form-field">
    <div className="custom-field-label">
      <label htmlFor={id}>Send as</label>
      <HelpTip label="Send as">Chat message sends plain chat. Mention sender adds an @username. Reply to message uses Twitch’s reply thread. If the incoming message has no reply ID, it sends as plain chat.</HelpTip>
    </div>
    <Select id={id} value={value} onChange={(next) => onChange(next as SendAs)} options={sendAsOptions} disabled={disabled} />
  </div>
}

function builtinSendAs(command: CommandInfo): SendAs {
  return command.send_as ?? command.default_send_as ?? 'chat'
}

function streamAvailability(value: StreamAvailability | undefined): StreamAvailability {
  return value ?? 'anytime'
}

function tgBurstMaxCount(command: CommandInfo): number {
  const count = command.burst_max_count ?? command.default_settings.burst_max_count ?? DEFAULT_TG_BURST_MAX_COUNT
  return Number.isInteger(count) && count >= 1 && count <= 20 ? count : DEFAULT_TG_BURST_MAX_COUNT
}

function draftFromCommand(command: CommandInfo): CommandDraft {
  return {
    primaryName: command.primary_name ?? command.name,
    enabled: command.enabled,
    permission: command.permission,
    perUserSeconds: String(command.cooldown.per_user_seconds),
    globalSeconds: String(command.cooldown.global_seconds),
    responsePool: command.response_pool ? responsePoolText(command.response_pool) : null,
    aliases: command.aliases.join(', '),
    displayName: command.display_name ?? '',
    burstIntervalMs: String(command.burst_interval_ms ?? 0),
    burstMaxCount: String(tgBurstMaxCount(command)),
    streamAvailability: streamAvailability(command.stream_availability),
    sendAs: builtinSendAs(command),
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
  return draft.primaryName !== (command.primary_name ?? command.name)
    || draft.enabled !== command.enabled
    || draft.permission !== command.permission
    || parsedCooldown(draft.perUserSeconds) !== command.cooldown.per_user_seconds
    || parsedCooldown(draft.globalSeconds) !== command.cooldown.global_seconds
    || JSON.stringify(parseAliases(draft.aliases)) !== JSON.stringify(command.aliases)
    || draft.displayName !== (command.display_name ?? '')
    || parsedBurstInterval(draft.burstIntervalMs) !== (command.burst_interval_ms ?? 0)
    || (command.name === 'tg' && parsedBurstMaxCount(draft.burstMaxCount) !== tgBurstMaxCount(command))
    || draft.streamAvailability !== streamAvailability(command.stream_availability)
    || draft.sendAs !== builtinSendAs(command)
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
    streamAvailability: 'anytime',
    sendAs: 'chat',
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
    streamAvailability: streamAvailability(command.stream_availability),
    sendAs: command.send_as ?? 'chat',
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

function parsedBurstMaxCount(value: string): number | null {
  if (value.trim() === '') return null
  const count = Number(value)
  return Number.isInteger(count) && count >= 1 && count <= 20 ? count : null
}

function parseAliases(value: string): string[] {
  return value.split(/[\n,]/).map((alias) => alias.trim()).filter(Boolean)
}

function canEditIdentity(command: CommandInfo): boolean {
  return command.identity_editable !== false
}

function commandPermissions(data: CommandsResponse, command: CommandInfo): string[] {
  const minimum = command.minimum_permission ?? (command.name === 'tg' ? 'MODERATOR' : command.name === 'erase' ? 'MODERATOR' : 'USER')
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
  const [reactionData, setReactionData] = useState<ChatReactionsResponse | null>(null)
  const [reactionDraft, setReactionDraft] = useState<ReactionDraft | null>(null)
  const reactionBaseline = useRef<ReactionDraft | null>(null)
  const [editingBuiltin, setEditingBuiltin] = useState<string | null>(null)
  const [busyReaction, setBusyReaction] = useState(false)
  const customDirty = Boolean(customDraft && JSON.stringify(customDraft) !== JSON.stringify(customBaseline.current))
  const reactionDirty = Boolean(reactionDraft && JSON.stringify(reactionDraft) !== JSON.stringify(reactionBaseline.current))
  useRestartDraft('Commands', Boolean(
    customDirty || reactionDirty
    || data?.commands.some((command) => drafts[command.name] && draftIsDirty(command, drafts[command.name])),
  ))
  const customResponse = useRef<HTMLTextAreaElement>(null)
  const [busyCommand, setBusyCommand] = useState('')
  const [busyCustom, setBusyCustom] = useState(false)
  const commandSnapshot = useRef<Record<string, CommandInfo>>({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [confirmation, setConfirmation] = useState<CommandConfirmation | null>(null)
  const confirmationResult = useRef<((confirmed: boolean) => void) | null>(null)

  useEffect(() => () => { confirmationResult.current?.(false) }, [])

  useEffect(() => {
    if (active && revealCommand) setEditingBuiltin(revealCommand)
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
          nextDraft.enabled = previousDraft.enabled
          nextDraft.permission = previousDraft.permission
          nextDraft.perUserSeconds = previousDraft.perUserSeconds
          nextDraft.globalSeconds = previousDraft.globalSeconds
          nextDraft.aliases = previousDraft.aliases
          nextDraft.primaryName = previousDraft.primaryName
          nextDraft.displayName = previousDraft.displayName
          nextDraft.burstIntervalMs = previousDraft.burstIntervalMs
          nextDraft.burstMaxCount = previousDraft.burstMaxCount
          nextDraft.streamAvailability = previousDraft.streamAvailability
          nextDraft.sendAs = previousDraft.sendAs
        }
        if (responseDraftIsDirty(previousCommand, previousDraft)) {
          nextDraft.responsePool = previousDraft.responsePool
        }
      } else if (command.name === completedCommand && completedArea === 'settings' && previousCommand && previousDraft && responseDraftIsDirty(previousCommand, previousDraft)) {
        nextDraft.responsePool = previousDraft.responsePool
      } else if (command.name === completedCommand && completedArea === 'responses' && previousCommand && previousDraft && settingsDraftIsDirty(previousCommand, previousDraft)) {
        nextDraft.enabled = previousDraft.enabled
        nextDraft.permission = previousDraft.permission
        nextDraft.perUserSeconds = previousDraft.perUserSeconds
        nextDraft.globalSeconds = previousDraft.globalSeconds
        nextDraft.aliases = previousDraft.aliases
        nextDraft.primaryName = previousDraft.primaryName
        nextDraft.displayName = previousDraft.displayName
        nextDraft.burstIntervalMs = previousDraft.burstIntervalMs
        nextDraft.burstMaxCount = previousDraft.burstMaxCount
        nextDraft.streamAvailability = previousDraft.streamAvailability
        nextDraft.sendAs = previousDraft.sendAs
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
        const [response, customResponse, reactionResponse] = await Promise.all([
          api.get_commands(),
          api.get_custom_commands(),
          api.get_message_triggers().catch((reason: unknown) => ({ ok: false, triggers: [], revision: '', error: reason instanceof Error ? reason.message : 'Could not load chat reactions.' })),
        ])
        if (mounted) {
          setData(response)
          setCustomData(customResponse)
          setReactionData(reactionResponse.ok ? reactionResponse : null)
          const previousCommands = commandSnapshot.current
          setDrafts((currentDrafts) => Object.fromEntries(response.commands.map((command) => {
            const previousCommand = previousCommands[command.name]
            const previousDraft = currentDrafts[command.name]
            const keepDraft = previousCommand
              && previousDraft
              && draftIsDirty(previousCommand, previousDraft)
            const draft = keepDraft ? { ...previousDraft } : draftFromCommand(command)
            return [command.name, draft]
          })))
          commandSnapshot.current = Object.fromEntries(response.commands.map((command) => [command.name, command]))
          setError(reactionResponse.ok ? '' : reactionResponse.error ?? 'Could not load chat reactions.')
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

  const focusListIfNeeded = () => window.requestAnimationFrame(() => {
    if (active && document.activeElement === document.body) document.getElementById('command-list-search')?.focus()
  })

  const toggleBuiltin = async (command: CommandInfo, enabled: boolean) => {
    setBusyCommand(command.name)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.save_builtin_enabled(command.name, enabled)
      if (!result.ok) throw new Error(result.error ?? 'Could not change command status.')
      await loadCommands()
      setNotice(`${data?.command_prefix ?? '!'}${command.primary_name ?? command.name} ${enabled ? 'enabled' : 'disabled'}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not change command status.')
    } finally {
      setBusyCommand('')
      focusListIfNeeded()
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
    const burstMaxCount = parsedBurstMaxCount(draft.burstMaxCount)
    if (action !== 'reset' && command.name === 'tg' && burstMaxCount === null) {
      setError('Maximum repeat count must be a whole number from 1 to 20.')
      return
    }
    const metadata = {
      primary_name: draft.primaryName,
      ...(draft.sendAs !== builtinSendAs(command) ? { send_as: draft.sendAs } : {}),
      ...(canEditIdentity(command) ? { aliases: parseAliases(draft.aliases), display_name: draft.displayName } : {}),
      ...(command.name === 'tg' ? { burst_interval_ms: burstInterval!, burst_max_count: burstMaxCount! } : {}),
      ...(isBrowserMode() ? { stream_availability: draft.streamAvailability } : {}),
      ...(command.removed && draft.enabled ? { reactivate_removed: true } : {}),
    }
    const responsePool = command.response_pool
    const saveResponses = action === 'save' && responsePool && draft.responsePool !== null
      && (responseDraftIsDirty(command, draft) || !responsePool.saved)
    const responses = responsePool && draft.responsePool !== null ? parseResponsePool(responsePool, draft.responsePool) : []
    if (saveResponses && responses.length === 0) {
      setError('Keep at least one non-empty response or message.')
      return
    }
    if (action === 'reset' && !await confirmAction({
      title: `Reset ${data?.command_prefix ?? '!'}${command.primary_name ?? command.name} settings?`,
      description: 'Restore the factory name, aliases, access and cooldowns. Keep the current enabled state and saved message.',
      danger: true,
    })) {
      return
    }

    setBusyCommand(command.name)
    setError('')
    setNotice('')
    let settingsSaved = false
    let responsesSaved = false
    try {
      const api = await waitForBridge()
      if (action === 'reset') {
        const result = await api.reset_command_settings(command.name, true)
        if (!result.ok) throw new Error(result.error ?? 'Command settings could not be updated.')
      } else if (settingsDraftIsDirty(command, draft) || !command.saved) {
        const result = await api.save_command_settings(
          command.name,
          draft.enabled,
          perUserSeconds!,
          globalSeconds!,
          draft.permission,
          metadata,
        )
        if (!result.ok) throw new Error(result.error ?? 'Command settings could not be saved.')
        settingsSaved = true
      }
      if (saveResponses) {
        const result = await api.save_command_responses(command.name, responses)
        if (!result.ok) throw new Error(result.error ?? 'Command text could not be saved.')
        responsesSaved = true
      }
      await loadCommands(command.name, action === 'reset' ? 'settings' : undefined)
      if (action === 'save') setEditingBuiltin(null)
      setNotice(action === 'save'
          ? `Saved ${data?.command_prefix ?? '!'}${draft.primaryName.trim()}${responsePool ? ' text and settings' : ''}.`
          : `Reset !${command.name} settings to built-in defaults. Its message was kept.`)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Command could not be saved.'
      if (settingsSaved && !responsesSaved && saveResponses) {
        setError(`Saved ${data?.command_prefix ?? '!'}${draft.primaryName.trim()} settings, but its text could not be saved. ${message} Your text draft is kept; use Save command to retry.`)
        // Refresh the committed settings while retaining this command's text and other drafts.
        try { await loadCommands(command.name, 'settings') } catch { /* Keep the drafts if refreshing also fails. */ }
      } else if (settingsSaved || responsesSaved) {
        setError(`Saved ${data?.command_prefix ?? '!'}${draft.primaryName.trim()}, but could not refresh it. ${message} Reopen Commands to check the saved values.`)
      } else {
        setError(message)
      }
    } finally {
      setBusyCommand('')
      focusListIfNeeded()
    }
  }

  const runResponseAction = async (
    command: CommandInfo,
  ) => {
    const draft = drafts[command.name]
    const responsePool = command.response_pool
    if (!draft || !responsePool || draft.responsePool === null) {
      return
    }
    const responseNoun = responsePool.response_mode === 'random' ? 'responses' : 'message'
    if (!await confirmAction({
      title: `Reset ${data?.command_prefix ?? '!'}${command.primary_name ?? command.name} ${responseNoun}?`,
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
      const result = await api.reset_command_responses(command.name)
      if (!result.ok) {
        throw new Error(result.error ?? `Command ${responseNoun} could not be updated.`)
      }
      await loadCommands(command.name, 'responses')
      setNotice(`Reset ${data?.command_prefix ?? '!'}${command.primary_name ?? command.name} ${responseNoun} to built-in defaults.`)
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

  const openCustomDraft = (draft: CustomDraft) => {
    customBaseline.current = draft ? { ...draft } : null
    setCustomDraft(draft)
    setError('')
    setNotice('')
  }

  const openReactionDraft = (draft: ReactionDraft) => {
    reactionBaseline.current = { ...draft }
    setReactionDraft(draft)
    setError('')
    setNotice('')
  }

  const closeEditor = async () => {
    const builtin = editingBuiltin ? commandSnapshot.current[editingBuiltin] : undefined
    const builtinDraft = builtin && drafts[builtin.name]
    if ((customDirty || reactionDirty || (builtin && builtinDraft && draftIsDirty(builtin, builtinDraft)))
      && !await confirmAction({ title: 'Discard unsaved changes?', description: 'Your changes in this editor will be lost.', danger: true })) return
    if (builtin) setDrafts((current) => ({ ...current, [builtin.name]: draftFromCommand(builtin) }))
    setEditingBuiltin(null)
    setCustomDraft(null)
    setReactionDraft(null)
    setError('')
    focusListIfNeeded()
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
    if (responses.length > 30) {
      setError('Keep 1 to 30 response templates.')
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
      send_as: customDraft.sendAs,
      ...(isBrowserMode() ? { stream_availability: customDraft.streamAvailability } : {}),
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
      setNotice(`Saved ${customData?.command_prefix ?? '!'}${name}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save custom command.')
    } finally {
      setBusyCustom(false)
      focusListIfNeeded()
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
        send_as: command.send_as,
        ...(isBrowserMode() ? { stream_availability: streamAvailability(command.stream_availability) } : {}),
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
      focusListIfNeeded()
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
      setNotice(`Deleted ${customData?.command_prefix ?? '!'}${command.name}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not delete custom command.')
    } finally {
      setBusyCustom(false)
      focusListIfNeeded()
    }
  }

  const persistReactions = async (rules: ChatReaction[]) => {
    if (!reactionData || busyReaction) return
    setError('')
    setNotice('')
    setBusyReaction(true)
    try {
      const result = await (await waitForBridge()).save_message_triggers(rules, reactionData.revision)
      if (!result.ok) throw new Error(result.error ?? 'Could not save chat reactions.')
      setReactionData(result)
      setReactionDraft(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save chat reactions.')
    } finally {
      setBusyReaction(false)
      focusListIfNeeded()
    }
  }

  const reactionPosition = reactionData && reactionDraft
    ? reactionData.triggers.findIndex((item) => item.id === reactionDraft.id) : -1
  const saveReaction = () => {
    if (!reactionData || !reactionDraft) return
    const { position, ...values } = reactionDraft
    const original = reactionData.triggers[reactionPosition]
    const rules = reactionData.triggers.filter((item) => item.id !== values.id)
    rules.splice(position, 0, {
      ...values,
      probability: original && values.probability === probabilityText(original.probability)
        ? original.probability : Number(values.probability) / 100,
      cooldown_seconds: Number(values.cooldown_seconds),
      responses: values.responses.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
    })
    void persistReactions(rules)
  }

  const deleteReaction = async (reaction: ChatReaction) => {
    if (!reactionData) return
    if (await confirmAction({ title: 'Delete chat reaction?', description: `Permanently delete the reaction for “${reaction.text}”?`, danger: true })) {
      await persistReactions(reactionData.triggers.filter((item) => item.id !== reaction.id))
    }
  }

  const resetAllBuiltins = async () => {
    if (!await confirmAction({
      title: 'Restore all factory defaults?',
      description: 'Restore built-in settings and messages. Each command keeps its current enabled state.',
      danger: true,
    })) return
    setBusyCommand('factory')
    setError('')
    setNotice('')
    try {
      const result = await (await waitForBridge()).reset_all_builtin_commands(true)
      await loadCommands()
      if (!result.ok) throw new Error(result.error ?? 'Could not reset all built-ins.')
      setNotice('Restored all built-in settings and messages.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not reset all built-ins.')
    } finally {
      setBusyCommand('')
    }
  }

  const renderBuiltin = (command: CommandInfo) => {
    if (!data) return null
    const primaryName = command.primary_name ?? command.name
    const draft = drafts[command.name] ?? draftFromCommand(command)
    const perUserValid = parsedCooldown(draft.perUserSeconds) !== null
    const globalValid = parsedCooldown(draft.globalSeconds) !== null
    const intervalValid = command.name !== 'tg' || parsedBurstInterval(draft.burstIntervalMs) !== null
    const maxCountValid = command.name !== 'tg' || parsedBurstMaxCount(draft.burstMaxCount) !== null
    const maxCount = parsedBurstMaxCount(draft.burstMaxCount) ?? tgBurstMaxCount(command)
    const settingsDirty = settingsDraftIsDirty(command, draft)
    const responseDirty = responseDraftIsDirty(command, draft)
    const dirty = settingsDirty || responseDirty
    const responsePool = command.response_pool
    const responseDraft = draft.responsePool
    const parsedResponses = responsePool && responseDraft !== null ? parseResponsePool(responsePool, responseDraft) : []
    const responseValid = parsedResponses.length > 0
    const isRandom = responsePool?.response_mode === 'random'
    const busy = busyCommand !== ''
    const compact = !isBrowserMode() || command.name === 'erase'
    const aliasField = canEditIdentity(command) && <div className="form-field command-aliases">
      <div className="custom-field-label"><label htmlFor={`aliases-${command.name}`}>Aliases, separated by commas</label>{compact && <HelpTip label="Built-in aliases">Optional alternate chat names, without {data.command_prefix}. For example question, q. Aliases keep this command's identity and access rules.</HelpTip>}</div>
      <input id={`aliases-${command.name}`} disabled={busy} value={draft.aliases} onChange={(event) => updateDraft(command.name, { aliases: event.target.value })} placeholder={compact ? 'e.g. question, q' : 'Optional alternate commands'} />
    </div>
    const displayField = canEditIdentity(command) && <div className="form-field command-display-label">
      <div className="custom-field-label"><label htmlFor={`display-name-${command.name}`}>Name in UI</label><HelpTip label="Name in UI">Optional display label. Public help uses the primary chat name.</HelpTip></div>
      <input id={`display-name-${command.name}`} disabled={busy} value={draft.displayName} maxLength={80} onChange={(event) => updateDraft(command.name, { displayName: event.target.value })} placeholder={compact ? 'e.g. AI questions' : 'Optional label'} />
    </div>
    const supportsSendAs = command.supports_send_as ?? !['tg', 'erase'].includes(command.name)
    const sections: CommandEditorSection[] = [
      {
        id: 'general', body: <div className="command-editor-stack">
          <div className="command-editor-identity">
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor={`primary-name-${command.name}`}>Primary chat name</label><HelpTip label="Primary chat name">Use one word of up to 40 characters, without {data.command_prefix}. Renaming keeps this command’s behavior, permission and cooldowns. The old name stops working unless kept as an alias. Reset settings restores the factory name. Factory names remain reserved for restoration.</HelpTip></div>
              <input id={`primary-name-${command.name}`} data-editor-focus disabled={busy} value={draft.primaryName} maxLength={40} onChange={(event) => updateDraft(command.name, { primaryName: event.target.value })} />
            </div>
            <Switch
              className="toggle-field command-enabled-toggle"
              checked={draft.enabled}
              disabled={busy}
              ariaLabel={`Enable ${data.command_prefix}${primaryName}`}
              onCheckedChange={(enabled) => updateDraft(command.name, { enabled })}
            >
              <span>{draft.enabled ? copy.enabled : copy.disabled}</span>
            </Switch>
          </div>
          {!responsePool && <div className="command-behavior-note command-dynamic-note">
            <span>Dynamic response</span>
            <HelpTip label="Dynamic response">This command generates its response from its built-in behavior and cannot be edited as a text template. Enabled state, permission and cooldowns still apply.</HelpTip>
          </div>}
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
          {!command.hidden && responsePool && responseDraft !== null && <button type="button" className="ghost" disabled={busy || (!responseDirty && !responsePool.has_saved_override && responsePool.saved)} onClick={() => void runResponseAction(command)}>{isRandom ? 'Reset responses' : 'Reset message'}</button>}
          <div className="command-fields">
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor={`per-user-${command.name}`}>Per-user cooldown</label>{compact && <HelpTip label="Built-in per-user cooldown">Seconds before the same viewer can use this command again. Zero disables this cooldown.</HelpTip>}</div>
              <span className="number-with-unit"><input id={`per-user-${command.name}`} disabled={busy} className={perUserValid ? '' : 'invalid'} type="number" min="0" step="any" value={draft.perUserSeconds} onChange={(event) => updateDraft(command.name, { perUserSeconds: event.target.value })} /><span>sec</span></span>
            </div>
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor={`global-${command.name}`}>Global cooldown</label>{compact && <HelpTip label="Built-in global cooldown">Seconds between invocations by any viewers. Zero disables this cooldown.</HelpTip>}</div>
              <span className="number-with-unit"><input id={`global-${command.name}`} disabled={busy} className={globalValid ? '' : 'invalid'} type="number" min="0" step="any" value={draft.globalSeconds} onChange={(event) => updateDraft(command.name, { globalSeconds: event.target.value })} /><span>sec</span></span>
            </div>
          </div>
          {supportsSendAs && <SendAsField id={`send-as-${command.name}`} value={draft.sendAs} disabled={busy} onChange={(sendAs) => updateDraft(command.name, { sendAs })} />}
        </div>
      },
      {
        id: 'access', body: <div className="command-editor-stack">
          <div className="custom-command-fields">
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor={`permission-${command.name}`}>Permission</label>{compact && <HelpTip label="Built-in permission">Minimum chat role allowed to invoke this command. {command.minimum_permission && command.minimum_permission !== 'USER' ? `Minimum permission: ${command.minimum_permission.toLowerCase()}.` : ''}</HelpTip>}</div>
              <Select id={`permission-${command.name}`} disabled={busy} value={draft.permission} onChange={(value) => updateDraft(command.name, { permission: value })} options={commandPermissions(data, command).map((permission) => ({ value: permission, label: permission.toLowerCase() }))} />
            </div>
            {displayField}
            {aliasField}
          </div>
          {command.hidden && <p className="command-behavior-note">Hidden administrative command; minimum {command.minimum_permission?.toLowerCase()} permission is required.</p>}
          {(!compact && command.minimum_permission && command.minimum_permission !== 'USER') && <p className="command-behavior-note">Minimum permission: {command.minimum_permission.toLowerCase()}.</p>}
          <button type="button" className="ghost" disabled={busy || (!settingsDirty && !command.has_saved_override && command.saved)} onClick={() => void runAction(command, 'reset')}>Reset settings</button>
        </div>
      },
    ]
    if (isBrowserMode() || command.name === 'tg') sections.push({
      id: 'conditions', body: <div className="command-editor-stack">
        <div className="command-fields">
          {isBrowserMode() && <label>Stream availability<Select value={draft.streamAvailability} aria-label="Stream availability" disabled={busy} onChange={(value) => updateDraft(command.name, { streamAvailability: value as StreamAvailability })} options={streamAvailabilityOptions} /></label>}
        </div>
        {command.name === 'tg' && <div className="command-burst-controls">
          <div className="form-field command-burst-interval">
            <div className="custom-field-label"><label htmlFor="tg-burst-interval">Burst interval (ms)</label>{compact && <HelpTip label="Tg Burst interval">0 to 1000 ms between request starts; 0 sends concurrently.</HelpTip>}</div>
            <input id="tg-burst-interval" disabled={busy} type="number" min="0" max="1000" step="1" aria-invalid={!intervalValid} className={intervalValid ? '' : 'invalid'} value={draft.burstIntervalMs} onChange={(event) => updateDraft(command.name, { burstIntervalMs: event.target.value })} />
            {!compact && <span className="custom-field-hint">0–1000 ms between request starts; 0 sends concurrently.</span>}
          </div>
          <div className="form-field command-burst-max-count">
            <div className="custom-field-label"><label htmlFor="tg-burst-max-count">Maximum repeat count</label>{compact && <HelpTip label="Tg repeat count">Default {data.command_prefix}{primaryName} sends 1. Use 1 to {maxCount}; e.g. {data.command_prefix}{primaryName} {maxCount} sends {maxCount} copies.</HelpTip>}</div>
            <input id="tg-burst-max-count" disabled={busy} type="number" min="1" max="20" step="1" aria-invalid={!maxCountValid} className={maxCountValid ? '' : 'invalid'} value={draft.burstMaxCount} onChange={(event) => updateDraft(command.name, { burstMaxCount: event.target.value })} />
            {!compact && <span className="custom-field-hint">Default {data.command_prefix}{primaryName} sends 1. Use 1–{maxCount}; e.g. {data.command_prefix}{primaryName} {maxCount} sends {maxCount} copies.</span>}
          </div>
        </div>}
      </div>
    })
    return <CommandEditorDialog id={`command-editor-${command.name}`} title={copy.editNamedCommand(data.command_prefix + primaryName)}
      busy={busy} dirty={dirty} error={error} sections={sections}
      saveLabel={responsePool ? copy.saveCommand : copy.save}
      saveDisabled={(!dirty && command.saved && (!responsePool || responsePool.saved)) || !perUserValid || !globalValid || !intervalValid || !maxCountValid || (responsePool !== null && !responseValid)}
      onSave={() => void runAction(command, 'save')} onClose={() => void closeEditor()} />
  }

  const builtinEditor = data?.commands.find((item) => item.name === editingBuiltin)
  const editorBusy = Boolean(busyCommand) || busyCustom || busyReaction
  const editorOpen = Boolean(builtinEditor || customDraft || reactionDraft)

  const editEntry = (entry: CommandEntry) => {
    if (entry.type === 'builtin') {
      setEditingBuiltin(entry.item.name)
      setError('')
      setNotice('')
    } else if (entry.type === 'custom') openCustomDraft(customDraftFromCommand(entry.item))
    else if (reactionData) openReactionDraft(reactionDraftFrom(entry.item, reactionData.triggers.indexOf(entry.item)))
  }

  const toggleEntry = (entry: CommandEntry, enabled: boolean) => {
    if (entry.type === 'builtin') void toggleBuiltin(entry.item, enabled)
    else if (entry.type === 'custom') void toggleCustom(entry.item)
    else if (reactionData) void persistReactions(reactionData.triggers.map((item) => item.id === entry.item.id ? { ...item, enabled } : item))
  }

  const customResponseCount = customDraft?.responses.split(/\r?\n/).filter((response) => response.trim()).length ?? 0

  const renderCustom = (customDraft: CustomDraft, customData: CustomCommandsResponse) => {
    const sections: CommandEditorSection[] = [
      {
        id: 'general', body: <div className="command-editor-stack">
          <div className="command-editor-identity">
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor="custom-name">Command name</label><HelpTip label="Command name">Use a single word of up to 40 characters, without {customData.command_prefix}. Names and aliases cannot conflict with another command.</HelpTip></div>
              <span className="custom-name-input"><span>{customData.command_prefix}</span><input data-editor-focus id="custom-name" value={customDraft.name} onChange={(event) => updateCustomDraft({ name: event.target.value })} placeholder="hello" /></span>
            </div>
            <Switch className="custom-command-enabled" checked={customDraft.enabled} ariaLabel="Enable custom command" onCheckedChange={(enabled) => updateCustomDraft({ enabled })}>
              <span>{customDraft.enabled ? copy.enabled : copy.disabled}</span>
            </Switch>
          </div>
          <div className="form-field custom-response-field">
            <div className="custom-field-label"><label htmlFor="custom-response">{customDraft.responseMode === 'random' ? 'Responses' : 'Message'}</label><HelpTip label="Custom response">Use template variables such as Hello, {'{sender}'}! Replies are limited to 450 UTF-8 bytes. Single and Burst use one line; Random uses one template per non-empty line.</HelpTip></div>
            <textarea ref={customResponse} id="custom-response" className="custom-response-textarea" rows={customDraft.responseMode === 'random' ? 7 : 4} value={customDraft.responseMode === 'random' ? customDraft.responses : customDraft.message} onChange={(event) => updateCustomDraft(customDraft.responseMode === 'random' ? { responses: event.target.value } : { message: event.target.value })} placeholder="Hello, {sender}!" />
          </div>
          {customDraft.responseMode === 'random' && <div className="custom-random-actions">
            <span className="muted">{customResponseCount} / 30 responses</span>
            <button type="button" className="secondary" disabled={busyCustom || customResponseCount >= 30} onClick={() => {
              updateCustomDraft({ responses: customDraft.responses.trimEnd() + (customDraft.responses.trim() ? '\n' : '') })
              requestAnimationFrame(() => {
                const field = customResponse.current
                field?.focus()
                field?.setSelectionRange(field.value.length, field.value.length)
              })
            }}>Add response</button>
            <button type="button" className="secondary" disabled={busyCustom || !customDraft.responses.trim()} onClick={() => {
              const responses = customDraft.responses.trimEnd().split(/\r?\n/)
              responses.pop()
              updateCustomDraft({ responses: responses.join('\n') })
              customResponse.current?.focus()
            }}>Remove last response</button>
          </div>}
          <div className="custom-command-fields">
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor="custom-per-user">Per-user cooldown (seconds)</label><HelpTip label="Per-user cooldown">Minimum wait for the same viewer to use the command again. Zero disables this cooldown.</HelpTip></div>
              <input id="custom-per-user" type="number" min="0" step="0.5" aria-invalid={parsedCooldown(customDraft.perUserSeconds) === null} value={customDraft.perUserSeconds} onChange={(event) => updateCustomDraft({ perUserSeconds: event.target.value })} />
            </div>
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor="custom-global">Global cooldown (seconds)</label><HelpTip label="Global cooldown">Minimum wait between uses by any viewers. Zero disables this cooldown.</HelpTip></div>
              <input id="custom-global" type="number" min="0" step="0.5" aria-invalid={parsedCooldown(customDraft.globalSeconds) === null} value={customDraft.globalSeconds} onChange={(event) => updateCustomDraft({ globalSeconds: event.target.value })} />
            </div>
          </div>
          <div className="custom-command-fields">
            <div className="form-field">
              <div className="custom-field-label"><label htmlFor="custom-mode">Response type</label><HelpTip label="Response type">Single sends one message. Random picks one of 1 to 30 non-empty lines; blank lines are ignored. Burst repeats one message up to ten times with optional spacing and an argument count override.</HelpTip></div>
              <Select id="custom-mode" aria-label="Response type"
                value={customDraft.responseMode}
                onChange={(value) => changeCustomMode(value as CustomResponseMode)}
                options={[
                  { value: 'single', label: 'Single' },
                  { value: 'random', label: 'Random' },
                  { value: 'burst', label: 'Burst' },
                ]}
              />
            </div>
            {customDraft.responseMode !== 'burst' && <SendAsField id="custom-send-as" value={customDraft.sendAs} onChange={(sendAs) => updateCustomDraft({ sendAs })} />}
          </div>
          <details className="custom-variable-help" key={customDraft.id ?? 'new'}>
            <summary>Available variables</summary>
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
          </details>
        </div>
      },
      {
        id: 'access', body: <div className="custom-command-fields">
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="custom-permission">Permission</label><HelpTip label="Custom command permission">The minimum chat role allowed to run this command. Burst requires Moderator or Broadcaster permission.</HelpTip></div>
            <Select id="custom-permission" aria-label="Permission" value={customDraft.permission} onChange={(value) => updateCustomDraft({ permission: value })}
              options={customData.permissions.filter((permission) => customDraft.responseMode !== 'burst' || burstPermissions.includes(permission)).map((permission) => ({ value: permission, label: permission.toLowerCase() }))} />
          </div>
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="custom-aliases">Aliases, separated by commas</label><HelpTip label="Aliases">Optional alternate names, for example hi, hey. Use up to ten unique aliases without {customData.command_prefix}; the same naming rules apply.</HelpTip></div>
            <input id="custom-aliases" value={customDraft.aliases} onChange={(event) => updateCustomDraft({ aliases: event.target.value })} placeholder="hi, hey" />
          </div>
        </div>
      },
    ]
    if (isBrowserMode() || customDraft.responseMode === 'burst') sections.push({
      id: 'conditions', body: <div className="command-editor-stack">
        {isBrowserMode() && <div className="form-field">
          <label htmlFor="custom-stream">Stream availability</label>
          <Select id="custom-stream" value={customDraft.streamAvailability} onChange={(value) => updateCustomDraft({ streamAvailability: value as StreamAvailability })} options={streamAvailabilityOptions} />
        </div>}
        {customDraft.responseMode === 'burst' && <div className="custom-burst-controls">
          <p className="custom-burst-restriction">Burst requires Moderator or Broadcaster permission. Sends 1–10 copies.</p>
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="custom-burst-count">Default repeat count</label><HelpTip label="Default repeat count">How many copies to send per invocation, from 1 to 10.</HelpTip></div>
            <input id="custom-burst-count" type="number" min="1" max="10" step="1" className={parsedBurstCount(customDraft.burstCount) === null ? 'invalid' : ''} aria-invalid={parsedBurstCount(customDraft.burstCount) === null} value={customDraft.burstCount} onChange={(event) => updateCustomDraft({ burstCount: event.target.value })} />
          </div>
          <div className="form-field">
            <div className="custom-field-label"><label htmlFor="custom-burst-interval">Burst interval (ms)</label><HelpTip label="Custom burst interval">0–1000 ms between request starts; 0 sends concurrently. Every send is awaited.</HelpTip></div>
            <input id="custom-burst-interval" type="number" min="0" max="1000" step="1" className={parsedBurstInterval(customDraft.burstIntervalMs) === null ? 'invalid' : ''} aria-invalid={parsedBurstInterval(customDraft.burstIntervalMs) === null} value={customDraft.burstIntervalMs} onChange={(event) => updateCustomDraft({ burstIntervalMs: event.target.value })} />
          </div>
          <div className="custom-field-label">
            <Switch checked={customDraft.burstAllowOverride} ariaLabel="Allow argument count override" onCheckedChange={(burstAllowOverride) => updateCustomDraft({ burstAllowOverride })}><span>Allow argument count override</span></Switch>
            <HelpTip label="Argument count override">When enabled, {customData.command_prefix}{customDraft.name || 'promo'} 10 sends ten copies instead of the default. A target can follow, for example 10 @alice. Invalid counts send nothing.</HelpTip>
          </div>
        </div>}
      </div>
    })
    return <CommandEditorDialog id="custom-command-editor" title={customDraft.id ? copy.editCommand : copy.newCommand}
      busy={busyCustom} dirty={customDirty} error={error} sections={sections}
      saveLabel={copy.saveCommand}
      saveDisabled={customDraft.responseMode === 'burst' && (parsedBurstCount(customDraft.burstCount) === null || parsedBurstInterval(customDraft.burstIntervalMs) === null)}
      onSave={() => void saveCustom()} onClose={() => void closeEditor()} />
  }

  return (
    <div className="commands-layout" aria-busy={loading}>
      {confirmation && <Confirmation {...confirmation} onConfirm={() => finishConfirmation(true)} onCancel={() => finishConfirmation(false)} />}
      <FeedbackToast
        error={editorOpen ? '' : error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <CommandList entries={[
        ...(data?.commands.map((item) => ({ type: 'builtin' as const, item })) ?? []),
        ...(customData?.commands.map((item) => ({ type: 'custom' as const, item })) ?? []),
        ...(reactionData?.triggers.map((item) => ({ type: 'reaction' as const, item })) ?? []),
      ]} prefix={data?.command_prefix ?? customData?.command_prefix ?? '!'} busy={loading || editorBusy}
        canCreateCommand={Boolean(customData)} canCreateReaction={Boolean(reactionData && reactionData.triggers.length < 100)}
        onCreate={(type) => {
          if (type === 'custom') openCustomDraft(newCustomDraft(customData?.permissions[0] ?? 'USER'))
          if (type === 'reaction' && reactionData) openReactionDraft(newReactionDraft(reactionData.triggers.length))
        }}
        onEdit={editEntry} onToggle={toggleEntry}
        onDelete={(entry) => entry.type === 'custom' ? void deleteCustom(entry.item) : void deleteReaction(entry.item)} />
      {active && builtinEditor && renderBuiltin(builtinEditor)}
      {active && reactionDraft && reactionData && <ChatReactions
        draft={reactionDraft} count={reactionData.triggers.length} position={reactionPosition}
        dirty={reactionDirty} busy={busyReaction} error={error}
        update={(values) => { setReactionDraft({ ...reactionDraft, ...values }); setError('') }}
        onSave={saveReaction} onClose={() => void closeEditor()} />}
      {active && customDraft && customData && renderCustom(customDraft, customData)}
      <AnnouncementsPanel active={active} />
      <CommandRestrictions active={active} commands={[
        ...(data?.commands.filter((command) => !command.removed).map((command) => ({ id: command.name, label: `${data.command_prefix}${command.primary_name ?? command.name}` })) ?? []),
        ...(customData?.commands.map((command) => ({ id: `custom:${command.id}`, label: `${customData.command_prefix}${command.name}` })) ?? []),
      ]} />
      {data && <OptOutManagement active={active} />}
      {data && <section className="card command-editor-card">
        <details className="factory-commands advanced-command-reset" id="advanced-command-reset">
          <summary>Advanced: reset all built-ins</summary>
          <div className="command-reset-row">
            <button className="ghost destructive" disabled={editorBusy} onClick={() => void resetAllBuiltins()}>Restore all factory defaults</button>
          </div>
        </details>
      </section>}
    </div>
  )
}
