export interface AppStatus {
  running: boolean
  uptime_seconds: number
  channel: string
  account: string
}

interface PythonApi {
  get_app_status(): Promise<AppStatus>
  start_bot(): Promise<ActionResult>
  stop_bot(): Promise<ActionResult>
}

interface ActionResult {
  ok: boolean
  changed: boolean
  error?: string
}

declare global {
  interface Window {
    pywebview?: {
      api: PythonApi
    }
  }
}

let pendingBridge: Promise<PythonApi> | null = null

export async function waitForBridge(): Promise<PythonApi> {
  if (window.pywebview?.api) {
    return window.pywebview.api
  }
  if (pendingBridge) {
    return pendingBridge
  }

  pendingBridge = new Promise((resolve, reject) => {
    const timeout = window.setTimeout(
      () => reject(new Error('The desktop backend did not become available.')),
      8000,
    )
    window.addEventListener(
      'pywebviewready',
      () => {
        window.clearTimeout(timeout)
        if (window.pywebview?.api) {
          resolve(window.pywebview.api)
        } else {
          reject(new Error('The desktop backend bridge is unavailable.'))
        }
      },
      { once: true },
    )
  })
  try {
    return await pendingBridge
  } catch (error) {
    pendingBridge = null
    throw error
  }
}
