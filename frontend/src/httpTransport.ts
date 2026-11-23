import type { OperationTransport } from './operationClient'
import { shell } from './i18n/app'
import { catalogFor } from './i18n/core'
import type { ActionResult } from './bridge'

const transport = () => catalogFor(shell).transport

type SessionState = { authenticated: boolean; message: string }
let sessionToken = ''
let sessionState: SessionState = { authenticated: false, message: '' }
let sessionGeneration = 0
let expiryTimer = 0
const listeners = new Set<() => void>()
const activeRequests = new Set<AbortController>()
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43,128}$/

export const getBrowserSession = () => sessionState
export const subscribeBrowserSession = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function browserConnectionSecure(): boolean {
  const hostname = location.hostname
  const ipv4Loopback = /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostname)
    && hostname.split('.').every((part) => Number(part) <= 255)
  return location.protocol === 'https:' || (location.protocol === 'http:'
    && (ipv4Loopback || ['localhost', '[::1]', '::1'].includes(hostname)))
}

function clearSession(message = '') {
  sessionToken = ''
  sessionGeneration += 1
  window.clearTimeout(expiryTimer)
  for (const controller of activeRequests) controller.abort()
  sessionState = { authenticated: false, message }
  for (const listener of listeners) listener()
}

async function request<T>(method: 'GET' | 'POST', path: string, token: string, payload?: object): Promise<T> {
  if (!browserConnectionSecure()) throw new Error(transport().insecure)
  const controller = new AbortController()
  activeRequests.add(controller)
  const timer = window.setTimeout(() => controller.abort(), 30000)
  try {
    const response = await fetch(path, {
      method, credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer',
      signal: controller.signal,
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}`,
        ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
      ...(method === 'POST' ? { body: JSON.stringify(payload ?? {}) } : {}),
    })
    if (response.status === 401) {
      if (token === sessionToken && token) clearSession('expired')
      throw new Error(transport().authRequired)
    }
    if (response.status >= 500) throw new Error(transport().serverUnavailable)
    if (response.status === 429) throw new Error(transport().tooManyRequests)
    if (response.status === 403) throw new Error(transport().refused)
    const responseLimit = (path === '/v1/ops/get_message_triggers' ? 3 : 2) * 1024 * 1024
    if (response.headers.get('Content-Type')?.split(';')[0].trim() !== 'application/json'
      || Number(response.headers.get('Content-Length')) > responseLimit) {
      throw new Error(transport().invalidResponse)
    }
    let data: unknown
    try {
      const raw = await response.text()
      if (raw.length > responseLimit) throw new Error()
      data = JSON.parse(raw)
    } catch {
      throw new Error(transport().invalidResponse)
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error(transport().invalidResponse)
    }
    if (!response.ok && (data as ActionResult).ok !== false) {
      throw new Error(transport().requestFailed)
    }
    return data as T
  } catch (error) {
    if (controller.signal.aborted || error instanceof TypeError) {
      throw new Error(transport().unreachable)
    }
    throw error
  } finally {
    window.clearTimeout(timer)
    activeRequests.delete(controller)
  }
}

export async function loginBrowserSession(adminToken: string): Promise<void> {
  if (!TOKEN_PATTERN.test(adminToken)) throw new Error(transport().invalidToken)
  const generation = sessionGeneration
  const result = await request<{ ok: boolean; token?: string; expires_in?: number }>('POST', '/v1/session', adminToken, {})
  if (generation !== sessionGeneration) return
  if (!result.ok || !result.token || !TOKEN_PATTERN.test(result.token)
    || !Number.isFinite(result.expires_in) || result.expires_in! <= 0 || result.expires_in! > 3600) {
    throw new Error(transport().signInFailed)
  }
  sessionToken = result.token
  sessionState = { authenticated: true, message: '' }
  expiryTimer = window.setTimeout(() => clearSession('expired'), result.expires_in! * 1000)
  for (const listener of listeners) listener()
}

export async function logoutBrowserSession(): Promise<void> {
  const token = sessionToken
  clearSession('signed_out')
  if (token) {
    try { await request('POST', '/v1/session/logout', token, {}) } catch { /* Local access is already cleared. */ }
  }
}

export async function browserRequest<T>(method: 'GET' | 'POST', path: string, payload?: object): Promise<T> {
  const token = sessionToken
  if (!token) throw new Error(transport().signInRequired)
  const result = await request<T>(method, path, token, payload)
  // A response that arrives after logout/expiry must not restore private page state.
  if (!sessionToken || sessionToken !== token) throw new Error(transport().sessionEnded)
  return result
}

// Every panel operation is one POST /v1/ops/<name> with named arguments.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const call = <T = any>(name: string, args: object = {}) => browserRequest<T>('POST', `/v1/ops/${name}`, args)
const unsupported = async (): Promise<never> => { throw new Error(transport().desktopOnly) }

const desktopOnlyOperations = new Set([
  'export_activity', 'check_for_updates', 'prepare_desktop_update', 'get_desktop_update_progress',
  'finish_desktop_update', 'restart_desktop', 'get_app_settings', 'get_profile_info',
  'open_profile_folder', 'update_app_settings', 'get_twitch_settings', 'update_twitch_settings',
  'reconnect_twitch', 'get_credentials', 'save_custom_ai_connection', 'remove_custom_ai_connection',
])

export const browserCall: OperationTransport = async <T>(name: string, args: Record<string, unknown> = {}): Promise<T> => {
  if (desktopOnlyOperations.has(name)) return unsupported()
  // Server keeps interface language in this browser.
  if (name === 'get_desktop_startup') return { state: 'ready' } as T
  if (name === 'get_interface_language' || name === 'set_interface_language') return { ok: true } as T
  if (name === 'open_external_link') {
    const links: Record<string, string> = {
      repository: 'https://github.com/heeetz/heetkit-bot',
      license: 'https://github.com/heeetz/heetkit-bot/blob/main/LICENSE',
      third_party_notices: 'https://github.com/heeetz/heetkit-bot/blob/main/THIRD_PARTY_NOTICES.md',
      author_twitch: 'https://www.twitch.tv/heet_ok',
      releases: 'https://github.com/heeetz/heetkit-bot/releases',
    }
    const url = links[String(args.destination)]
    if (!url) return unsupported()
    window.open(url, '_blank', 'noopener,noreferrer')
    return { ok: true } as T
  }
  if (name === 'get_recent_logs') return call<T>(name, { ...args, limit: args.limit ?? 100 })
  if (name === 'save_twitch_preset') {
    const { target_channel: channel, target_channel_user_id: channel_user_id, ...rest } = args
    return call<T>(name, { ...rest, channel, channel_user_id })
  }
  return call<T>(name, args)
}
