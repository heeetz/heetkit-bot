import { type KeyboardEvent, useRef, useState } from 'react'
import { shell } from '../i18n/app'
import { type Language, languageCodes, languageNames, languages, useCatalog, useLanguage } from '../i18n/core'
import { chooseLanguage } from '../i18n/language'
import { Select } from './Select'

/** Saves in place; a failed Desktop save keeps the new language for this session. */
function useLanguageChoice() {
  const [saveFailed, setSaveFailed] = useState(false)
  const choose = async (language: Language) => {
    setSaveFailed(!(await chooseLanguage(language)))
  }
  return { saveFailed, choose }
}

/** Compact EN | UA | RU segmented control for the navigation, next to About. */
export default function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const language = useLanguage()
  const text = useCatalog(shell)
  const { saveFailed, choose } = useLanguageChoice()
  const buttons = useRef<(HTMLButtonElement | null)[]>([])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    event.preventDefault()
    const focused = buttons.current.findIndex((button) => button === document.activeElement)
    const from = focused >= 0 ? focused : languages.indexOf(language)
    const next = languages[(from + step + languages.length) % languages.length]
    void choose(next)
    buttons.current[languages.indexOf(next)]?.focus()
  }

  return <div className={`language-switcher${compact ? ' compact' : ''}`} role="radiogroup" aria-label={text.language.label}
    title={saveFailed ? text.language.saveFailed : undefined} onKeyDown={onKeyDown}>
    {languages.map((item, index) => <button key={item} type="button" role="radio" lang={item}
      ref={(element) => { buttons.current[index] = element }}
      aria-checked={item === language} tabIndex={item === language ? 0 : -1}
      aria-label={languageNames[item]} className={item === language ? 'active' : ''}
      onClick={() => void choose(item)}>{languageCodes[item]}</button>)}
  </div>
}

/** Settings field with native language names. */
export function InterfaceLanguageField({ id = 'interface-language' }: { id?: string }) {
  const language = useLanguage()
  const text = useCatalog(shell)
  const { saveFailed, choose } = useLanguageChoice()
  return <div className="form-field interface-language-field">
    <label className="visually-hidden" htmlFor={id}>{text.language.label}</label>
    <Select id={id} value={language} aria-label={text.language.label}
      options={languages.map((item) => ({ value: item, label: languageNames[item] }))}
      onChange={(value) => void choose(value as Language)} />
    {saveFailed && <p className="inline-error" role="alert">{text.language.saveFailed}</p>}
  </div>
}

/** Settings card shared by Desktop and Server. */
export function InterfaceLanguageSettings({ server = false }: { server?: boolean }) {
  const text = useCatalog(shell).language
  return <section className="card settings-page" id="interface-settings" aria-labelledby="interface-settings-heading">
    <div className="section-heading">
      <div>
        <h2 id="interface-settings-heading">{text.label}</h2>
        <p className="section-copy">{text.hint} {server ? text.serverSaved : text.desktopSaved}</p>
      </div>
      <span className="mini-badge saved-badge">{text.autoSaved}</span>
    </div>
    <InterfaceLanguageField />
  </section>
}
