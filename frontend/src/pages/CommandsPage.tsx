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
import AnnouncementsPanel from '../components/AnnouncementsPanel'
import ChatReactions, { newReactionDraft, probabilityText, reactionDraftFrom, type ReactionDraft } from '../components/ChatReactions'
import CommandList, { type CommandEntry } from '../components/CommandList'
import CommandEditorDialog, { type CommandEditorSection } from '../components/CommandEditorDialog'
import { commandsText } from '../i18n/commands'
import { useCatalog, useI18n } from '../i18n/core'
import CommandRestrictions from '../components/CommandRestrictions'
import OptOutManagement from '../components/OptOutManagement'
import './commands-refresh.css'

interface CommandDraft {
  entryLimit: string
  chatTemplate: string
  primaryName: string
  enabled: boolean
  permission: string
  perUserSeconds: string
  globalSeconds: string
  responsePool: string | null
  aliases: string
  displayName: string
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
  burstMaxCount: string
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

type Labels = Record<string, string>

const streamAvailabilityValues: StreamAvailability[] = ['anytime', 'live_only', 'offline_only']
const sendAsValues: SendAs[] = ['chat', 'mention', 'reply']

function SendAsField({ id, value, onChange, disabled }: { id: string; value: SendAs; onChange: (value: SendAs) => void; disabled?: boolean }) {
  const text = useCatalog(commandsText).page
  const sendAsOptions = sendAsValues.map((option) => ({ value: option, label: text.sendAsOptions[option] }))
  return <div className="form-field">
    <label className="command-field-label" htmlFor={id}>{text.sendAs}</label>
    <span className="command-select-control"><Select id={id} aria-label={text.sendAs} value={value} onChange={(next) => onChange(next as SendAs)} options={sendAsOptions} disabled={disabled} /></span>
  </div>
}

function builtinSendAs(command: CommandInfo): SendAs {
  return command.send_as ?? command.default_send_as ?? 'chat'
}

function streamAvailability(value: StreamAvailability | undefined): StreamAvailability {
  return value ?? 'anytime'
}

function draftFromCommand(command: CommandInfo): CommandDraft {
  return {
    entryLimit: String(command.entry_limit ?? ''),
    chatTemplate: command.chat_template ?? '',
    primaryName: command.primary_name ?? command.name,
    enabled: command.enabled,
    permission: command.permission,
    perUserSeconds: String(command.cooldown.per_user_seconds),
    globalSeconds: String(command.cooldown.global_seconds),
    responsePool: command.response_pool ? responsePoolText(command.response_pool) : null,
    aliases: command.aliases.join(', '),
    displayName: command.display_name ?? '',
    streamAvailability: streamAvailability(command.stream_availability),
    sendAs: builtinSendAs(command),
  }
}

function responsePoolText(responsePool: NonNullable<CommandInfo['response_pool']>): string {
  return responsePool.responses.join('\n')
}

function parseResponsePool(draft: string): string[] {
  return draft.split(/\r?\n/).map((response) => response.trim()).filter(Boolean)
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
    || (command.entry_limit !== undefined && draft.entryLimit !== String(command.entry_limit))
    || (command.chat_template !== undefined && draft.chatTemplate !== command.chat_template)
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
    burstMaxCount: '10',
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
    burstMaxCount: String(command.burst_max_count ?? 10),
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

function parsedBurstMaxCount(value: string, defaultCount: string): number | null {
  if (value.trim() === '') return null
  const count = Number(value)
  return Number.isInteger(count) && count >= Math.max(1, parsedBurstCount(defaultCount) ?? 1) && count <= 20 ? count : null
}

function parseAliases(value: string): string[] {
  return value.split(/[\n,]/).map((alias) => alias.trim()).filter(Boolean)
}

function canEditIdentity(command: CommandInfo): boolean {
  return command.identity_editable !== false
}

function commandPermissions(data: CommandsResponse, command: CommandInfo): string[] {
  const minimum = command.minimum_permission ?? (command.name === 'erase' ? 'MODERATOR' : 'USER')
  const levels = ['USER', 'SUBSCRIBER', 'VIP', 'MODERATOR', 'BROADCASTER']
  return data.permissions.filter((permission) => levels.indexOf(permission) >= levels.indexOf(minimum))
}

export default function CommandsPage({ active, revealCommand, onAIEnabledChanged }: CommandsPageProps) {
  const strings = useCatalog(commandsText)
  const copy = strings.editor
  const text = strings.page
  const { fmt, plural } = useI18n()
  const streamAvailabilityOptions = streamAvailabilityValues.map((value) => ({ value, label: text.streamAvailability[value] }))
  const permissionLabels: Labels = text.permissions
  const permissionLabel = (permission: string) => permissionLabels[permission] ?? permission.toLowerCase()
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
          api.get_message_triggers().catch((reason: unknown) => ({ ok: false, triggers: [], revision: '', error: reason instanceof Error ? reason.message : text.loadReactionsFailed })),
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
          setError(reactionResponse.ok ? '' : reactionResponse.error ?? text.loadReactionsFailed)
        }
      } catch (reason) {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : text.loadFailed)
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
      if (!result.ok) throw new Error(result.error ?? text.statusFailed)
      await loadCommands()
      setNotice(fmt(enabled ? text.commandEnabled : text.commandDisabled, { name: `${data?.command_prefix ?? '!'}${command.primary_name ?? command.name}` }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.statusFailed)
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
      setError(text.cooldownInvalid)
      return
    }
    const metadata = {
      primary_name: draft.primaryName,
      ...(draft.sendAs !== builtinSendAs(command) ? { send_as: draft.sendAs } : {}),
      ...(canEditIdentity(command) ? { aliases: parseAliases(draft.aliases), display_name: draft.displayName } : {}),
      ...(command.entry_limit !== undefined ? { entry_limit: Number(draft.entryLimit) } : {}),
      ...(command.chat_template !== undefined ? { chat_template: draft.chatTemplate } : {}),
      ...(isBrowserMode() ? { stream_availability: draft.streamAvailability } : {}),
      ...(command.removed && draft.enabled ? { reactivate_removed: true } : {}),
    }
    const responsePool = command.response_pool
    const saveResponses = action === 'save' && responsePool && draft.responsePool !== null
      && (responseDraftIsDirty(command, draft) || !responsePool.saved)
    const responses = responsePool && draft.responsePool !== null ? parseResponsePool(draft.responsePool) : []
    if (saveResponses && responses.length === 0) {
      setError(text.responseRequired)
      return
    }
    if (action === 'reset' && !await confirmAction({
      title: fmt(text.resetSettingsTitle, { name: `${data?.command_prefix ?? '!'}${command.primary_name ?? command.name}` }),
      description: command.chat_template !== undefined
        ? text.resetSettingsWithMessage
        : text.resetSettingsDescription,
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
        if (!result.ok) throw new Error(result.error ?? text.settingsUpdateFailed)
      } else if (settingsDraftIsDirty(command, draft) || !command.saved) {
        const result = await api.save_command_settings(
          command.name,
          draft.enabled,
          perUserSeconds!,
          globalSeconds!,
          draft.permission,
          metadata,
        )
        if (!result.ok) throw new Error(result.error ?? text.settingsSaveFailed)
        settingsSaved = true
      }
      if (saveResponses) {
        const result = await api.save_command_responses(command.name, responses)
        if (!result.ok) throw new Error(result.error ?? text.textSaveFailed)
        responsesSaved = true
      }
      await loadCommands(command.name, action === 'reset' ? 'settings' : undefined)
      if (action === 'save') setEditingBuiltin(null)
      setNotice(action === 'save'
          ? fmt(responsePool ? text.savedWithText : text.saved, { name: `${data?.command_prefix ?? '!'}${draft.primaryName.trim()}` })
          : fmt(command.chat_template !== undefined ? text.resetWithMessage : text.resetKeptMessage, { name: `!${command.name}` }))
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : text.saveFailed
      if (settingsSaved && !responsesSaved && saveResponses) {
        setError(fmt(text.textNotSaved, { name: `${data?.command_prefix ?? '!'}${draft.primaryName.trim()}`, message }))
        // Refresh the committed settings while retaining this command's text and other drafts.
        try { await loadCommands(command.name, 'settings') } catch { /* Keep the drafts if refreshing also fails. */ }
      } else if (settingsSaved || responsesSaved) {
        setError(fmt(text.refreshFailed, { name: `${data?.command_prefix ?? '!'}${draft.primaryName.trim()}`, message }))
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
    const commandName = `${data?.command_prefix ?? '!'}${command.primary_name ?? command.name}`
    const updateFailed = text.responsesUpdateFailed
    if (!await confirmAction({
      title: fmt(text.resetResponsesTitle, { name: commandName }),
      description: text.resetResponsesDescription,
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
        throw new Error(result.error ?? updateFailed)
      }
      await loadCommands(command.name, 'responses')
      setNotice(fmt(text.responsesReset, { name: commandName }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : updateFailed)
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
      && !await confirmAction({ title: text.discardTitle, description: text.discardDescription, danger: true })) return
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
      setError(text.customInvalid)
      return
    }
    if (responses.length > 30) {
      setError(text.customTooMany)
      return
    }
    const burstMaxCount = parsedBurstMaxCount(customDraft.burstMaxCount, customDraft.burstCount)
    const burstCount = parsedBurstCount(customDraft.burstCount)
    const burstInterval = parsedBurstInterval(customDraft.burstIntervalMs)
    if (customDraft.responseMode === 'burst' && (burstCount === null || !burstPermissions.includes(customDraft.permission))) {
      setError(text.burstInvalid)
      return
    }
    if (customDraft.responseMode === 'burst' && burstInterval === null) {
      setError(text.burstIntervalInvalid)
      return
    }

    if (customDraft.responseMode === 'burst' && burstMaxCount === null) {
      setError(text.maxCountInvalid)
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
      ...(customDraft.responseMode === 'burst' ? { burst_count: burstCount!, burst_max_count: burstMaxCount!, burst_allow_override: customDraft.burstAllowOverride, burst_interval_ms: burstInterval! } : {}),
    }
    setBusyCustom(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.save_custom_command(command)
      if (!result.ok) throw new Error(result.error ?? text.customSaveFailed)
      await loadCustomCommands()
      setCustomDraft(null)
      customBaseline.current = null
      setNotice(fmt(text.saved, { name: `${customData?.command_prefix ?? '!'}${name}` }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.customSaveFailed)
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
        ...(command.response_mode === 'burst' ? { burst_count: command.burst_count ?? 1, burst_max_count: command.burst_max_count ?? 10, burst_allow_override: command.burst_allow_override ?? false, burst_interval_ms: command.burst_interval_ms ?? 0 } : {}),
      })
      if (!result.ok) throw new Error(result.error ?? text.customUpdateFailed)
      await loadCustomCommands()
      setCustomDraft((current) => current?.id === command.id ? { ...current, enabled: !command.enabled } : current)
      if (customBaseline.current?.id === command.id) customBaseline.current = { ...customBaseline.current, enabled: !command.enabled }
      setNotice(fmt(command.enabled ? text.commandDisabled : text.commandEnabled, { name: `${customData?.command_prefix ?? '!'}${command.name}` }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.customUpdateFailed)
    } finally {
      setBusyCustom(false)
      focusListIfNeeded()
    }
  }

  const deleteCustom = async (command: CustomCommandInfo) => {
    if (!await confirmAction({
      title: fmt(text.deleteTitle, { name: `${customData?.command_prefix ?? '!'}${command.name}` }),
      description: text.deleteDescription,
      danger: true,
    })) return
    setBusyCustom(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.delete_custom_command(command.id)
      if (!result.ok) throw new Error(result.error ?? text.customDeleteFailed)
      await loadCustomCommands()
      setNotice(fmt(text.deleted, { name: `${customData?.command_prefix ?? '!'}${command.name}` }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.customDeleteFailed)
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
      if (!result.ok) throw new Error(result.error ?? text.reactionsSaveFailed)
      setReactionData(result)
      setReactionDraft(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.reactionsSaveFailed)
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
    if (await confirmAction({ title: text.deleteReactionTitle, description: fmt(text.deleteReactionDescription, { text: reaction.text }), danger: true })) {
      await persistReactions(reactionData.triggers.filter((item) => item.id !== reaction.id))
    }
  }

  const resetAllBuiltins = async () => {
    if (!await confirmAction({
      title: text.restoreAllTitle,
      description: text.restoreAllDescription,
      danger: true,
    })) return
    setBusyCommand('factory')
    setError('')
    setNotice('')
    try {
      const result = await (await waitForBridge()).reset_all_builtin_commands(true)
      await loadCommands()
      if (!result.ok) throw new Error(result.error ?? text.restoreAllFailed)
      setNotice(text.restoredAll)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.restoreAllFailed)
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
    const settingsDirty = settingsDraftIsDirty(command, draft)
    const responseDirty = responseDraftIsDirty(command, draft)
    const dirty = settingsDirty || responseDirty
    const responsePool = command.response_pool
    const responseDraft = draft.responsePool
    const parsedResponses = responsePool && responseDraft !== null ? parseResponsePool(responseDraft) : []
    const responseValid = parsedResponses.length > 0
    const busy = busyCommand !== ''
    const aliasField = canEditIdentity(command) && <div className="form-field command-aliases">
      <label className="command-field-label" htmlFor={`aliases-${command.name}`}>{text.aliases}</label>
      <span className="command-context-control"><input id={`aliases-${command.name}`} aria-label={text.aliasesInput} disabled={busy} value={draft.aliases} onChange={(event) => updateDraft(command.name, { aliases: event.target.value })} placeholder={text.commaSeparated} /></span>
    </div>
    const displayField = canEditIdentity(command) && <div className="form-field command-display-label">
      <label className="command-field-label" htmlFor={`display-name-${command.name}`}>{text.nameInUI}</label>
      <span className="command-context-control"><input id={`display-name-${command.name}`} aria-label={text.nameInUI} disabled={busy} value={draft.displayName} maxLength={80} onChange={(event) => updateDraft(command.name, { displayName: event.target.value })} placeholder={text.nameInUI} /></span>
    </div>
    const supportsSendAs = command.supports_send_as ?? command.name !== 'erase'
    const sections: CommandEditorSection[] = [
      {
        id: 'general', body: <div className="command-editor-stack">
          <div className="command-editor-identity">
            <div className="form-field">
              <label className="command-field-label" htmlFor={`primary-name-${command.name}`}>{text.primaryName}</label>
              <span className="custom-name-input"><span aria-hidden="true">{data.command_prefix}</span><input id={`primary-name-${command.name}`} aria-label={text.primaryName} data-editor-focus disabled={busy} value={draft.primaryName} maxLength={40} onChange={(event) => updateDraft(command.name, { primaryName: event.target.value })} /></span>
            </div>
            <Switch
              className="custom-command-enabled"
              checked={draft.enabled}
              disabled={busy}
              ariaLabel={fmt(text.enableNamed, { name: `${data.command_prefix}${primaryName}` })}
              onCheckedChange={(enabled) => updateDraft(command.name, { enabled })}
            >
              <span>{draft.enabled ? copy.enabled : copy.disabled}</span>
            </Switch>
          </div>
          {!responsePool && command.chat_template === undefined && <div className="command-behavior-note command-dynamic-note"><span>{text.dynamicResponse}</span></div>}
          {!command.available && <p className="command-unavailable"><strong>{text.unavailable}</strong> {command.unavailable_reason ?? text.aiNotConfigured}</p>}
          {command.chat_template !== undefined && <div className="form-field">
              <label className="command-field-label" htmlFor={`chat-template-${command.name}`}>{text.commandMessage}</label>
            <span className="command-context-control"><input id={`chat-template-${command.name}`} aria-label={text.commandMessage} placeholder={text.commandMessage} disabled={busy} maxLength={450} value={draft.chatTemplate}
              onChange={(event) => updateDraft(command.name, { chatTemplate: event.target.value })} /></span>
          </div>}
          {command.entry_limit !== undefined && <div className="form-field">
            <label className="command-field-label" htmlFor="leaderboard-entry-limit">{text.entryLimit}</label>
            <span className="command-context-control"><input id="leaderboard-entry-limit" aria-label={text.entryLimit} placeholder="1–10" type="number" min={1} max={10} step={1} required disabled={busy}
              value={draft.entryLimit} onChange={(event) => updateDraft(command.name, { entryLimit: event.target.value })} /></span>
          </div>}
          {!command.hidden && responsePool && responseDraft !== null && <div className="command-response-editor">
            <div className="custom-response-heading">
              <div>
                <h3>{text.responsePool}</h3>
              </div>
              <div className="command-response-badges">
                {responsePool.has_saved_override && <span className="mini-badge saved-badge">{text.savedOverride}</span>}
                {!responsePool.saved && <span className="mini-badge runtime-badge">{text.runtimeOnly}</span>}
                {responseDirty && <span className="mini-badge dirty-badge">{text.edited}</span>}
              </div>
            </div>
            <div className="form-field command-response-field">
              <div className="command-response-control"><textarea
                aria-label={text.responses}
                className="command-response-textarea"
                disabled={busy}
                rows={7}
                value={responseDraft}
                onChange={(event) => updateDraft(command.name, { responsePool: event.target.value })}
                placeholder={text.onePerLine}
              /></div>
            </div>
            <p className="command-meta">{plural(text.responsesReady, parsedResponses.length)}</p>
          </div>}
          {!command.hidden && responsePool && responseDraft !== null && <button type="button" className="ghost" disabled={busy || (!responseDirty && !responsePool.has_saved_override && responsePool.saved)} onClick={() => void runResponseAction(command)}>{text.resetResponses}</button>}
          <div className="command-fields">
            <div className="form-field">
              <label className="command-field-label" htmlFor={`per-user-${command.name}`}>{text.perUserCooldown}</label>
              <span className="command-number-control"><input id={`per-user-${command.name}`} aria-label={text.perUserCooldown} disabled={busy} className={perUserValid ? '' : 'invalid'} type="number" min="0" step="any" value={draft.perUserSeconds} onChange={(event) => updateDraft(command.name, { perUserSeconds: event.target.value })} /><span>{text.secondsUnit}</span></span>
            </div>
            <div className="form-field">
              <label className="command-field-label" htmlFor={`global-${command.name}`}>{text.globalCooldown}</label>
              <span className="command-number-control"><input id={`global-${command.name}`} aria-label={text.globalCooldown} disabled={busy} className={globalValid ? '' : 'invalid'} type="number" min="0" step="any" value={draft.globalSeconds} onChange={(event) => updateDraft(command.name, { globalSeconds: event.target.value })} /><span>{text.secondsUnit}</span></span>
            </div>
          </div>
          {supportsSendAs && <SendAsField id={`send-as-${command.name}`} value={draft.sendAs} disabled={busy} onChange={(sendAs) => updateDraft(command.name, { sendAs })} />}
        </div>
      },
      {
        id: 'access', body: <div className="command-editor-stack">
          <div className="custom-command-fields">
            <div className="form-field">
              <label className="command-field-label" htmlFor={`permission-${command.name}`}>{text.permission}</label>
              <span className="command-select-control"><Select id={`permission-${command.name}`} aria-label={text.permission} disabled={busy} value={draft.permission} onChange={(value) => updateDraft(command.name, { permission: value })} options={commandPermissions(data, command).map((permission) => ({ value: permission, label: permissionLabel(permission) }))} /></span>
            </div>
            {displayField}
            {aliasField}
          </div>
          <button type="button" className="ghost" disabled={busy || (!settingsDirty && !command.has_saved_override && command.saved)} onClick={() => void runAction(command, 'reset')}>{text.resetSettings}</button>
        </div>
      },
    ]
    if (isBrowserMode()) sections.push({
      id: 'conditions', body: <div className="command-editor-stack">
        <div className="command-fields">
          {isBrowserMode() && <div className="form-field"><label className="command-field-label" htmlFor={`builtin-stream-${command.name}`}>{text.streamAvailabilityLabel}</label><span className="command-select-control"><Select id={`builtin-stream-${command.name}`} value={draft.streamAvailability} aria-label={text.streamAvailabilityLabel} disabled={busy} onChange={(value) => updateDraft(command.name, { streamAvailability: value as StreamAvailability })} options={streamAvailabilityOptions} /></span></div>}
        </div>
      </div>
    })
    return <CommandEditorDialog id={`command-editor-${command.name}`} title={fmt(copy.editNamedCommand, { name: data.command_prefix + primaryName })}
      busy={busy} dirty={dirty} error={error} sections={sections}
      saveLabel={responsePool ? copy.saveCommand : copy.save}
      saveDisabled={(!dirty && command.saved && (!responsePool || responsePool.saved)) || !perUserValid || !globalValid || (responsePool !== null && !responseValid)}
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
              <label className="command-field-label" htmlFor="custom-name">{text.commandName}</label>
              <span className="custom-name-input"><span>{customData.command_prefix}</span><input aria-label={text.commandName} data-editor-focus id="custom-name" value={customDraft.name} onChange={(event) => updateCustomDraft({ name: event.target.value })} placeholder={text.commandNamePlaceholder} /></span>
            </div>
            <Switch className="custom-command-enabled" checked={customDraft.enabled} ariaLabel={text.enableCustom} onCheckedChange={(enabled) => updateCustomDraft({ enabled })}>
              <span>{customDraft.enabled ? copy.enabled : copy.disabled}</span>
            </Switch>
          </div>
          <div className="form-field custom-response-field">
            <label className="command-field-label" htmlFor="custom-response">{customDraft.responseMode === 'random' ? text.responses : text.message}</label>
            <div className="command-response-control"><textarea aria-label={customDraft.responseMode === 'random' ? text.responses : text.message} ref={customResponse} id="custom-response" className="custom-response-textarea" rows={customDraft.responseMode === 'random' ? 7 : 4} value={customDraft.responseMode === 'random' ? customDraft.responses : customDraft.message} onChange={(event) => updateCustomDraft(customDraft.responseMode === 'random' ? { responses: event.target.value } : { message: event.target.value })} placeholder={text.writeResponse} /></div>
          </div>
          {customDraft.responseMode === 'random' && <div className="custom-random-actions">
            <span className="muted">{plural(text.responseCount, customResponseCount)}</span>
            <button type="button" className="secondary" disabled={busyCustom || customResponseCount >= 30} onClick={() => {
              updateCustomDraft({ responses: customDraft.responses.trimEnd() + (customDraft.responses.trim() ? '\n' : '') })
              requestAnimationFrame(() => {
                const field = customResponse.current
                field?.focus()
                field?.setSelectionRange(field.value.length, field.value.length)
              })
            }}>{text.addResponse}</button>
            <button type="button" className="secondary" disabled={busyCustom || !customDraft.responses.trim()} onClick={() => {
              const responses = customDraft.responses.trimEnd().split(/\r?\n/)
              responses.pop()
              updateCustomDraft({ responses: responses.join('\n') })
              customResponse.current?.focus()
            }}>{text.removeLastResponse}</button>
          </div>}
          <div className="custom-command-fields">
            <div className="form-field">
              <label className="command-field-label" htmlFor="custom-per-user">{text.perUserCooldown}</label>
              <span className="command-number-control"><input id="custom-per-user" aria-label={text.perUserCooldown} type="number" min="0" step="0.5" aria-invalid={parsedCooldown(customDraft.perUserSeconds) === null} value={customDraft.perUserSeconds} onChange={(event) => updateCustomDraft({ perUserSeconds: event.target.value })} /><span>{text.secondsUnit}</span></span>
            </div>
            <div className="form-field">
              <label className="command-field-label" htmlFor="custom-global">{text.globalCooldown}</label>
              <span className="command-number-control"><input id="custom-global" aria-label={text.globalCooldown} type="number" min="0" step="0.5" aria-invalid={parsedCooldown(customDraft.globalSeconds) === null} value={customDraft.globalSeconds} onChange={(event) => updateCustomDraft({ globalSeconds: event.target.value })} /><span>{text.secondsUnit}</span></span>
            </div>
          </div>
          <div className="custom-command-fields">
            <div className="form-field">
              <label className="command-field-label" htmlFor="custom-mode">{text.responseType}</label>
              <span className="command-select-control"><Select id="custom-mode" aria-label={text.responseType}
                value={customDraft.responseMode}
                onChange={(value) => changeCustomMode(value as CustomResponseMode)}
                options={[
                  { value: 'single', label: text.modeSingle },
                  { value: 'random', label: text.modeRandom },
                  { value: 'burst', label: text.modeBurst },
                ]}
              /></span>
            </div>
            {customDraft.responseMode !== 'burst' && <SendAsField id="custom-send-as" value={customDraft.sendAs} onChange={(sendAs) => updateCustomDraft({ sendAs })} />}
          </div>
        </div>
      },
      {
        id: 'access', body: <div className="custom-command-fields">
          <div className="form-field">
            <label className="command-field-label" htmlFor="custom-permission">{text.permission}</label>
            <span className="command-select-control"><Select id="custom-permission" aria-label={text.permission} value={customDraft.permission} onChange={(value) => updateCustomDraft({ permission: value })}
              options={customData.permissions.filter((permission) => customDraft.responseMode !== 'burst' || burstPermissions.includes(permission)).map((permission) => ({ value: permission, label: permissionLabel(permission) }))} /></span>
          </div>
          <div className="form-field">
            <label className="command-field-label" htmlFor="custom-aliases">{text.aliases}</label>
            <span className="command-context-control"><input id="custom-aliases" aria-label={text.aliasesInput} value={customDraft.aliases} onChange={(event) => updateCustomDraft({ aliases: event.target.value })} placeholder={text.commaSeparated} /></span>
          </div>
        </div>
      },
    ]
    if (isBrowserMode() || customDraft.responseMode === 'burst') sections.push({
      id: 'conditions', body: <div className="command-editor-stack">
        {isBrowserMode() && <div className="form-field">
          <label className="command-field-label" htmlFor="custom-stream">{text.streamAvailabilityLabel}</label>
          <span className="command-select-control"><Select id="custom-stream" aria-label={text.streamAvailabilityLabel} value={customDraft.streamAvailability} onChange={(value) => updateCustomDraft({ streamAvailability: value as StreamAvailability })} options={streamAvailabilityOptions} /></span>
        </div>}
        {customDraft.responseMode === 'burst' && <div className="custom-burst-controls">
          <div className="form-field">
            <label className="command-field-label" htmlFor="custom-burst-count">{text.defaultRepeatCount}</label>
            <input id="custom-burst-count" aria-label={text.defaultRepeatCount} placeholder={text.copies} type="number" min="1" max="10" step="1" className={parsedBurstCount(customDraft.burstCount) === null ? 'invalid' : ''} aria-invalid={parsedBurstCount(customDraft.burstCount) === null} value={customDraft.burstCount} onChange={(event) => updateCustomDraft({ burstCount: event.target.value })} />
            {parsedBurstCount(customDraft.burstCount) === null && <span className="custom-field-hint command-editor-validation" role="alert">{text.copiesHint}</span>}
          </div>
          <div className="form-field">
            <label className="command-field-label" htmlFor="custom-burst-interval">{text.burstInterval}</label>
            <input id="custom-burst-interval" aria-label={text.burstInterval} placeholder={text.intervalPlaceholder} type="number" min="0" max="1000" step="1" className={parsedBurstInterval(customDraft.burstIntervalMs) === null ? 'invalid' : ''} aria-invalid={parsedBurstInterval(customDraft.burstIntervalMs) === null} value={customDraft.burstIntervalMs} onChange={(event) => updateCustomDraft({ burstIntervalMs: event.target.value })} />
            {parsedBurstInterval(customDraft.burstIntervalMs) === null && <span className="custom-field-hint command-editor-validation" role="alert">{text.intervalHint}</span>}
          </div>
          <div className="form-field">
            <label className="command-field-label" htmlFor="custom-burst-max-count">{text.maxRepeatCount}</label>
            <input id="custom-burst-max-count" aria-label={text.maxRepeatCount} placeholder={text.maxCopies} type="number" min="1" max="20" step="1" className={parsedBurstMaxCount(customDraft.burstMaxCount, customDraft.burstCount) === null ? 'invalid' : ''} aria-invalid={parsedBurstMaxCount(customDraft.burstMaxCount, customDraft.burstCount) === null} value={customDraft.burstMaxCount} onChange={(event) => updateCustomDraft({ burstMaxCount: event.target.value })} />
            {parsedBurstMaxCount(customDraft.burstMaxCount, customDraft.burstCount) === null && <span className="custom-field-hint command-editor-validation" role="alert">{text.maxCountInvalid}</span>}
          </div>
          <div className="custom-field-label">
            <Switch checked={customDraft.burstAllowOverride} ariaLabel={text.allowOverride} onCheckedChange={(burstAllowOverride) => updateCustomDraft({ burstAllowOverride })}><span>{text.allowOverride}</span></Switch>
          </div>
        </div>}
      </div>
    })
    return <CommandEditorDialog id="custom-command-editor" title={customDraft.id ? copy.editCommand : copy.newCommand}
      busy={busyCustom} dirty={customDirty} error={error} sections={sections}
      saveLabel={copy.saveCommand}
      saveDisabled={customDraft.responseMode === 'burst' && (parsedBurstMaxCount(customDraft.burstMaxCount, customDraft.burstCount) === null || parsedBurstCount(customDraft.burstCount) === null || parsedBurstInterval(customDraft.burstIntervalMs) === null)}
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
          <summary>{text.advancedReset}</summary>
          <div className="command-reset-row">
            <button className="ghost destructive" disabled={editorBusy} onClick={() => void resetAllBuiltins()}>{text.restoreAll}</button>
          </div>
        </details>
      </section>}
    </div>
  )
}
