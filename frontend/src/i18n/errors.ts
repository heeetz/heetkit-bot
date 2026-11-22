import { backendErrors, validationFields } from './backendErrors'
import { catalogFor, fmt } from './core'

type Localizable = { error?: unknown; error_code?: unknown; error_params?: unknown }

/** Text of a backend message in the current language; English text when the code is unknown. */
export function localizedError(result: Localizable): string | undefined {
  const english = typeof result.error === 'string' ? result.error : undefined
  const code = result.error_code
  if (typeof code !== 'string') return english
  const messages = catalogFor(backendErrors) as Record<string, string>
  const template = Object.hasOwn(messages, code) ? messages[code] : undefined
  if (!template) return english
  const params = result.error_params && typeof result.error_params === 'object'
    ? Object.fromEntries(Object.entries(result.error_params as Record<string, unknown>).map(([key, value]) => [key, String(value)]))
    : {}
  if (code.startsWith('validation.')) {
    const labels = catalogFor(validationFields) as Record<string, string>
    if (params.field) params.field = labels[`fields.${params.field}`] ?? params.field
    if (params.expected) params.expected = labels[`types.${params.expected}`] ?? params.expected
  }
  return fmt(template, params)
}

/** Fields with a user-visible backend message. */
const messageFields = ['error', 'automatic_update_reason', 'load_error'] as const

/** Render coded messages, including errors inside settings and status snapshots. */
export function localizeResult<T>(value: T): T {
  if (!value || typeof value !== 'object') return value
  if (Array.isArray(value)) {
    const items = value.map(localizeResult)
    return (items.some((item, index) => item !== value[index]) ? items : value) as T
  }
  const record = value as Record<string, unknown>
  let result: Record<string, unknown> | null = null
  for (const field of messageFields) {
    const code = field === 'error' ? record.error_code : record[`${field}_code`]
    if (typeof code !== 'string') continue
    const params = field === 'error' ? record.error_params : record[`${field}_params`]
    const text = localizedError({ error: record[field], error_code: code, error_params: params })
    if (text === record[field]) continue
    result ??= { ...record }
    result[field] = text
  }
  for (const [key, child] of Object.entries(record)) {
    if (!child || typeof child !== 'object') continue
    const localized = localizeResult(child)
    if (localized === child) continue
    result ??= { ...record }
    result[key] = localized
  }
  return (result ?? value) as T
}

const wrapped = new WeakMap<object, object>()

/** Wrap a bridge so every returned error is shown in the current UI language. */
export function localizedApi<T extends object>(api: T): T {
  const existing = wrapped.get(api)
  if (existing) return existing as T
  const proxy = new Proxy(api, {
    get(target, property, receiver) {
      const member = Reflect.get(target, property, receiver)
      if (typeof member !== 'function') return member
      return (...args: unknown[]) => {
        const result = (member as (...values: unknown[]) => unknown).apply(target, args)
        return result instanceof Promise ? result.then(localizeResult) : localizeResult(result)
      }
    },
  })
  wrapped.set(api, proxy)
  return proxy
}
