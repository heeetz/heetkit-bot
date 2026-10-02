import type { LogEntry } from '../bridge'

type LogContextValue = string | number | boolean
type FieldEmphasis = 'primary' | 'secondary' | 'metric'

interface FieldSpec {
  key: string
  emphasis: FieldEmphasis
}

const eventLabels: Record<string, string> = {
  'chat.incoming': 'CHAT IN',
  'chat.outgoing': 'CHAT OUT',
  'chat.filtered': 'CHAT FILTERED',
  'command.invoke': 'COMMAND',
  'command.cooldown': 'COOLDOWN',
  'twitch.subscribe': 'TWITCH',
  'twitch.connected': 'TWITCH READY',
  'twitch.disconnected': 'TWITCH LOST',
  'twitch.recovered': 'TWITCH RECOVERED',
  'twitch.auth_required': 'TWITCH AUTH',
  'twitch.failed': 'TWITCH FAILED',
  'twitch.reconnect': 'TWITCH RECONNECT',
  'twitch.start': 'TWITCH START',
  'twitch.stop': 'TWITCH STOP',
  'twitch.shutdown': 'TWITCH STOP',
  'ai.request_config': 'AI CONFIG',
  'ai.request_start': 'AI REQUEST',
  'ai.request_finish': 'AI RESPONSE',
  'ai.fallback': 'AI FALLBACK',
  'ai.failure': 'AI FAILURE',
}

const contextLabels: Record<string, string> = {
  username: 'user',
  command: 'command',
  channel: 'channel',
  retry_after_seconds: 'retry',
  duration_seconds: 'duration',
  model: 'model',
  provider: 'provider',
  setting: 'setting',
  action: 'action',
}

const eventFieldLayouts: Record<string, FieldSpec[]> = {
  'chat.incoming': [
    { key: 'username', emphasis: 'primary' },
    { key: 'channel', emphasis: 'secondary' },
  ],
  'chat.outgoing': [
    { key: 'username', emphasis: 'primary' },
    { key: 'channel', emphasis: 'secondary' },
  ],
  'chat.filtered': [
    { key: 'username', emphasis: 'primary' },
    { key: 'channel', emphasis: 'secondary' },
  ],
  'command.invoke': [
    { key: 'command', emphasis: 'primary' },
    { key: 'username', emphasis: 'primary' },
    { key: 'channel', emphasis: 'secondary' },
  ],
  'command.cooldown': [
    { key: 'retry_after_seconds', emphasis: 'metric' },
    { key: 'command', emphasis: 'primary' },
    { key: 'username', emphasis: 'primary' },
  ],
  'ai.request_config': [
    { key: 'model', emphasis: 'primary' },
    { key: 'provider', emphasis: 'secondary' },
  ],
  'ai.request_start': [
    { key: 'model', emphasis: 'primary' },
    { key: 'provider', emphasis: 'secondary' },
  ],
  'ai.request_finish': [
    { key: 'model', emphasis: 'primary' },
    { key: 'duration_seconds', emphasis: 'metric' },
    { key: 'provider', emphasis: 'secondary' },
  ],
  'ai.fallback': [
    { key: 'model', emphasis: 'primary' },
    { key: 'provider', emphasis: 'secondary' },
  ],
  'ai.failure': [
    { key: 'model', emphasis: 'primary' },
    { key: 'provider', emphasis: 'secondary' },
  ],
  'twitch.subscribe': [{ key: 'channel', emphasis: 'primary' }],
  'twitch.connected': [
    { key: 'channel', emphasis: 'primary' },
    { key: 'username', emphasis: 'secondary' },
  ],
  'twitch.disconnected': [{ key: 'channel', emphasis: 'primary' }],
  'twitch.recovered': [{ key: 'channel', emphasis: 'primary' }],
  'twitch.auth_required': [{ key: 'channel', emphasis: 'primary' }],
  'twitch.failed': [{ key: 'channel', emphasis: 'primary' }],
  'twitch.reconnect': [
    { key: 'channel', emphasis: 'primary' },
    { key: 'action', emphasis: 'primary' },
  ],
  'twitch.start': [
    { key: 'channel', emphasis: 'primary' },
    { key: 'action', emphasis: 'primary' },
  ],
  'twitch.stop': [
    { key: 'channel', emphasis: 'primary' },
    { key: 'action', emphasis: 'primary' },
  ],
  'twitch.shutdown': [
    { key: 'channel', emphasis: 'primary' },
    { key: 'action', emphasis: 'primary' },
  ],
}

const settingsFieldOrder = ['setting', 'action', 'command', 'channel', 'model', 'provider']
const selfDescribingFields = new Set([
  'username',
  'command',
  'channel',
  'retry_after_seconds',
  'duration_seconds',
  'model',
])

export function logEventClassNames(eventKind: string | null) {
  if (!eventKind) {
    return 'event-generic'
  }
  return `event-${eventKind.split('.')[0]} event-${eventKind.replaceAll('.', '-')}`
}

function eventLabel(eventKind: string) {
  if (eventLabels[eventKind]) {
    return eventLabels[eventKind]
  }
  if (eventKind.startsWith('settings.')) {
    return 'SETTINGS'
  }
  return eventKind.replaceAll('.', ' ').toUpperCase()
}

function prefixedValue(value: LogContextValue, prefix: string) {
  const text = String(value)
  return text.startsWith(prefix) ? text : `${prefix}${text}`
}

function formatSeconds(value: LogContextValue, suffix = '') {
  const numericValue = typeof value === 'number' ? value : Number(value)
  const formatted = Number.isFinite(numericValue) ? numericValue.toFixed(2) : String(value)
  return `${formatted}s${suffix}`
}

function formatContextValue(key: string, value: LogContextValue) {
  if (key === 'username') {
    return prefixedValue(value, '@')
  }
  if (key === 'command') {
    return prefixedValue(value, '!')
  }
  if (key === 'channel') {
    return prefixedValue(value, '#')
  }
  if (key === 'retry_after_seconds') {
    return formatSeconds(value, ' remaining')
  }
  if (key === 'duration_seconds') {
    return formatSeconds(value)
  }
  return String(value)
}

function orderedFields(entry: LogEntry): FieldSpec[] {
  const configured = entry.event_kind?.startsWith('settings.')
    ? settingsFieldOrder.map((key) => ({ key, emphasis: 'secondary' as const }))
    : eventFieldLayouts[entry.event_kind ?? ''] ?? []
  const configuredKeys = new Set(configured.map(({ key }) => key))
  return [
    ...configured,
    ...Object.keys(entry.context)
      .filter((key) => !configuredKeys.has(key))
      .map((key) => ({ key, emphasis: 'secondary' as const })),
  ].filter(({ key }) => entry.context[key] !== undefined)
}

export default function LogEventSummary({ entry }: { entry: LogEntry }) {
  if (!entry.event_kind) {
    return null
  }

  return (
    <div className="log-event-summary">
      <span className="log-event-kind">{eventLabel(entry.event_kind)}</span>
      {orderedFields(entry).map(({ key, emphasis }) => {
        const label = contextLabels[key] ?? key.replaceAll('_', ' ')
        const value = formatContextValue(key, entry.context[key])
        return (
          <span
            className={`log-field is-${emphasis}`}
            key={key}
            aria-label={`${label}: ${value}`}
            title={`${label}: ${value}`}
          >
            {!selfDescribingFields.has(key) && <span className="log-field-label">{label}</span>}
            <span className="log-field-value">{value}</span>
          </span>
        )
      })}
    </div>
  )
}
