import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Select, type SelectOption } from '../src/components/Select'
import '../src/styles.css'

const options: SelectOption[] = [
  { value: 'alpha', label: 'Alpha' },
  { value: 'bravo', label: 'Bravo (unavailable)', disabled: true },
  { value: 'charlie', label: 'Charlie' },
  { value: 'delta', label: 'Delta with a long model identifier that wraps inside a narrow menu' },
  ...Array.from({ length: 40 }, (_, index) => ({ value: `model-${index}`, label: `Model ${String(index + 1).padStart(2, '0')}` })),
]

function Fixture() {
  const [value, setValue] = useState('alpha')
  const [disabled, setDisabled] = useState(false)
  const [hidden, setHidden] = useState(false)
  return <main style={{ padding: 16, maxWidth: 440 }}>
    <div className="card" id="clipping-panel" style={{ height: 180, overflow: 'auto', padding: 16 }} hidden={hidden}>
      <label className="form-field">Example selection
        <Select value={value} onChange={setValue} options={options} disabled={disabled} />
      </label>
      <div style={{ height: 400 }} />
    </div>
    <output aria-label="Committed value">{value}</output>
    <button onClick={() => setDisabled((previous) => !previous)}>Toggle disabled</button>
    <button onClick={() => setHidden((previous) => !previous)}>Toggle hidden</button>
    <label className="form-field">Disabled selection<Select value="alpha" onChange={setValue} options={options} disabled /></label>
    <label className="form-field">Empty selection<Select value="" onChange={setValue} options={[]} /></label>
  </main>
}

createRoot(document.getElementById('root')!).render(<Fixture />)
