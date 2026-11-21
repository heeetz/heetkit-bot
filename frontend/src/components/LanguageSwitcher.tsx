import { useState } from 'react'
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

/** Compact language menu for the navigation, next to About: shows EN/UA/RU, lists native names. */
export default function LanguageSwitcher() {
  const language = useLanguage()
  const text = useCatalog(shell)
  const { saveFailed, choose } = useLanguageChoice()
  return <span className="language-switcher" title={saveFailed ? text.language.saveFailed : undefined}>
    <Select className="language-select" value={language} valueLabel={languageCodes[language]} aria-label={text.language.label}
      options={languages.map((item) => ({ value: item, label: languageNames[item] }))}
      onChange={(value) => void choose(value as Language)} />
  </span>
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

/** Slim Settings row shared by Desktop and Server: title and hint on the left, menu on the right. */
export function InterfaceLanguageSettings({ server = false }: { server?: boolean }) {
  const text = useCatalog(shell).language
  return <section className="card settings-page interface-language-card" id="interface-settings" aria-labelledby="interface-settings-heading">
    <div className="interface-language-copy">
      <h2 id="interface-settings-heading">{text.label}</h2>
      <p className="section-copy">{text.hint} {server ? text.serverSaved : text.desktopSaved}</p>
    </div>
    <InterfaceLanguageField />
  </section>
}
