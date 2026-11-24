import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

// Quality Check settings for one product (Products page, admin only).
// Weigh for QC, the package that gets weighed (bag, pan...), its target weight,
// tolerance and scale unit. Production runs then show weight boxes for this
// product and flag averages outside target ± tolerance. QC weights never change
// inventory or base units. Changing a target never changes weights already
// recorded (each check keeps the target it was judged against).
//
// refreshKey: change it when the product's conversions change, so the
// "bag size changed" reminder is re-checked.

const EMPTY = { enabled: true, package_unit_id: '', target_weight: '', tolerance: '', scale_unit: 'lb', notes: '' }

function fmt(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString('en-US', { maximumFractionDigits: 3 })
}

export default function ProductQcCard({ productId, refreshKey }) {
  const [data,    setData]    = useState(null)      // {spec, package_choices, scale_units, samples}
  const [editing, setEditing] = useState(false)
  const [form,    setForm]    = useState(EMPTY)
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    try {
      const res = await axios.get(`/api/products/${productId}/qc`)
      setData(res.data)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not load the QC settings.')
    }
  }, [productId])

  useEffect(() => { load() }, [load, refreshKey])

  const startEdit = () => {
    const s = data?.spec
    setForm(s ? {
      enabled:         s.enabled,
      package_unit_id: String(s.package_unit_id),
      target_weight:   String(s.target_weight),
      tolerance:       String(s.tolerance),
      scale_unit:      s.scale_unit,
      notes:           s.notes || '',
    } : {
      ...EMPTY,
      // Suggest a bag when the product has one
      package_unit_id: String(data?.package_choices.find(u => u.name.toLowerCase() === 'bag')?.id || ''),
    })
    setError(null)
    setEditing(true)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const res = await axios.put(`/api/products/${productId}/qc`, {
        enabled:         form.enabled,
        package_unit_id: form.package_unit_id ? parseInt(form.package_unit_id) : null,
        target_weight:   form.target_weight,
        tolerance:       form.tolerance || 0,
        scale_unit:      form.scale_unit,
        notes:           form.notes,
      })
      setData(d => ({ ...d, spec: res.data.spec }))
      setEditing(false)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not save the QC settings.')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!confirm('Remove the QC settings for this product? Weights already recorded on production runs are kept.')) return
    try {
      await axios.delete(`/api/products/${productId}/qc`)
      setData(d => ({ ...d, spec: null }))
      setEditing(false)
    } catch (e) {
      setError(e.response?.data?.error || 'Could not remove the QC settings.')
    }
  }

  const spec = data?.spec
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div className="card">
      <div className="card-header">
        <h2 className="card-title">Quality Check</h2>
        {data && !editing && (
          <button className="btn btn-secondary btn-sm" onClick={startEdit}>
            {spec ? 'Edit' : '+ Set up'}
          </button>
        )}
      </div>
      <div className="card-body">
        {error && <div className="alert alert-error" style={{ marginBottom: '0.75rem' }}>{error}</div>}

        {!data ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', margin: 0 }}>Loading...</p>
        ) : editing ? (
          <>
            <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
              <input type="checkbox" checked={form.enabled} onChange={e => set('enabled', e.target.checked)} />
              Weigh for QC on production runs
            </label>
            <div className="form-group">
              <label className="form-label">Package (what gets weighed)</label>
              <select className="input" value={form.package_unit_id} onChange={e => set('package_unit_id', e.target.value)}>
                <option value="">Select...</option>
                {data.package_choices.map(u => (
                  <option key={u.id} value={u.id}>{u.name}{u.is_base ? ' (base)' : ''}</option>
                ))}
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 80px', gap: '0.5rem' }}>
              <div className="form-group">
                <label className="form-label">Target weight</label>
                <input className="input" inputMode="decimal" value={form.target_weight}
                  onChange={e => set('target_weight', e.target.value)} placeholder="4.50" />
              </div>
              <div className="form-group">
                <label className="form-label">± Tolerance</label>
                <input className="input" inputMode="decimal" value={form.tolerance}
                  onChange={e => set('tolerance', e.target.value)} placeholder="0.30" />
              </div>
              <div className="form-group">
                <label className="form-label">Scale</label>
                <select className="input" value={form.scale_unit} onChange={e => set('scale_unit', e.target.value)}>
                  {data.scale_units.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Notes</label>
              <input className="input" value={form.notes} onChange={e => set('notes', e.target.value)}
                placeholder="Optional (e.g. weigh with the bag sealed)" />
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <button className="btn btn-primary btn-sm" onClick={save}
                disabled={saving || !form.package_unit_id || !form.target_weight}>
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
              {spec && (
                <button className="btn btn-ghost btn-sm" style={{ color: 'var(--error)', marginLeft: 'auto' }}
                  onClick={remove}>Remove</button>
              )}
            </div>
          </>
        ) : !spec ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', margin: 0 }}>
            Not weighed for QC. Set up a package and target weight to get {data.samples} weight boxes for
            this product on production runs.
          </p>
        ) : (
          <div style={{ fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <div>
              <span className={`badge ${spec.enabled ? 'badge-success' : 'badge-neutral'}`}>
                {spec.enabled ? 'Weighed for QC' : 'QC off'}
              </span>
            </div>
            <div>
              1 <span className="mono">{spec.package_unit}</span> should weigh{' '}
              <strong className="mono">{fmt(spec.target_weight)} {spec.scale_unit}</strong>
              {' '}± <span className="mono">{fmt(spec.tolerance)}</span>
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
              {data.samples} weights per production run · set by {spec.updated_by || '—'}
            </div>
            {spec.notes && <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{spec.notes}</div>}
            {spec.package_changed && (
              <div className="alert alert-warning" style={{ margin: '0.4rem 0 0', fontSize: '0.78rem' }}>
                The {spec.package_unit} size changed since this target was set
                ({fmt(spec.package_base_qty)} → {fmt(spec.package_base_now)} {spec.base_unit}).
                Check the target weight, then Save to confirm it.
              </div>
            )}
            {!spec.package_converts && (
              <div className="alert alert-error" style={{ margin: '0.4rem 0 0', fontSize: '0.78rem' }}>
                The {spec.package_unit} no longer converts to {spec.base_unit}. Add the conversion.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
