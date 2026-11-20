import { type Language, applyLanguage, getLanguage, isLanguage } from './core'

/** Server keeps the choice per browser origin. Desktop uses app settings (pywebview runs in private mode). */
export const LANGUAGE_STORAGE_KEY = 'heetkit.ui-language'

function browserMode(): boolean {
  return document.querySelector('meta[name="heetkit-transport"]')?.getAttribute('content') === 'http'
}

function readStored(): Language | null {
  try {
    const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
    return isLanguage(value) ? value : null
  } catch {
    return null
  }
}

function writeStored(language: Language): void {
  try { window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language) } catch { /* Storage can be unavailable. */ }
}

interface LanguageBridge {
  get_interface_language?: () => Promise<{ ok: boolean; language?: string }>
  set_interface_language?: (language: string) => Promise<{ ok: boolean; error?: string }>
}

/** Apply the saved browser choice before the first render; English otherwise. */
export function initializeLanguage(): void {
  const stored = readStored()
  document.documentElement.lang = stored ?? 'en'
  if (stored) applyLanguage(stored)
}

/** Desktop: adopt the language saved in app settings once the bridge is ready. */
export async function loadDesktopLanguage(api: LanguageBridge): Promise<void> {
  if (browserMode() || typeof api.get_interface_language !== 'function') return
  try {
    const result = await api.get_interface_language()
    if (result.ok && isLanguage(result.language)) applyLanguage(result.language)
  } catch { /* Keep the current language. */ }
}

let desktopBridge: LanguageBridge | null = null
export function registerDesktopLanguageBridge(api: LanguageBridge): void {
  desktopBridge = api
}

/** Switch in place and remember the choice for this host. */
export async function chooseLanguage(language: Language): Promise<boolean> {
  if (language === getLanguage()) return true
  applyLanguage(language)
  writeStored(language)
  if (browserMode() || !desktopBridge?.set_interface_language) return true
  try {
    const result = await desktopBridge.set_interface_language(language)
    return result.ok
  } catch {
    return false
  }
}
