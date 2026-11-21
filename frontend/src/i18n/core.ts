import { useSyncExternalStore } from 'react'

/** UI languages. English is the default and the fallback for every missing string. */
export const languages = ['en', 'uk', 'ru'] as const
export type Language = (typeof languages)[number]

/** Short codes shown in the navigation switcher (UA is the familiar code for Ukrainian). */
export const languageCodes: Record<Language, string> = { en: 'EN', uk: 'UA', ru: 'RU' }
/** Native names for the Settings field. */
export const languageNames: Record<Language, string> = { en: 'English', uk: 'Українська', ru: 'Русский' }
const locales: Record<Language, string> = { en: 'en-US', uk: 'uk-UA', ru: 'ru-RU' }

/** Plural forms chosen with Intl.PluralRules; uk/ru use one/few/many. */
export interface Plural { one: string; few?: string; many?: string; other: string }

type Entry = string | readonly string[] | Plural
/** uk/ru catalogs must have exactly the keys of the English catalog. */
export type Shape<T> = T extends string ? string
  : T extends readonly string[] ? readonly string[]
    : T extends Plural ? Plural
      : { readonly [K in keyof T]: Shape<T[K]> }

export interface Catalog<T> { readonly en: T; readonly uk: Shape<T>; readonly ru: Shape<T> }

const registry: Catalog<object>[] = []

/** Declare one feature's strings. TypeScript enforces identical keys in every language. */
export function defineCatalog<const T extends object>(catalog: { en: T; uk: NoInfer<Shape<T>>; ru: NoInfer<Shape<T>> }): Catalog<T> {
  registry.push(catalog as Catalog<object>)
  return catalog as Catalog<T>
}

/** All declared catalogs, for the parity check. */
export const declaredCatalogs = (): readonly Catalog<object>[] => registry

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (languages as readonly string[]).includes(value)
}

let current: Language = 'en'
const listeners = new Set<() => void>()

export const getLanguage = (): Language => current
export const getLocale = (language: Language = current): string => locales[language]

export function subscribeLanguage(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** Change the language in place. State, drafts and the session are untouched. */
export function applyLanguage(language: Language): void {
  if (language === current) return
  current = language
  document.documentElement.lang = language
  for (const listener of listeners) listener()
}

export function useLanguage(): Language {
  return useSyncExternalStore(subscribeLanguage, getLanguage)
}

function isPlural(value: unknown): value is Plural {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
    && typeof (value as Plural).one === 'string' && typeof (value as Plural).other === 'string'
}

function merge(base: unknown, override: unknown): unknown {
  if (override === undefined || override === null) return base
  if (typeof base === 'string' || Array.isArray(base) || isPlural(base)) {
    return typeof override === typeof base || isPlural(override) ? override : base
  }
  if (!base || typeof base !== 'object' || typeof override !== 'object') return base
  const result: Record<string, unknown> = {}
  for (const key of Object.keys(base)) {
    result[key] = merge((base as Record<string, unknown>)[key], (override as Record<string, unknown>)[key])
  }
  return result
}

const resolved = new WeakMap<object, Partial<Record<Language, unknown>>>()

/** Strings of a catalog for a language; any missing key falls back to English. */
export function catalogFor<T extends object>(catalog: Catalog<T>, language: Language = current): T {
  let entries = resolved.get(catalog)
  if (!entries) {
    entries = {}
    resolved.set(catalog, entries)
  }
  if (!entries[language]) entries[language] = language === 'en' ? catalog.en : merge(catalog.en, catalog[language])
  return entries[language] as T
}

/** Strings for the current UI language; rerenders when the language changes. */
export function useCatalog<T extends object>(catalog: Catalog<T>): T {
  return catalogFor(catalog, useLanguage())
}

export type Params = Record<string, string | number>

/** Replace {name} placeholders. Numbers are formatted for the UI language. */
export function fmt(template: string, params: Params = {}, language: Language = current): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name]
    if (value === undefined) return match
    return typeof value === 'number' ? formatNumber(value, language) : value
  })
}

const pluralRules = new Map<Language, Intl.PluralRules>()

/** Pick the plural form for count and fill {count} and other placeholders. */
export function plural(forms: Plural, count: number, params: Params = {}, language: Language = current): string {
  let rules = pluralRules.get(language)
  if (!rules) {
    rules = new Intl.PluralRules(locales[language])
    pluralRules.set(language, rules)
  }
  const category = rules.select(count) as keyof Plural
  const template = forms[category] ?? forms.other
  return fmt(template, { count, ...params }, language)
}

export function formatNumber(value: number, language: Language = current, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(locales[language], options).format(value)
}

export function formatDateTime(value: Date | number | string, language: Language = current, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleString(locales[language], options)
}

export function formatDate(value: Date | number | string, language: Language = current, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleDateString(locales[language], options)
}

export function formatTime(value: Date | number | string, language: Language = current, options?: Intl.DateTimeFormatOptions): string {
  return new Date(value).toLocaleTimeString(locales[language], options)
}

/** Join items as a natural list ("a, b and c"). */
export function formatList(items: readonly string[], language: Language = current, type: Intl.ListFormatType = 'conjunction'): string {
  return new Intl.ListFormat(locales[language], { style: 'long', type }).format(items)
}

export type { Entry }

/** Formatting helpers bound to the current UI language; rerenders on a switch. */
export function useI18n() {
  const language = useLanguage()
  return {
    language,
    locale: locales[language],
    fmt: (template: string, params?: Params) => fmt(template, params, language),
    plural: (forms: Plural, count: number, params?: Params) => plural(forms, count, params, language),
    number: (value: number, options?: Intl.NumberFormatOptions) => formatNumber(value, language, options),
    dateTime: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => formatDateTime(value, language, options),
    date: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => formatDate(value, language, options),
    time: (value: Date | number | string, options?: Intl.DateTimeFormatOptions) => formatTime(value, language, options),
    list: (items: readonly string[], type?: Intl.ListFormatType) => formatList(items, language, type),
  }
}
