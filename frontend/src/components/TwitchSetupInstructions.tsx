import { useState } from 'react'
import { waitForBridge } from '../bridge'
import EditorDialog from './EditorDialog'

const consoleUrl = 'https://dev.twitch.tv/console/apps'

export default function TwitchSetupInstructions({ headingId, host, callback, callbackMode }: {
  headingId: string
  host: 'desktop' | 'server'
  callback: string
  callbackMode?: 'paste' | 'redirect'
}) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const desktop = host === 'desktop'
  const dialogId = `${headingId}-instructions`

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
      setError('Could not copy the callback URL. Select the URL in the instructions and copy it manually.')
    }
  }

  const openConsole = async () => {
    setError('')
    try {
      const result = await (await waitForBridge()).open_external_link('twitch_developer_console')
      if (!result.ok) throw new Error(result.error)
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : 'Could not open Twitch Developer Console. Try again.')
    }
  }

  return <>
    <div className="twitch-application-heading">
      <h3 id={headingId}>Twitch application</h3>
      <button type="button" className="secondary" aria-haspopup="dialog" onClick={() => {
        setError('')
        setCopied(false)
        setOpen(true)
      }}>Setup instructions</button>
    </div>
    {open && <EditorDialog id={dialogId} title="Twitch setup instructions" closeLabel="Close setup instructions"
      busy={false} onClose={() => setOpen(false)} error={error} className="twitch-setup-dialog">
      <div className="command-dialog-panels">
        <p tabIndex={-1} data-editor-focus>Choose the Twitch account that will send replies and the channel where HeetKit should read and reply to chat.</p>
        <ol>
          <li><strong>Register your application</strong>
            <ul>
              <li>Sign in to Twitch Developer Console with two-factor authentication enabled.</li>
              <li>Under Applications, choose <strong>Register Your Application</strong>.</li>
              <li>Enter a name and select the <strong>Confidential</strong> client type.</li>
              <li>Add the exact callback below under <strong>OAuth Redirect URLs</strong>.</li>
              <li>Choose a category and create the app.</li>
            </ul>
            <div className="twitch-setup-callback">
              <div className="settings-callback">
                <div><span>OAuth callback URL</span><code>{callback || 'Unavailable'}</code></div>
                <button type="button" className="secondary" aria-label="Copy OAuth callback URL" disabled={!callback}
                  onClick={(event) => void copy(event.currentTarget)}>Copy</button>
              </div>
              {desktop
                ? <button type="button" className="secondary" onClick={() => void openConsole()}>Open Twitch Developer Console</button>
                : <a className="secondary" href={consoleUrl} target="_blank" rel="noopener noreferrer">Open Twitch Developer Console</a>}
            </div>
            {copied && <p role="status">OAuth callback URL copied.</p>}
          </li>
          <li><strong>Enter the application and account details</strong>
            <ul>
              <li>Close these instructions to edit the fields. You can reopen them while you work.</li>
              <li>Open <strong>Manage</strong> beside your registered app in Twitch.</li>
              <li>Copy its Client ID into <strong>{desktop ? 'Twitch application client ID' : 'Client ID'}</strong>.</li>
              <li>Enter the sending account’s login in <strong>Bot account login</strong>.</li>
              <li>Enter the broadcaster’s login in <strong>Target channel login</strong>.</li>
              <li>Use a Twitch user ID lookup that accepts a login to find each account’s numeric ID.</li>
              <li>Enter those IDs in <strong>Bot account user ID</strong> and <strong>Target channel user ID</strong>.</li>
            </ul>
            <p>Enter logins without an @ or URL.</p>
          </li>
          <li><strong>Save the settings and apply the secret</strong>
            <ul>
              <li>Under <strong>Authorization, status and save</strong>, choose {desktop ? <strong>Save for later</strong> : <strong>Save Twitch settings</strong>}.</li>
              <li>On the application’s Twitch <strong>Manage</strong> page, choose <strong>New Secret</strong>.</li>
              <li>Paste it into <strong>Twitch client secret</strong> and keep it private. Generating a new secret invalidates the old one.</li>
              {desktop ? <>
                <li>Choose <strong>Add secret &amp; restart</strong> or <strong>Replace secret &amp; restart</strong>.</li>
                <li>If you saved the secret separately, choose <strong>Restart now</strong> to apply pending changes.</li>
              </> : <>
                <li>Choose <strong>Add secret</strong> or <strong>Replace secret</strong>. This stops the session and clears prior authorization.</li>
                <li>If the secret is managed externally, set it on the Server host and restart the Server.</li>
              </>}
            </ul>
          </li>
          <li><strong>Give the sending account channel access</strong>
            <ul>
              <li>If the sending account is the broadcaster, skip this step.</li>
              <li>For a separate bot, the broadcaster types <code>/mod bot_login</code> in the target channel’s Twitch chat, using the sending account’s login.</li>
            </ul>
          </li>
          <li><strong>Authorize and connect</strong>
            <ul>
              {desktop ? <>
                <li>On Dashboard, choose <strong>Start Bot</strong>.</li>
                <li>Choose <strong>Authorize Twitch</strong> if prompted.</li>
              </> : <li>In Settings, choose <strong>Connect Twitch</strong>.</li>}
              <li>Sign in to Twitch as the sending account and approve access.</li>
              {!desktop && <>
                <li>Return to the original signed-in Settings tab.</li>
                {callbackMode === 'paste' && <li>Copy the full URL from the callback error page into that tab. Choose <strong>Complete authorization</strong> within five minutes and keep the URL private.</li>}
                <li>On Dashboard, choose <strong>Connect</strong> in Manual mode. Always On connects automatically, Stream Only waits for a live stream, and Disabled keeps chat stopped.</li>
              </>}
              <li>Wait for Dashboard to show <strong>Connected</strong>.</li>
              <li>Send <code>!help</code> from a permitted account in the target channel and check for a reply. This uses the default command and prefix.</li>
            </ul>
          </li>
        </ol>
      </div>
    </EditorDialog>}
  </>
}
