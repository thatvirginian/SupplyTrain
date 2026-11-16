// =============================================================================
// core/components/LineItemEditor.jsx
// =============================================================================
// Product search + editable list of lines (product, quantity, unit), used by
// Transfers and Unscheduled Orders.
//
// Props
//   lines        [{ product_id, product_name, quantity, unit_id, units: [{id,name}] , meta? }]
//   onChange     (nextLines) => void
//   searchUrl    API that returns [{ product_id, product_name, units, default_unit_id, ... }]
//   searchParams extra query params for searchUrl (e.g. { vendor_id })
//   metaFor      optional (result) => string shown under a search result
//   disabled     read-only when true
//   emptyText    shown when there are no lines
// =============================================================================
import { useState, useEffect } from 'react'
import axios from 'axios'
import { NumericInput } from './NumericInput.jsx'
import { useDebounce } from '../hooks/useDebounce.js'
import '../styles/line-item-editor.css'

export default function LineItemEditor({
  lines, onChange, searchUrl, searchParams = {}, metaFor, disabled = false,
  emptyText = 'No items yet. Search above to add one.',
}) {
  const [search,    setSearch]    = useState('')
  const [results,   setResults]   = useState([])
  const [searching, setSearching] = useState(false)
  const debounced = useDebounce(search, 300)
  const paramsKey = JSON.stringify(searchParams)

  useEffect(() => {
    if (!debounced || debounced.trim().length < 2) { setResults([]); return }
    let cancelled = false
    setSearching(true)
    axios.get(searchUrl, { params: { ...JSON.parse(paramsKey), search: debounced.trim() } })
      .then(res => { if (!cancelled) setResults(res.data || []) })
      .catch(() => { if (!cancelled) setResults([]) })
      .finally(() => { if (!cancelled) setSearching(false) })
    return () => { cancelled = true }
  }, [debounced, searchUrl, paramsKey])

  const addProduct = (p) => {
    setSearch('')
    setResults([])
    if (lines.some(l => l.product_id === p.product_id)) return   // already on the list
    onChange([...lines, {
      product_id:   p.product_id,
      product_name: p.product_name,
      quantity:     '',
      unit_id:      p.default_unit_id || p.units?.[0]?.id || '',
      units:        p.units || [],
      meta:         metaFor ? metaFor(p) : '',
    }])
  }

  const update = (idx, changes) =>
    onChange(lines.map((l, i) => i === idx ? { ...l, ...changes } : l))

  const remove = (idx) => onChange(lines.filter((_, i) => i !== idx))

  const onList = new Set(lines.map(l => l.product_id))

  return (
    <div className="line-editor">
      {!disabled && (
        <div className="line-editor-search">
          <input className="input" placeholder="Search products to add…"
            value={search} onChange={e => setSearch(e.target.value)} />
          {searching && <span className="line-editor-hint">Searching…</span>}
          {results.length > 0 && (
            <div className="line-editor-results">
              {results.map(p => (
                <button key={p.product_id} type="button"
                  className={`line-editor-result ${onList.has(p.product_id) ? 'is-added' : ''}`}
                  onClick={() => addProduct(p)}>
                  <span>{p.product_name}</span>
                  <span className="line-editor-meta">
                    {onList.has(p.product_id) ? 'on the list' : (metaFor ? metaFor(p) : '')}
                  </span>
                </button>
              ))}
            </div>
          )}
          {!searching && search.trim().length >= 2 && debounced === search && results.length === 0 && (
            <span className="line-editor-hint">No matching products.</span>
          )}
        </div>
      )}

      {lines.length === 0 ? (
        <div className="line-editor-empty">{emptyText}</div>
      ) : (
        <div className="line-editor-rows">
          <div className="line-editor-row line-editor-row-header">
            <span>Product</span><span>Qty</span><span>Unit</span><span />
          </div>
          {lines.map((l, idx) => (
            <div key={l.product_id} className="line-editor-row">
              <div className="line-editor-name">
                <span>{l.product_name}</span>
                {l.meta && <span className="line-editor-meta">{l.meta}</span>}
              </div>
              <NumericInput className="input line-editor-qty" placeholder="0"
                value={l.quantity ?? ''} disabled={disabled}
                onChange={e => update(idx, { quantity: e.target.value })} />
              <select className="input line-editor-unit" value={l.unit_id || ''} disabled={disabled}
                onChange={e => update(idx, { unit_id: parseInt(e.target.value) })}>
                {(l.units || []).map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
              {!disabled ? (
                <button type="button" className="btn btn-ghost btn-sm line-editor-remove"
                  title="Remove" onClick={() => remove(idx)}>✕</button>
              ) : <span />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

