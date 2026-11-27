import { useState } from 'react'
import type { ChatReaction, CommandInfo, CustomCommandInfo } from '../bridge'
import { Select } from './Select'
import Switch from './Switch'
import { commandsText } from '../i18n/commands'
import { fmt, useCatalog } from '../i18n/core'

export type CommandEntry =
  | { type: 'builtin'; item: CommandInfo }
  | { type: 'custom'; item: CustomCommandInfo }
  | { type: 'reaction'; item: ChatReaction }

type Strings = typeof commandsText.en
type Labels = Record<string, string>

function summarize(entry: CommandEntry, prefix: string, strings: Strings) {
  const text = strings.list
  const descriptions: Labels = strings.builtInDescriptions
  const roleLabels: Labels = text.roles
  if (entry.type === 'reaction') {
    const rule = entry.item
    return { id: rule.id, name: rule.text, sortName: rule.text, detail: rule.match_mode === 'exact' ? text.exactMatch : text.contains,
      response: rule.responses[0], description: undefined, access: '', enabled: rule.enabled, order: rule.creation_order ?? 0 }
  }
  const command = entry.item
  const builtin = entry.type === 'builtin' ? entry.item : null
  const primary = builtin?.primary_name ?? command.name
  const name = prefix + primary
  const description = builtin
    ? Object.hasOwn(descriptions, command.name)
      ? descriptions[command.name]
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
    detail: [builtin?.display_name, builtin?.hidden ? text.administrative : '', ...command.aliases.map((alias) => prefix + alias)].filter(Boolean).join(' · '),
    response,
    description: description === undefined
      ? undefined
      : command.name === 'weather'
        ? fmt(text.weatherDescription, { description, name })
        : description,
    access: roleLabels[command.permission] ?? command.permission,
    enabled: command.enabled && !builtin?.removed,
    order: entry.type === 'custom' ? entry.item.creation_order ?? 0 : 0,
    unavailable: builtin?.available === false ? builtin.unavailable_reason || text.unavailable : undefined,
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
  const strings = useCatalog(commandsText)
  const copy = strings.editor
  const text = strings.list
  const types = text.types
  const statusOptions = [
    { value: 'active', label: text.statusActive }, { value: 'disabled', label: text.statusDisabled }, { value: 'all', label: text.statusAll },
  ]
  const typeOptions = [{ value: 'all', label: text.typeAll }, ...Object.entries(types).map(([value, label]) => ({ value, label }))]
  const sortOptions = [{ value: 'newest', label: text.sortNewest }, { value: 'name', label: text.sortName }]
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('active')
  const [type, setType] = useState('all')
  const [sort, setSort] = useState('newest')
  const search = query.trim().toLocaleLowerCase()
  const visible = entries.map((entry) => ({ entry, ...summarize(entry, prefix, strings) }))
    .filter((row) => (status === 'all' || row.enabled === (status === 'active'))
      && (type === 'all' || row.entry.type === type)
      && [row.name, row.detail, row.response, row.description].some((value) => value?.toLocaleLowerCase().includes(search)))
    .sort((left, right) => (sort === 'newest' ? right.order - left.order : left.sortName.localeCompare(right.sortName))
      || left.entry.type.localeCompare(right.entry.type) || left.id.localeCompare(right.id))

  return <section className="card command-list-card" id="command-list" aria-label={text.label}>
    <div className="command-list-toolbar">
      <input id="command-list-search" type="search" aria-label={text.search} placeholder={text.searchPlaceholder} value={query} onChange={(event) => setQuery(event.target.value)} />
      <div className="command-list-filters">
        <Select aria-label={text.status} value={status} options={statusOptions} onChange={setStatus} />
        <Select aria-label={text.type} value={type} options={typeOptions} onChange={setType} />
        <Select aria-label={text.sort} value={sort} options={sortOptions} onChange={setSort} />
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
      <table className="unified-command-table" role="table" aria-label={text.table}>
        <colgroup><col className="command-state-column" /><col className="command-name-column" /><col className="command-type-column" /><col /><col className="command-access-column" /><col className="command-action-column" /></colgroup>
        <thead role="rowgroup"><tr role="row">
          <th scope="col" role="columnheader">{text.columnEnabled}</th><th scope="col" role="columnheader">{text.columnName}</th>
          <th scope="col" role="columnheader">{text.columnType}</th><th scope="col" role="columnheader">{text.columnResponse}</th>
          <th scope="col" role="columnheader">{text.columnAccess}</th><th scope="col" role="columnheader"><span className="sr-only">{text.columnActions}</span></th>
        </tr></thead>
        <tbody role="rowgroup">{visible.map(({ entry, ...row }) => <tr role="row" key={`${entry.type}:${row.id}`}>
          <td role="cell" className="command-list-state"><Switch checked={row.enabled} disabled={busy} ariaLabel={fmt(text.enableNamed, { name: row.name })}
            onCheckedChange={(enabled) => onToggle(entry, enabled)}><span className="sr-only">{row.enabled ? text.enabled : text.disabled}</span></Switch></td>
          <th scope="row" role="rowheader" className="command-list-name">
            <strong>{row.name}</strong>{row.detail && <small>{row.detail}</small>}
          </th>
          <td role="cell" className="command-list-type"><span className={`command-type-label type-${entry.type}`}>{types[entry.type]}</span></td>
          <td role="cell" className="command-list-response">
            {row.response && <span title={row.response}>{row.response}</span>}
            {row.description && <small className="command-list-description">{row.description}</small>}
            {row.unavailable && <small title={row.unavailable}>{text.unavailable}</small>}
          </td>
          <td role="cell" className="command-list-access">{row.access || <span aria-label={text.noRole}>—</span>}</td>
          <td role="cell" className="command-list-actions"><div className="command-list-buttons">
            {entry.type !== 'builtin' && <button className="ghost destructive" disabled={busy} aria-label={fmt(text.deleteNamed, { name: row.name })}
              onClick={() => onDelete(entry)}>{text.delete}</button>}
            <button className="secondary" disabled={busy} onClick={() => onEdit(entry)} aria-label={fmt(text.editNamed, { name: row.name })}>{text.edit}</button>
          </div></td>
        </tr>)}</tbody>
      </table>
    </div> : <p className="command-list-empty muted">{busy && !entries.length ? text.loading : text.empty}</p>}
  </section>
}
