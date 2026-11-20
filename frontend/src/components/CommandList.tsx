import { useState } from 'react'
import type { ChatReaction, CommandInfo, CustomCommandInfo } from '../bridge'
import { Select } from './Select'
import Switch from './Switch'
import { builtInCommandDescriptions, commandEditorCopy as copy } from '../i18n/commands.en'

export type CommandEntry =
  | { type: 'builtin'; item: CommandInfo }
  | { type: 'custom'; item: CustomCommandInfo }
  | { type: 'reaction'; item: ChatReaction }

const types = { builtin: 'Built-in', custom: 'Custom', reaction: 'Reaction' }
const statusOptions = [
  { value: 'active', label: 'Active' }, { value: 'disabled', label: 'Disabled' }, { value: 'all', label: 'All statuses' },
]
const typeOptions = [{ value: 'all', label: 'All types' }, ...Object.entries(types).map(([value, label]) => ({ value, label }))]
const sortOptions = [{ value: 'newest', label: 'Newest saved' }, { value: 'name', label: 'Name A–Z' }]
const roleLabels: Record<string, string> = { USER: 'Everyone', VIP: 'VIP', MODERATOR: 'Moderator', BROADCASTER: 'Broadcaster', SUBSCRIBER: 'Subscriber' }

function summarize(entry: CommandEntry, prefix: string) {
  if (entry.type === 'reaction') {
    const rule = entry.item
    return { id: rule.id, name: rule.text, sortName: rule.text, detail: rule.match_mode === 'exact' ? 'Exact match' : 'Contains',
      response: rule.responses[0], description: undefined, access: '', enabled: rule.enabled, order: rule.creation_order ?? 0 }
  }
  const command = entry.item
  const builtin = entry.type === 'builtin' ? entry.item : null
  const primary = builtin?.primary_name ?? command.name
  const name = prefix + primary
  const description = builtin
    ? Object.hasOwn(builtInCommandDescriptions, command.name)
      ? builtInCommandDescriptions[command.name]
      : builtin.description || builtin.help_text
    : undefined
  const response = entry.type === 'custom'
    ? entry.item.responses[0]
    : entry.type === 'builtin'
      ? entry.item.response_pool?.responses[0]
      : undefined
  return {
    id: entry.type === 'custom' ? entry.item.id : command.name,
    name, sortName: primary,
    detail: [builtin?.display_name, builtin?.hidden ? 'Administrative' : '', ...command.aliases.map((alias) => prefix + alias)].filter(Boolean).join(' · '),
    response,
    description: description === undefined
      ? undefined
      : command.name === 'weather'
        ? `${description} Try ${name} London.`
        : description,
    access: roleLabels[command.permission] ?? command.permission,
    enabled: command.enabled && !builtin?.removed,
    order: entry.type === 'custom' ? entry.item.creation_order ?? 0 : 0,
    unavailable: builtin?.available === false ? builtin.unavailable_reason || 'Unavailable' : undefined,
  }
}

export default function CommandList({ entries, prefix, busy, canCreateCommand, canCreateReaction, onCreate, onEdit, onDelete, onToggle }: {
  entries: CommandEntry[]
  prefix: string
  busy: boolean
  canCreateCommand: boolean
  canCreateReaction: boolean
  onCreate: (type: 'custom' | 'reaction') => void
  onEdit: (entry: CommandEntry) => void
  onDelete: (entry: Exclude<CommandEntry, { type: 'builtin' }>) => void
  onToggle: (entry: CommandEntry, enabled: boolean) => void
}) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('active')
  const [type, setType] = useState('all')
  const [sort, setSort] = useState('newest')
  const search = query.trim().toLocaleLowerCase()
  const visible = entries.map((entry) => ({ entry, ...summarize(entry, prefix) }))
    .filter((row) => (status === 'all' || row.enabled === (status === 'active'))
      && (type === 'all' || row.entry.type === type)
      && [row.name, row.detail, row.response, row.description].some((value) => value?.toLocaleLowerCase().includes(search)))
    .sort((left, right) => (sort === 'newest' ? right.order - left.order : left.sortName.localeCompare(right.sortName))
      || left.entry.type.localeCompare(right.entry.type) || left.id.localeCompare(right.id))

  return <section className="card command-list-card" id="command-list" aria-label="Command list">
    <div className="command-list-toolbar">
      <input id="command-list-search" type="search" aria-label="Search commands and reactions" placeholder="Search commands and reactions…" value={query} onChange={(event) => setQuery(event.target.value)} />
      <div className="command-list-filters">
        <Select aria-label="Status" value={status} options={statusOptions} onChange={setStatus} />
        <Select aria-label="Type" value={type} options={typeOptions} onChange={setType} />
        <Select aria-label="Sort" value={sort} options={sortOptions} onChange={setSort} />
      </div>
      <div className="command-list-create">
        <Select className="command-create-trigger" aria-label={copy.create} value="" placeholder={copy.create}
          disabled={busy || (!canCreateCommand && !canCreateReaction)}
          options={[
            { value: 'custom', label: copy.createCommand, disabled: !canCreateCommand },
            { value: 'reaction', label: copy.createReaction, disabled: !canCreateReaction },
          ]}
          onChange={(type) => onCreate(type === 'custom' ? 'custom' : 'reaction')} />
      </div>
    </div>
    {visible.length ? <div className="command-list-frame">
      <table className="unified-command-table" role="table" aria-label="Commands and chat reactions">
        <colgroup><col className="command-state-column" /><col className="command-name-column" /><col className="command-type-column" /><col /><col className="command-access-column" /><col className="command-action-column" /></colgroup>
        <thead role="rowgroup"><tr role="row">
          <th scope="col" role="columnheader">Enabled</th><th scope="col" role="columnheader">Name / Match</th>
          <th scope="col" role="columnheader">Type</th><th scope="col" role="columnheader">Response and purpose</th>
          <th scope="col" role="columnheader">Access</th><th scope="col" role="columnheader"><span className="sr-only">Actions</span></th>
        </tr></thead>
        <tbody role="rowgroup">{visible.map(({ entry, ...row }) => <tr role="row" key={`${entry.type}:${row.id}`}>
          <td role="cell" className="command-list-state"><Switch checked={row.enabled} disabled={busy} ariaLabel={`Enable ${row.name}`}
            onCheckedChange={(enabled) => onToggle(entry, enabled)}><span className="sr-only">{row.enabled ? 'Enabled' : 'Disabled'}</span></Switch></td>
          <th scope="row" role="rowheader" className="command-list-name">
            <strong>{row.name}</strong>{row.detail && <small>{row.detail}</small>}
          </th>
          <td role="cell" className="command-list-type"><span className={`command-type-label type-${entry.type}`}>{types[entry.type]}</span></td>
          <td role="cell" className="command-list-response">
            {row.response && <span title={row.response}>{row.response}</span>}
            {row.description && <small className="command-list-description">{row.description}</small>}
            {row.unavailable && <small title={row.unavailable}>Unavailable</small>}
          </td>
          <td role="cell" className="command-list-access">{row.access || <span aria-label="No role restriction">—</span>}</td>
          <td role="cell" className="command-list-actions">
            {entry.type !== 'builtin' && <button className="ghost destructive" disabled={busy} aria-label={`Delete ${row.name}`}
              onClick={() => onDelete(entry)}>Delete</button>}
            <button className="secondary" disabled={busy} onClick={() => onEdit(entry)} aria-label={`Edit ${row.name}`}>Edit</button>
          </td>
        </tr>)}</tbody>
      </table>
    </div> : <p className="command-list-empty muted">{busy && !entries.length ? 'Loading commands and reactions…' : 'No matching commands or reactions.'}</p>}
  </section>
}
