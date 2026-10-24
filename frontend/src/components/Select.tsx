import { type KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  disabled?: boolean
  id?: string
  className?: string
  searchable?: boolean
  'aria-label'?: string
  'aria-describedby'?: string
}

/** A single-choice listbox with optional model search; navigation previews until committed. */
export function Select({ value, onChange, options: allOptions, disabled = false, id, className = '', searchable = false, ...aria }: SelectProps) {
  const [query, setQuery] = useState('')
  const options = query ? allOptions.filter((option) => option.label.toLocaleLowerCase().includes(query.toLocaleLowerCase())) : allOptions
  const generatedId = useId()
  const triggerId = id ?? generatedId
  const listId = `${triggerId}-options`
  const trigger = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const search = useRef({ text: '', time: 0 })
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<string | null>(null)
  const [position, setPosition] = useState<{ left: number; top: number; minWidth: number; maxWidth: number; maxHeight: number } | null>(null)
  const selected = allOptions.find((option) => option.value === value)
  const activeIndex = options.findIndex((option) => option.value === active && !option.disabled)

  const dismiss = () => {
    setOpen(false)
    setPosition(null)
    setQuery('')
    search.current = { text: '', time: 0 }
  }
  const show = (fromEnd = false) => {
    if (disabled) return
    setActive((selected && !selected.disabled ? selected : options.filter((option) => !option.disabled).at(fromEnd ? -1 : 0))?.value ?? null)
    setOpen(true)
  }
  const choose = (option: SelectOption) => {
    if (disabled || option.disabled) return
    dismiss()
    trigger.current?.focus({ preventScroll: true })
    if (option.value !== value) onChange(option.value)
  }

  useEffect(() => {
    if (disabled) dismiss()
  }, [disabled])

  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const anchor = trigger.current
      const menu = list.current
      if (!anchor || !menu) return
      const rect = anchor.getBoundingClientRect()
      // Mounted pages/accordions may become hidden without unmounting this control.
      if (!anchor.getClientRects().length || rect.bottom < 0 || rect.top > window.innerHeight) {
        dismiss()
        return
      }
      // A portalled menu must close when its trigger scrolls behind a clipping ancestor.
      for (let parent = anchor.parentElement; parent && parent !== document.body && parent !== document.documentElement; parent = parent.parentElement) {
        const style = getComputedStyle(parent)
        const bounds = parent.getBoundingClientRect()
        const clips = /auto|scroll|hidden|clip/
        if ((clips.test(style.overflowY) && (rect.bottom <= bounds.top || rect.top >= bounds.bottom))
          || (clips.test(style.overflowX) && (rect.right <= bounds.left || rect.left >= bounds.right))) {
          dismiss()
          return
        }
      }
      const padding = 8
      const gap = 6
      const availableWidth = document.documentElement.clientWidth - padding * 2
      const minWidth = Math.min(Math.max(rect.width, 200), availableWidth)
      const maxWidth = Math.min(Math.max(rect.width, 360), availableWidth)
      const width = Math.max(minWidth, Math.min(menu.getBoundingClientRect().width, maxWidth))
      const below = Math.max(0, window.innerHeight - rect.bottom - gap - padding)
      const above = Math.max(0, rect.top - gap - padding)
      const height = Math.min(280, menu.scrollHeight)
      const down = below >= height || below >= above
      const maxHeight = Math.min(280, down ? below : above)
      const next = {
        minWidth,
        maxWidth,
        maxHeight,
        left: Math.max(padding, Math.min(rect.left, document.documentElement.clientWidth - width - padding)),
        top: down ? rect.bottom + gap : rect.top - gap - Math.min(height, maxHeight),
      }
      setPosition((previous) => previous && Object.keys(next).every((key) => previous[key as keyof typeof next] === next[key as keyof typeof next]) ? previous : next)
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    const observer = new ResizeObserver(place)
    if (trigger.current) observer.observe(trigger.current)
    if (list.current) observer.observe(list.current)
    const visibility = new MutationObserver(place)
    visibility.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['hidden'] })
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
      observer.disconnect()
      visibility.disconnect()
    }
  }, [open, options])

  useLayoutEffect(() => {
    if (!open || !position || activeIndex < 0) return
    const menu = searchable ? list.current?.querySelector<HTMLElement>('[role=listbox]') : list.current
    const option = list.current?.querySelectorAll<HTMLElement>('[role=option]')[activeIndex]
    if (!menu || !option) return
    // Scroll only the listbox, never the surrounding application/document.
    const bounds = menu.getBoundingClientRect()
    const item = option.getBoundingClientRect()
    if (item.top < bounds.top) menu.scrollTop += item.top - bounds.top
    else if (item.bottom > bounds.bottom) menu.scrollTop += item.bottom - bounds.bottom
  }, [open, activeIndex, position, searchable])

  useLayoutEffect(() => {
    if (open && searchable && position && !list.current?.contains(document.activeElement)) {
      list.current?.querySelector<HTMLInputElement>('input')?.focus({ preventScroll: true })
    }
  }, [open, searchable, position])

  useEffect(() => {
    if (!open) return
    const outside = (event: Event) => {
      const target = event.target as Node
      if (!trigger.current?.contains(target) && !list.current?.contains(target)) dismiss()
    }
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('focusin', outside)
    return () => {
      document.removeEventListener('pointerdown', outside, true)
      document.removeEventListener('focusin', outside)
    }
  }, [open])

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement | HTMLInputElement>) => {
    if (event.key === 'Tab') {
      dismiss()
      if (searchable) trigger.current?.focus({ preventScroll: true })
      return
    }
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault()
        event.stopPropagation()
        dismiss()
        trigger.current?.focus({ preventScroll: true })
      }
      return
    }
    const enabled = options.filter((option) => !option.disabled)
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      event.stopPropagation()
      if (!open) show(event.key === 'ArrowUp' || event.key === 'End')
      if (event.key === 'Home' || event.key === 'End') setActive(enabled.at(event.key === 'Home' ? 0 : -1)?.value ?? null)
      else if (open && enabled.length) {
        const index = enabled.findIndex((option) => option.value === active)
        const next = index < 0 ? (event.key === 'ArrowDown' ? 0 : enabled.length - 1) : (index + (event.key === 'ArrowDown' ? 1 : -1) + enabled.length) % enabled.length
        setActive(enabled[next].value)
      }
    } else if (event.key === 'Enter' || (event.key === ' ' && event.currentTarget.tagName !== 'INPUT')) {
      event.preventDefault()
      event.stopPropagation()
      if (!open) show()
      else if (activeIndex >= 0) choose(options[activeIndex])
    } else if (event.currentTarget.tagName !== 'INPUT' && event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
      event.preventDefault()
      const now = Date.now()
      const typed = now - search.current.time > 700 ? event.key : search.current.text + event.key
      search.current = { text: typed.toLocaleLowerCase(), time: now }
      const term = [...typed].every((letter) => letter.toLocaleLowerCase() === typed[0].toLocaleLowerCase()) ? typed[0].toLocaleLowerCase() : typed.toLocaleLowerCase()
      const start = enabled.findIndex((option) => option.value === (open ? active : value))
      const ordered = [...enabled.slice(start + 1), ...enabled.slice(0, start + 1)]
      const match = ordered.find((option) => option.label.toLocaleLowerCase().startsWith(term))
      if (!open) show()
      if (match) setActive(match.value)
    }
  }

  return <>
    <button
      {...aria}
      ref={trigger}
      id={triggerId}
      type="button"
      role="combobox"
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-controls={open ? listId : undefined}
      aria-activedescendant={open && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
      disabled={disabled}
      data-value={value}
      className={`select-trigger ${className}`.trim()}
      onClick={() => open ? dismiss() : show()}
      onKeyDown={onKeyDown}
    >
      <span className="select-value">{selected?.label ?? 'Select…'}</span>
      <svg className="select-caret" width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m5 7.5 5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
    </button>
    {open && createPortal(<div
      ref={list}
      id={searchable ? undefined : listId}
      role={searchable ? undefined : 'listbox'}
      aria-labelledby={searchable ? undefined : triggerId}
      className="select-menu"
      style={{ ...position, visibility: position ? 'visible' : 'hidden' }}
      onPointerDown={(event) => { if (!(event.target instanceof HTMLInputElement)) event.preventDefault() }}
    >
      {searchable && <input className="select-search" aria-label="Search models" type="search" autoFocus value={query} onChange={(event) => { setQuery(event.target.value); setActive(null) }} onKeyDown={onKeyDown} aria-controls={listId} aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined} />}
      <div id={searchable ? listId : undefined} role={searchable ? 'listbox' : undefined} aria-labelledby={searchable ? triggerId : undefined} style={searchable ? { maxHeight: Math.max(0, (position?.maxHeight ?? 280) - 70), overflowY: 'auto' } : { display: 'contents' }}>
      {options.map((option, index) => <div
        key={option.value}
        id={`${listId}-${index}`}
        role="option"
        aria-selected={option.value === value}
        aria-disabled={option.disabled || undefined}
        data-value={option.value}
        data-active={option.value === active && !option.disabled}
        className="select-option"
        onPointerMove={() => { if (!option.disabled) setActive(option.value) }}
        onClick={() => choose(option)}
      >
        <span>{option.label}</span><span className="select-check" aria-hidden="true">{option.value === value ? '✓' : ''}</span>
      </div>)}
      {!options.length && <div className="select-empty">No options available</div>}
      </div>
    </div>, document.body)}
  </>
}
