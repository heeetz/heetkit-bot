import { Fragment, useState, type ReactNode } from 'react'
import { waitForBridge } from '../bridge'
import EditorDialog from './EditorDialog'
import { common as commonText } from '../i18n/common'
import { useCatalog } from '../i18n/core'
import { settingsText } from '../i18n/settings'

const consoleUrl = 'https://dev.twitch.tv/console/apps'

/** Fill {name} placeholders with React nodes, keeping the surrounding text. */
function rich(template: string, values: Record<string, ReactNode>): ReactNode[] {
  return template.split(/\{(\w+)\}/g).map((part, index) => index % 2
    ? <Fragment key={index}>{values[part] ?? `{${part}}`}</Fragment>
    : part)
}

export default function TwitchSetupInstructions({ headingId, host, callback, callbackMode, compact = false }: {
  headingId: string
  host: 'desktop' | 'server'
  callback: string
  callbackMode?: 'paste' | 'redirect'
  compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const desktop = host === 'desktop'
  const dialogId = `${headingId}-instructions`
  const all = useCatalog(settingsText)
  const text = all.guide
  const common = useCatalog(commonText)

  const copy = async (button: HTMLButtonElement) => {
    setError('')
    setCopied(false)
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(callback)
      else {
        const input = document.createElement('textarea')
        input.value = callback
        input.readOnly = true
        input.style.position = 'fixed'
        input.style.opacity = '0'
        button.closest('dialog')?.append(input)
        try {
          input.select()
          if (!document.execCommand('copy')) throw new Error()
        } finally {
          input.remove()
          button.focus({ preventScroll: true })
        }
      }
      setCopied(true)
    } catch {
      setError(text.copyFailed)
    }
  }

  const openConsole = async () => {
    setError('')
    try {
      const result = await (await waitForBridge()).open_external_link('twitch_developer_console')
      if (!result.ok) throw new Error(result.error)
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : text.consoleFailed)
    }
  }

  const s = (value: ReactNode) => <strong>{value}</strong>
  return <>
    {!compact && <div className="twitch-application-heading">
      <h3 id={headingId}>{text.application}</h3>
      <button type="button" className="secondary" aria-haspopup="dialog" onClick={() => {
        setError('')
        setCopied(false)
        setOpen(true)
      }}>{text.open}</button>
    </div>}
    {compact && <button type="button" className="secondary setup-guide-trigger" aria-haspopup="dialog" onClick={() => {
      setError('')
      setCopied(false)
      setOpen(true)
    }}>{text.open}</button>}
    {open && <EditorDialog id={dialogId} title={text.title} closeLabel={text.close}
      busy={false} onClose={() => setOpen(false)} error={error} className="twitch-setup-dialog">
      <div className="command-dialog-panels">
        <p tabIndex={-1} data-editor-focus>{text.intro}</p>
        <ol>
          <li><strong>{text.accountsTitle}</strong>
            <ul>
              <li>{rich(text.botLogin, { field: s(all.twitch.botLogin) })}</li>
              <li>{rich(text.targetLogin, { field: s(all.twitch.targetLogin) })}</li>
              <li>{text.lookUp}</li>
              <li>{rich(text.ids, { bot: s(all.twitch.botUserId), target: s(all.twitch.targetUserId) })}</li>
            </ul>
            <p>{text.noAt}</p>
          </li>
          <li><strong>{text.registerTitle}</strong>
            <ul>
              <li>{text.register[0]}</li>
              <li>{rich(text.register[1], { register: s('Register Your Application') })}</li>
              <li>{rich(text.register[2], { confidential: s('Confidential') })}</li>
              <li>{rich(text.register[3], { redirects: s('OAuth Redirect URLs') })}</li>
              <li>{text.register[4]}</li>
            </ul>
            <div className="twitch-setup-callback">
              <div className="settings-callback">
                <div><span>{all.twitch.callbackUrl}</span><code>{callback || text.unavailable}</code></div>
                <button type="button" className="secondary" aria-label={all.twitch.copyCallback} disabled={!callback}
                  onClick={(event) => void copy(event.currentTarget)}>{all.twitch.copy}</button>
              </div>
              {desktop
                ? <button type="button" className="secondary" onClick={() => void openConsole()}>{all.twitch.openConsole}</button>
                : <a className="secondary" href={consoleUrl} target="_blank" rel="noopener noreferrer">{all.twitch.openConsole}</a>}
            </div>
            {copied && <p role="status">{text.copied}</p>}
          </li>
          <li><strong>{text.detailsTitle}</strong>
            <ul>
              <li>{rich(text.manage, { manage: s('Manage') })}</li>
              <li>{rich(text.clientId, { field: s(desktop ? all.twitch.clientIdAria : 'Client ID') })}</li>
            </ul>
          </li>
          <li><strong>{text.secretTitle}</strong>
            <ul>
              <li>{rich(text.saveStep, { section: s(text.saveSection), button: s(desktop ? all.twitch.saveForLater : all.twitch.saveTwitch) })}</li>
              <li>{rich(text.newSecret, { manage: s('Manage'), newSecret: s('New Secret') })}</li>
              <li>{rich(text.paste, { field: s(all.secret.label) })}</li>
              {desktop ? <>
                <li>{rich(text.desktopChoose, { add: s(all.secret.addRestart), replace: s(all.secret.replaceRestart) })}</li>
                <li>{rich(text.desktopRestart, { restart: s(all.twitch.restartNow) })}</li>
              </> : <>
                <li>{rich(text.serverChoose, { add: s(all.secret.add), replace: s(all.secret.replace) })}</li>
                <li>{text.serverExternal}</li>
              </>}
            </ul>
          </li>
          <li><strong>{text.accessTitle}</strong>
            <ul>
              <li>{text.accessSkip}</li>
              <li>{rich(text.accessMod, { command: <code>/mod bot_login</code>, login: <code>bot_login</code> })}</li>
            </ul>
          </li>
          <li><strong>{text.connectTitle}</strong>
            <ul>
              {desktop ? <>
                <li>{rich(text.startBot, { button: s(text.startBotLabel) })}</li>
                <li>{rich(text.authorizePrompt, { button: s(all.twitch.authorizeTwitch) })}</li>
              </> : <li>{rich(text.serverConnect, { button: s(all.twitch.connectTwitch) })}</li>}
              <li>{text.signIn}</li>
              {!desktop && <>
                <li>{text.returnTab}</li>
                {callbackMode === 'paste' && <li>{rich(text.pasteUrl, { button: s(all.twitch.completeAuthorization) })}</li>}
                <li>{rich(text.manualConnect, { button: s(text.connectLabel) })}</li>
              </>}
              <li>{rich(text.waitConnected, { status: s(common.connection.connected) })}</li>
              <li>{rich(text.sendHelp, { command: <code>!help</code> })}</li>
            </ul>
          </li>
        </ol>
      </div>
    </EditorDialog>}
  </>
}
