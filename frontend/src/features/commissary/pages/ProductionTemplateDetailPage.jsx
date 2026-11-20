import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import axios from 'axios'
import { useDebounce } from '../../../core/hooks/useDebounce'
import { useAuth } from '../../../core/auth/AuthContext.js'
import '../../../core/styles/shared-ui.css'
import './ProductionPages.css'
import '../../../core/styles/template-editor.css'
import '../../../core/styles/drag-and-drop.css'
import '../../catalog/pages/ProductDetailPage.css'   // uses .detail-grid from this stylesheet
import '../../catalog/pages/VendorItemsPage.css'     // uses .product-search-results from this stylesheet

// Production Template editor (admin, commissary GM).
// Sections of products; each product has ONE production unit (the unit the
// commissary enters what it made in). Only units that convert to the
// product's base unit are offered; the server checks again.

function InlineAddButton({ sectionId, insertAfterIdx, addingTo, setAddingTo, onAdd }) {
  const [search,  setSearch]  = useState('')
  const [results, setResults] = useState([])
  const debouncedSearch = useDebounce(search, 300)
  const isOpen = addingTo?.sectionId === sectionId && addingTo?.insertAfterIdx === insertAfterIdx

  useEffect(() => {
    if (!debouncedSearch || debouncedSearch.length < 2) { setResults([]); return }
    axios.get('/api/production-products', { params: { search: debouncedSearch, per_page: 8 } })
      .then(res => setResults(res.data.products || []))
      .catch(() => setResults([]))
  }, [debouncedSearch])

  const close = () => { setAddingTo(null); setSearch(''); setResults([]) }

  if (!isOpen) {
    return (
      <div className="inline-add-row">
        <button className="inline-add-btn"
          onClick={() => { setAddingTo({ sectionId, insertAfterIdx }); setSearch(''); setResults([]) }}
          title="Add product here">+</button>
      </div>
    )
  }

  return (
    <div className="inline-add-search">
      <input className="input" placeholder="Search products..."
        value={search} autoFocus
        onChange={e => setSearch(e.target.value)}
        onKeyDown={e => e.key === 'Escape' && close()} />
      {results.length > 0 && (
        <div className="product-search-results">
          {results.map(p => (
            <button key={p.id} className="product-search-result"
              onClick={() => { onAdd(sectionId, p, insertAfterIdx); close() }}>
              <span>{p.name}</span>
              <span className="result-meta">{p.category_name} · {p.base_unit}</span>
            </button>
          ))}
        </div>
      )}
      <button className="btn btn-ghost btn-sm" style={{ marginTop: '0.25rem' }} onClick={close}>
        Cancel
      </button>
    </div>
  )
}

// The product's production unit: a tag; click to change it.
function UnitPicker({ item, onChange }) {
  const [open,    setOpen]    = useState(false)
  const [choices, setChoices] = useState([])
  const [loading, setLoading] = useState(false)

  const openPicker = async () => {
    setOpen(true)
    setLoading(true)
    try {
      const res = await axios.get(`/api/production-products/${item.product_id}/units`)
      setChoices(res.data)
    } catch (e) {
      setChoices([{ id: item.unit_id, name: item.unit_name }])
    } finally {
      setLoading(false)
    }
  }

  if (!open) {
    return (
      <div className="count-units">
        <span className="count-unit-tag" title="Production unit">{item.unit_name}</span>
        {item.unit_id !== item.base_unit_id && (
          <span className="count-unit-default">base: {item.base_unit}</span>
        )}
        <button className="count-unit-add" onClick={openPicker}>change unit</button>
      </div>
    )
  }

  return (
    <div className="count-units">
      <select className="input" autoFocus disabled={loading}
        style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem', width: 'auto' }}
        value={item.unit_id}
        onChange={async e => { await onChange(item, parseInt(e.target.value)); setOpen(false) }}>
        {loading && <option value={item.unit_id}>Loading...</option>}
        {!loading && choices.map(u => (
          <option key={u.id} value={u.id}>{u.name}{u.is_base ? ' (base)' : ''}</option>
        ))}
      </select>
      <button className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>✕</button>
    </div>
  )
}

export default function ProductionTemplateDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()

  const [template,          setTemplate]          = useState(null)
  const [sections,          setSections]          = useState([])
  const [loading,           setLoading]           = useState(true)
  const [error,             setError]             = useState(null)      // page could not load
  const [actionError,       setActionError]       = useState(null)      // a change failed
  const [saving,            setSaving]            = useState(false)
  const [saved,             setSaved]             = useState(false)
  const [editing,           setEditing]           = useState(false)
  const [editForm,          setEditForm]          = useState({})
  const [orderDirty,        setOrderDirty]        = useState(false)
  const [savingOrder,       setSavingOrder]       = useState(false)
  const [collapsedSections, setCollapsedSections] = useState(new Set())
  const [showLocations,     setShowLocations]     = useState(false)
  const [commissaries,      setCommissaries]      = useState([])

  const [showAddSection,  setShowAddSection]  = useState(false)
  const [newSectionName,  setNewSectionName]  = useState('')
  const [addingSec,       setAddingSec]       = useState(false)
  const [editingSection,  setEditingSection]  = useState(null)
  const [editSectionName, setEditSectionName] = useState('')
  const [addingTo,        setAddingTo]        = useState(null)

  const dragItem = useRef(null)

  const fail = (e, fallback) => setActionError(e.response?.data?.error || fallback)

  const fetchTemplate = useCallback(async () => {
    try {
      const res = await axios.get(`/api/production-templates/${id}`)
      setTemplate(res.data)
      setSections(res.data.sections || [])
      setEditForm({ name: res.data.name, notes: res.data.notes || '' })
      setOrderDirty(false)
    } catch (e) {
      setError(e.response?.status === 404 ? 'Template not found.' : 'Could not load the template.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchTemplate()
    axios.get('/api/commissary-locations').then(res => setCommissaries(res.data)).catch(() => {})
  }, [fetchTemplate])

  const flashSaved = () => { setSaved(true); setTimeout(() => setSaved(false), 2000) }

  // ── Template ───────────────────────────────────────────────────────────────
  const handleSaveTemplate = async () => {
    setSaving(true)
    setActionError(null)
    try {
      await axios.put(`/api/production-templates/${id}`, editForm)
      setEditing(false)
      flashSaved()
      fetchTemplate()
    } catch (e) { fail(e, 'Could not save the template.') }
    finally { setSaving(false) }
  }

  const handleToggleActive = async () => {
    setActionError(null)
    try {
      await axios.post(`/api/production-templates/${id}/toggle-active`)
      fetchTemplate()
    } catch (e) { fail(e, 'Could not change the template.') }
  }

  const handleDuplicate = async () => {
    setActionError(null)
    try {
      const res = await axios.post(`/api/production-templates/${id}/duplicate`)
      navigate(`/production-templates/${res.data.id}`)
    } catch (e) { fail(e, 'Could not duplicate the template.') }
  }

  // ── Order ──────────────────────────────────────────────────────────────────
  const handleSaveOrder = async () => {
    setSavingOrder(true)
    setActionError(null)
    try {
      await axios.post(`/api/production-templates/${id}/sort`, {
        sections: sections.map((s, si) => ({
          id: s.id, sort_order: si,
          items: (s.items || []).map((item, ii) => ({ id: item.id, sort_order: ii })),
        })),
      })
      setOrderDirty(false)
      flashSaved()
    } catch (e) { fail(e, 'Could not save the order.') }
    finally { setSavingOrder(false) }
  }

  const onSectionDragStart = (e, sectionIdx) => {
    e.stopPropagation()
    dragItem.current = { type: 'section', sectionIdx }
    e.dataTransfer.effectAllowed = 'move'
  }

  const onSectionDrop = (e, targetIdx) => {
    e.preventDefault()
    if (dragItem.current?.type !== 'section') return
    const fromIdx = dragItem.current.sectionIdx
    if (fromIdx === targetIdx) return
    const next = [...sections]
    const [moved] = next.splice(fromIdx, 1)
    next.splice(targetIdx, 0, moved)
    setSections(next)
    setOrderDirty(true)
    dragItem.current = null
  }

  const onItemDragStart = (e, sectionIdx, itemIdx) => {
    dragItem.current = { type: 'item', sectionIdx, itemIdx }
    e.dataTransfer.effectAllowed = 'move'
    e.stopPropagation()
  }

  const moveItem = (fromS, fromI, toS, toI) => {
    const next = sections.map(s => ({ ...s, items: [...(s.items || [])] }))
    const [moved] = next[fromS].items.splice(fromI, 1)
    if (toI === null) next[toS].items.push(moved)
    else {
      let at = toI
      if (fromS === toS && fromI < toI) at--
      next[toS].items.splice(at, 0, moved)
    }
    setSections(next)
    setOrderDirty(true)
  }

  const onItemDrop = (e, toS, toI) => {
    e.preventDefault()
    e.stopPropagation()
    if (dragItem.current?.type !== 'item') return
    const { sectionIdx, itemIdx } = dragItem.current
    if (sectionIdx === toS && itemIdx === toI) return
    moveItem(sectionIdx, itemIdx, toS, toI)
    dragItem.current = null
  }

  const onSectionBodyDrop = (e, toS) => {
    e.preventDefault()
    e.stopPropagation()
    if (dragItem.current?.type !== 'item') return
    const { sectionIdx, itemIdx } = dragItem.current
    moveItem(sectionIdx, itemIdx, toS, null)
    dragItem.current = null
  }

  // ── Sections ───────────────────────────────────────────────────────────────
  const handleAddSection = async () => {
    if (!newSectionName.trim()) return
    setAddingSec(true)
    setActionError(null)
    try {
      await axios.post('/api/production-sections', {
        template_id: parseInt(id), name: newSectionName.trim(), sort_order: sections.length,
      })
      setShowAddSection(false)
      setNewSectionName('')
      fetchTemplate()
    } catch (e) { fail(e, 'Could not add the section.') }
    finally { setAddingSec(false) }
  }

  const handleSaveSection = async (sectionId) => {
    setActionError(null)
    try {
      await axios.put(`/api/production-sections/${sectionId}`, { name: editSectionName })
      setEditingSection(null)
      fetchTemplate()
    } catch (e) { fail(e, 'Could not rename the section.') }
  }

  const handleDeleteSection = async (sectionId) => {
    if (!confirm('Delete this section and all its products?')) return
    setActionError(null)
    try {
      await axios.delete(`/api/production-sections/${sectionId}`)
      fetchTemplate()
    } catch (e) { fail(e, 'Could not delete the section.') }
  }

  // ── Products ───────────────────────────────────────────────────────────────
  const handleAddProduct = async (sectionId, product, insertAfterIdx) => {
    setActionError(null)
    try {
      await axios.post(`/api/production-sections/${sectionId}/items`, {
        product_id: product.id, sort_order: insertAfterIdx + 1,
      })
      fetchTemplate()
    } catch (e) { fail(e, 'Could not add the product.') }
  }

  const handleRemoveProduct = async (itemId) => {
    setActionError(null)
    try {
      await axios.delete(`/api/production-template-items/${itemId}`)
      fetchTemplate()
    } catch (e) { fail(e, 'Could not remove the product.') }
  }

  const handleChangeUnit = async (item, unitId) => {
    if (unitId === item.unit_id) return
    setActionError(null)
    try {
      await axios.put(`/api/production-template-items/${item.id}`, { unit_id: unitId })
      fetchTemplate()
    } catch (e) { fail(e, 'Could not change the unit.') }
  }

  // ── Commissaries ───────────────────────────────────────────────────────────
  const handleToggleLocation = async (locationId, isAssigned) => {
    setActionError(null)
    try {
      if (isAssigned) await axios.delete(`/api/production-templates/${id}/locations/${locationId}`)
      else            await axios.post(`/api/production-templates/${id}/locations`, { location_id: locationId })
      fetchTemplate()
    } catch (e) { fail(e, 'Could not change the commissaries.') }
  }

  const toggleCollapse = (sectionId) => {
    setCollapsedSections(prev => {
      const next = new Set(prev)
      next.has(sectionId) ? next.delete(sectionId) : next.add(sectionId)
      return next
    })
  }

  if (loading)   return <div className="spinner">Loading...</div>
  if (error)     return <div className="page"><div className="alert alert-error">{error}</div></div>
  if (!template) return null

  const assigned = new Set((template.locations || []).map(l => l.location_id))

  return (
    <div className="page">
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/production-templates')}>← Back</button>
          <div>
            <h1 className="page-title">
              {template.name}
              {!template.active && <span className="badge badge-neutral" style={{ marginLeft: '0.5rem' }}>Inactive</span>}
            </h1>
            <p className="page-subtitle">
              {sections.length} sections · {sections.reduce((n, s) => n + (s.items?.length || 0), 0)} products
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {saved && <span className="save-confirm">Saved ✓</span>}
          {orderDirty && (
            <button className="btn btn-primary" onClick={handleSaveOrder} disabled={savingOrder}>
              {savingOrder ? 'Saving...' : 'Save Order'}
            </button>
          )}
          {editing ? (
            <>
              <button className="btn btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSaveTemplate} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-secondary" onClick={() => setShowLocations(!showLocations)}>
                Commissaries ({template.locations?.length || 0})
              </button>
              <button className="btn btn-secondary" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn btn-secondary" onClick={handleDuplicate}>Duplicate</button>
              <button className={`btn ${template.active ? 'btn-secondary' : 'btn-primary'}`}
                onClick={handleToggleActive}>
                {template.active ? 'Deactivate' : 'Activate'}
              </button>
            </>
          )}
        </div>
      </div>

      {actionError && (
        <div className="alert alert-error" style={{ marginBottom: '1rem' }}>{actionError}</div>
      )}

      <div className="detail-grid">
        <div className="detail-main">
          {editing && (
            <div className="card" style={{ marginBottom: '1rem' }}>
              <div className="card-header"><h2 className="card-title">Template Info</h2></div>
              <div className="card-body">
                <div className="form-group">
                  <label className="form-label">Name *</label>
                  <input className="input" value={editForm.name}
                    onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label className="form-label">Notes</label>
                  <textarea className="input" rows={2} value={editForm.notes}
                    onChange={e => setEditForm(f => ({ ...f, notes: e.target.value }))} />
                </div>
              </div>
            </div>
          )}

          {orderDirty && (
            <div className="alert alert-success" style={{ marginBottom: '1rem' }}>
              Order changed — click <strong>Save Order</strong> to save.
            </div>
          )}

          {sections.map((section, sectionIdx) => {
            const isCollapsed = collapsedSections.has(section.id)
            return (
              <div key={section.id} className="card section-card"
                onDragOver={e => { if (dragItem.current?.type === 'item') return; e.preventDefault() }}
                onDrop={e => {
                  if (dragItem.current?.type === 'item') { onSectionBodyDrop(e, sectionIdx); return }
                  onSectionDrop(e, sectionIdx)
                }}
                style={{ marginBottom: '0.75rem' }}>

                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, minWidth: 0 }}>
                    <span className="drag-handle" draggable
                      onDragStart={e => onSectionDragStart(e, sectionIdx)}>⋮⋮</span>
                    <button className="btn btn-ghost btn-sm"
                      style={{ padding: '0.1rem 0.3rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}
                      onClick={() => toggleCollapse(section.id)}>
                      {isCollapsed ? '▶' : '▼'}
                    </button>
                    {editingSection === section.id ? (
                      <div style={{ display: 'flex', gap: '0.5rem', flex: 1 }}>
                        <input className="input" value={editSectionName} autoFocus
                          onChange={e => setEditSectionName(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === 'Enter')  handleSaveSection(section.id)
                            if (e.key === 'Escape') setEditingSection(null)
                          }} />
                        <button className="btn btn-primary btn-sm" onClick={() => handleSaveSection(section.id)}>Save</button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditingSection(null)}>Cancel</button>
                      </div>
                    ) : (
                      <h2 className="card-title">
                        {section.name}
                        {isCollapsed && (
                          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '0.4rem' }}>
                            ({section.items?.length || 0} products)
                          </span>
                        )}
                      </h2>
                    )}
                  </div>
                  {editingSection !== section.id && (
                    <div style={{ display: 'flex', gap: '0.4rem', flexShrink: 0 }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => {
                        setEditingSection(section.id)
                        setEditSectionName(section.name)
                      }}>Rename</button>
                      <button className="btn btn-ghost btn-sm" style={{ color: 'var(--error)' }}
                        onClick={() => handleDeleteSection(section.id)}>Delete</button>
                    </div>
                  )}
                </div>

                {!isCollapsed && (
                  <div>
                    {(!section.items || section.items.length === 0) && (
                      <div className="comm-empty-drop-zone"
                        onDragOver={e => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add('drag-over') }}
                        onDragLeave={e => e.currentTarget.classList.remove('drag-over')}
                        onDrop={e => { e.currentTarget.classList.remove('drag-over'); onSectionBodyDrop(e, sectionIdx) }}>
                        Drop products here or use + to add
                      </div>
                    )}

                    <InlineAddButton sectionId={section.id} insertAfterIdx={-1}
                      addingTo={addingTo} setAddingTo={setAddingTo} onAdd={handleAddProduct} />

                    <div className="section-items">
                      {(section.items || []).map((item, itemIdx) => (
                        <div key={item.id}>
                          <div className="section-item"
                            onDragOver={e => { e.preventDefault(); e.stopPropagation() }}
                            onDrop={e => onItemDrop(e, sectionIdx, itemIdx)}>
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', flex: 1 }}>
                              <span className="drag-handle" style={{ marginTop: '2px' }} draggable
                                onDragStart={e => onItemDragStart(e, sectionIdx, itemIdx)}>⋮⋮</span>
                              <div className="section-item-info">
                                <span className="section-item-name">
                                  {isAdmin
                                    ? <Link to={`/products/${item.product_id}`} style={{ color: 'inherit' }}>{item.product_name}</Link>
                                    : item.product_name}
                                </span>
                                <span className="section-item-meta">{item.category || 'No category'} · base: {item.base_unit}</span>
                                <UnitPicker item={item} onChange={handleChangeUnit} />
                              </div>
                            </div>
                            <button className="btn btn-ghost btn-sm"
                              style={{ color: 'var(--text-muted)', flexShrink: 0 }}
                              title="Remove from template"
                              onClick={() => handleRemoveProduct(item.id)}>✕</button>
                          </div>
                          <InlineAddButton sectionId={section.id} insertAfterIdx={itemIdx}
                            addingTo={addingTo} setAddingTo={setAddingTo} onAdd={handleAddProduct} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )
          })}

          {showAddSection ? (
            <div className="card">
              <div className="card-body">
                <div className="form-group">
                  <label className="form-label">Section Name *</label>
                  <input className="input" placeholder="e.g. Sauces, Proteins, Prep"
                    value={newSectionName} autoFocus
                    onChange={e => setNewSectionName(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter')  handleAddSection()
                      if (e.key === 'Escape') { setShowAddSection(false); setNewSectionName('') }
                    }} />
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                  <button className="btn btn-primary" onClick={handleAddSection}
                    disabled={addingSec || !newSectionName.trim()}>
                    {addingSec ? 'Adding...' : 'Add Section'}
                  </button>
                  <button className="btn btn-ghost"
                    onClick={() => { setShowAddSection(false); setNewSectionName('') }}>Cancel</button>
                </div>
              </div>
            </div>
          ) : (
            <button className="btn btn-secondary add-section-btn" onClick={() => setShowAddSection(true)}>
              + Add Section
            </button>
          )}
        </div>

        {showLocations && (
          <div className="detail-side">
            <div className="card">
              <div className="card-header">
                <h2 className="card-title">Commissaries</h2>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowLocations(false)}>✕</button>
              </div>
              <div className="location-list">
                {commissaries.length === 0 && (
                  <div className="location-item" style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    No commissary locations found (locations.is_commissary).
                  </div>
                )}
                {commissaries.map(loc => {
                  const isAssigned = assigned.has(loc.store_guid)
                  return (
                    <div key={loc.store_guid} className="location-item">
                      <span>{loc.location_name}</span>
                      <button className={`btn btn-sm ${isAssigned ? 'btn-ghost' : 'btn-secondary'}`}
                        style={isAssigned ? { color: 'var(--error)' } : {}}
                        onClick={() => handleToggleLocation(loc.store_guid, isAssigned)}>
                        {isAssigned ? 'Remove' : 'Assign'}
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
