import { backendErrors } from './backendErrors'
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
  return fmt(template, params)
}

/** Replace a coded English error with its translation, keeping everything else. */
export function localizeResult<T>(value: T): T {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value
  const result = value as Localizable
  if (typeof result.error !== 'string' || typeof result.error_code !== 'string') return value
  const text = localizedError(result)
  return text === result.error ? value : { ...value, error: text }
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
