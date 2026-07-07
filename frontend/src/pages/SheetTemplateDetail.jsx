import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useDebounce } from '../hooks/useDebounce'
import './catalog.css'
import './sheet-templates.css'
import './comm-template.css'

// ── Inline add button + search ─────────────────────────────────────────────
function InlineAddButton({ sectionId, insertAfterIdx, addingTo, setAddingTo, onAdd }) {
  const [search,  setSearch]  = useState('')
  const [results, setResults] = useState([])
  const debouncedSearch = useDebounce(search, 300)
  const isOpen = addingTo?.sectionId === sectionId && addingTo?.insertAfterIdx === insertAfterIdx

  useEffect(() => {
    if (!debouncedSearch || debouncedSearch.length < 2) { setResults([]); return }
    axios.get('/api/products', { params: { search: debouncedSearch, per_page: 8 } })
      .then(res => setResults(res.data.products || []))
      .catch(() => setResults([]))
  }, [debouncedSearch])

  const open = () => {
    setAddingTo({ sectionId, insertAfterIdx })
    setSearch('')
    setResults([])
  }

  const close = () => {
    setAddingTo(null)
    setSearch('')
    setResults([])
  }

  if (!isOpen) {
    return (
      <div className="inline-add-row">
        <button className="inline-add-btn" onClick={open} title="Add product here">+</button>
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

// ── Main component ─────────────────────────────────────────────────────────
export default function SheetTemplateDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()

  const [template,        setTemplate]        = useState(null)
  const [sections,        setSections]        = useState([])
  const [loading,         setLoading]         = useState(true)
  const [error,           setError]           = useState(null)
  const [saving,          setSaving]          = useState(false)
  const [saved,           setSaved]           = useState(false)
  const [editing,         setEditing]         = useState(false)
  const [editForm,        setEditForm]        = useState({})
  const [orderDirty,      setOrderDirty]      = useState(false)
  const [savingOrder,     setSavingOrder]     = useState(false)
  const [duplicating,     setDuplicating]     = useState(false)
  const [collapsedSections, setCollapsedSections] = useState(new Set())

  // Section management
  const [showAddSection,  setShowAddSection]  = useState(false)
  const [newSectionName,  setNewSectionName]  = useState('')
  const [addingSec,       setAddingSec]       = useState(false)
  const [editingSection,  setEditingSection]  = useState(null)
  const [editSectionName, setEditSectionName] = useState('')

  // Inline product add
  const [addingTo,        setAddingTo]        = useState(null) // { sectionId, insertAfterIdx }

  // Count unit management
  const [addingUnitToItem, setAddingUnitToItem] = useState(null)
  const [selectedUnitId,   setSelectedUnitId]   = useState('')
  const [itemUnits,        setItemUnits]        = useState([])
  const [allUnits,         setAllUnits]         = useState([])

  // Locations panel
  const [showLocations,   setShowLocations]   = useState(false)
  const [locations,       setLocations]       = useState([])

  // Drag state
  const dragItem     = useRef(null)

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchTemplate = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get(`/api/sheet-templates/${id}`)
      setTemplate(res.data)
      setSections(res.data.sections || [])
      setEditForm({
        name:          res.data.name,
        notes:         res.data.notes || '',
        is_commissary: res.data.is_commissary || false,
      })
      setOrderDirty(false)
    } catch (e) {
      setError('Template not found.')
    } finally {
      setLoading(false)
    }
  }, [id])

  const fetchLocations = useCallback(async () => {
    try {
      const res = await axios.get('/api/locations')
      setLocations(res.data)
    } catch (e) { console.error('Failed to load locations', e) }
  }, [])

  useEffect(() => {
    fetchTemplate()
    fetchLocations()
    axios.get('/api/units').then(res => setAllUnits(res.data)).catch(() => {})
  }, [fetchTemplate, fetchLocations])

  // ── Template edit ──────────────────────────────────────────────────────────
  const handleSaveTemplate = async () => {
    setSaving(true)
    try {
      await axios.put(`/api/sheet-templates/${id}`, editForm)
      setEditing(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      fetchTemplate()
    } catch (e) {
      const msg = e.response?.data?.error || 'Failed to save template'
      alert(msg)
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async () => {
    try {
      await axios.post(`/api/sheet-templates/${id}/toggle-active`)
      fetchTemplate()
    } catch (e) { console.error('Failed to toggle', e) }
  }

  const handleDuplicate = async () => {
    if (!confirm('Duplicate this template? A copy will be created with all sections, items and count units.')) return
    setDuplicating(true)
    try {
      const res = await axios.post(`/api/sheet-templates/${id}/duplicate`)
      navigate(`/sheet-templates/${res.data.id}`)
    } catch (e) {
      const msg = e.response?.data?.error || 'Failed to duplicate template'
      alert(msg)
    } finally {
      setDuplicating(false)
    }
  }

  // ── Save order ─────────────────────────────────────────────────────────────
  const handleSaveOrder = async () => {
    setSavingOrder(true)
    try {
      await axios.post(`/api/sheet-templates/${id}/sort`, {
        sections: sections.map((s, si) => ({
          id:         s.id,
          sort_order: si,
          items:      (s.items || []).map((item, ii) => ({
            id:         item.id,
            sort_order: ii,
          })),
        })),
      })
      setOrderDirty(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      console.error('Failed to save order', e)
    } finally {
      setSavingOrder(false)
    }
  }

  // ── Drag and drop — sections ───────────────────────────────────────────────
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
    const newSections = [...sections]
    const [moved] = newSections.splice(fromIdx, 1)
    newSections.splice(targetIdx, 0, moved)
    setSections(newSections)
    setOrderDirty(true)
    dragItem.current = null
  }

  // ── Drag and drop — items ──────────────────────────────────────────────────
  const onItemDragStart = (e, sectionIdx, itemIdx) => {
    dragItem.current = { type: 'item', sectionIdx, itemIdx }
    e.dataTransfer.effectAllowed = 'move'
    e.stopPropagation()
  }

  const onItemDrop = (e, targetSectionIdx, targetItemIdx) => {
    e.preventDefault()
    e.stopPropagation()
    if (dragItem.current?.type !== 'item') return
    const { sectionIdx: fromSectionIdx, itemIdx: fromItemIdx } = dragItem.current
    if (fromSectionIdx === targetSectionIdx && fromItemIdx === targetItemIdx) return
    const newSections = sections.map(s => ({ ...s, items: [...(s.items || [])] }))
    const [moved] = newSections[fromSectionIdx].items.splice(fromItemIdx, 1)
    let insertIdx = targetItemIdx
    if (fromSectionIdx === targetSectionIdx && fromItemIdx < targetItemIdx) insertIdx--
    newSections[targetSectionIdx].items.splice(insertIdx, 0, moved)
    setSections(newSections)
    setOrderDirty(true)
    dragItem.current = null
  }

  const onSectionBodyDrop = (e, targetSectionIdx) => {
    e.preventDefault()
    e.stopPropagation()
    if (dragItem.current?.type !== 'item') return
    const { sectionIdx: fromSectionIdx, itemIdx: fromItemIdx } = dragItem.current
    const newSections = sections.map(s => ({ ...s, items: [...(s.items || [])] }))
    const [moved] = newSections[fromSectionIdx].items.splice(fromItemIdx, 1)
    newSections[targetSectionIdx].items.push(moved)
    setSections(newSections)
    setOrderDirty(true)
    dragItem.current = null
  }

  // ── Sections CRUD ──────────────────────────────────────────────────────────
  const handleAddSection = async () => {
    if (!newSectionName.trim()) return
    setAddingSec(true)
    try {
      await axios.post('/api/sheet-sections', {
        template_id: parseInt(id),
        name:        newSectionName.trim(),
        sort_order:  sections.length,
      })
      setShowAddSection(false)
      setNewSectionName('')
      fetchTemplate()
    } catch (e) {
      console.error('Failed to add section', e)
    } finally {
      setAddingSec(false)
    }
  }

  const handleSaveSection = async (sectionId) => {
    try {
      await axios.put(`/api/sheet-sections/${sectionId}`, { name: editSectionName })
      setEditingSection(null)
      fetchTemplate()
    } catch (e) { console.error('Failed to save section', e) }
  }

  const handleDeleteSection = async (sectionId) => {
    if (!confirm('Delete this section and all its items?')) return
    try {
      await axios.delete(`/api/sheet-sections/${sectionId}`)
      fetchTemplate()
    } catch (e) { console.error('Failed to delete section', e) }
  }

  // ── Section items ──────────────────────────────────────────────────────────
  const handleAddProduct = async (sectionId, product, insertAfterIdx) => {
    try {
      await axios.post(`/api/sheet-sections/${sectionId}/items`, {
        product_id: product.id,
        sort_order: insertAfterIdx + 1,
      })
      fetchTemplate()
    } catch (e) { console.error('Failed to add product', e) }
  }

  const handleRemoveProduct = async (itemId) => {
    try {
      await axios.delete(`/api/sheet-section-items/${itemId}`)
      fetchTemplate()
    } catch (e) { console.error('Failed to remove product', e) }
  }

  // ── Count units ────────────────────────────────────────────────────────────
  const openAddUnit = async (item) => {
    setAddingUnitToItem(item.id)
    setSelectedUnitId('')
    try {
      const res = await axios.get(`/api/products/${item.product_id}`)
      const convUnits = res.data.unit_conversions?.map(u => ({ id: u.from_unit_id, name: u.from_unit })) || []
      const baseUnit  = { id: res.data.base_unit_id, name: res.data.base_unit }
      const seen = new Set()
      const units = [baseUnit, ...convUnits].filter(u => {
        if (seen.has(u.id)) return false
        seen.add(u.id)
        return true
      })
      const existingIds = new Set((item.count_units || []).map(u => u.unit_id))
      setItemUnits(units.filter(u => !existingIds.has(u.id)))
    } catch (e) { setItemUnits(allUnits) }
  }

  const handleAddCountUnit = async (itemId) => {
    if (!selectedUnitId) return
    try {
      await axios.post(`/api/sheet-section-items/${itemId}/units`, { unit_id: parseInt(selectedUnitId) })
      setAddingUnitToItem(null)
      setSelectedUnitId('')
      fetchTemplate()
    } catch (e) { console.error('Failed to add count unit', e) }
  }

  const handleRemoveCountUnit = async (unitRowId) => {
    try {
      await axios.delete(`/api/sheet-section-item-units/${unitRowId}`)
      fetchTemplate()
    } catch (e) { console.error('Failed to remove count unit', e) }
  }

  // ── Location assignment ────────────────────────────────────────────────────
  const handleToggleLocation = async (locationId, isAssigned) => {
    try {
      if (isAssigned) {
        await axios.delete(`/api/sheet-templates/${id}/locations/${locationId}`)
      } else {
        await axios.post(`/api/sheet-templates/${id}/locations`, { location_id: locationId })
      }
      fetchTemplate()
    } catch (e) { console.error('Failed to toggle location', e) }
  }

  const toggleCollapse = (sectionId) => {
    setCollapsedSections(prev => {
      const next = new Set(prev)
      next.has(sectionId) ? next.delete(sectionId) : next.add(sectionId)
      return next
    })
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading)  return <div className="spinner">Loading...</div>
  if (error)    return <div className="page"><div className="alert alert-error">{error}</div></div>
  if (!template) return null

  const assignedLocationIds = new Set((template.locations || []).map(l => l.location_id))

  return (
    <div className="page">
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/sheet-templates')}>← Back</button>
          <div>
            <h1 className="page-title">{template.name}</h1>
            <p className="page-subtitle">
              {sections.length} sections ·{' '}
              {sections.reduce((sum, s) => sum + (s.items?.length || 0), 0)} products
              {template.is_commissary && (
                <span className="badge badge-warning" style={{ marginLeft: '0.5rem' }}>Commissary</span>
              )}
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
                Locations ({template.locations?.length || 0})
              </button>
              <button className="btn btn-secondary" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn btn-secondary"
                onClick={handleDuplicate} disabled={duplicating}>
                {duplicating ? 'Duplicating...' : '⧉ Duplicate'}
              </button>
              <button
                className={`btn ${template.active ? 'btn-secondary' : 'btn-primary'}`}
                onClick={handleToggleActive}>
                {template.active ? 'Deactivate' : 'Activate'}
              </button>
            </>
          )}
        </div>
      </div>

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
                <div className="form-group">
                  <label className="filter-toggle">
                    <input type="checkbox" checked={editForm.is_commissary}
                      onChange={e => setEditForm(f => ({ ...f, is_commissary: e.target.checked }))} />
                    Commissary Sheet
                  </label>
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
              <div key={section.id}
                className="card section-card"
                onDragOver={e => {
                  if (dragItem.current?.type === 'item') return
                  e.preventDefault()
                }}
                onDrop={e => {
                  if (dragItem.current?.type === 'item') { onSectionBodyDrop(e, sectionIdx); return }
                  onSectionDrop(e, sectionIdx)
                }}
                style={{ marginBottom: '0.75rem' }}>

                {/* Section header */}
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, minWidth: 0 }}>
                    <span className="drag-handle"
                      draggable
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
                        <button className="btn btn-primary btn-sm"
                          onClick={() => handleSaveSection(section.id)}>Save</button>
                        <button className="btn btn-ghost btn-sm"
                          onClick={() => setEditingSection(null)}>Cancel</button>
                      </div>
                    ) : (
                      <h2 className="card-title">
                        {section.name}
                        {isCollapsed && (
                          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 400, marginLeft: '0.4rem' }}>
                            ({section.items?.length || 0} items)
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
                      <button className="btn btn-ghost btn-sm"
                        style={{ color: 'var(--error)' }}
                        onClick={() => handleDeleteSection(section.id)}>Delete</button>
                    </div>
                  )}
                </div>

                {/* Section body */}
                {!isCollapsed && (
                  <div>
                    {(!section.items || section.items.length === 0) ? (
                      <div
                        className="comm-empty-drop-zone"
                        onDragOver={e => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add('drag-over') }}
                        onDragLeave={e => e.currentTarget.classList.remove('drag-over')}
                        onDrop={e => { e.currentTarget.classList.remove('drag-over'); onSectionBodyDrop(e, sectionIdx) }}>
                        Drop products here or use + to add
                      </div>
                    ) : null}

                    {/* + at top */}
                    <InlineAddButton
                      sectionId={section.id} insertAfterIdx={-1}
                      addingTo={addingTo} setAddingTo={setAddingTo}
                      onAdd={handleAddProduct} />

                    <div className="section-items">
                      {(section.items || []).map((item, itemIdx) => (
                        <div key={item.id}>
                          <div
                            className="section-item"
                            onDragOver={e => { e.preventDefault(); e.stopPropagation() }}
                            onDrop={e => onItemDrop(e, sectionIdx, itemIdx)}>
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', flex: 1 }}>
                              <span className="drag-handle"
                                style={{ marginTop: '2px' }}
                                draggable
                                onDragStart={e => onItemDragStart(e, sectionIdx, itemIdx)}>⋮⋮</span>
                              <div className="section-item-info">
                                <span className="section-item-name">
                                  <a
                                    href={`/products/${item.product_id}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    style={{ color: 'inherit', textDecoration: 'none' }}
                                    onMouseEnter={e => e.currentTarget.style.textDecoration = 'underline'}
                                    onMouseLeave={e => e.currentTarget.style.textDecoration = 'none'}
                                    onClick={e => e.stopPropagation()}>
                                    {item.product_name} ↗
                                  </a>
                                </span>
                                <span className="section-item-meta">{item.category} · base: {item.base_unit}</span>
                                <div className="count-units">
                                  {(item.count_units || []).length === 0 && addingUnitToItem !== item.id && (
                                    <span className="count-unit-default">defaults to {item.base_unit}</span>
                                  )}
                                  {(item.count_units || []).map(cu => (
                                    <span key={cu.id} className="count-unit-tag">
                                      {cu.unit_name}
                                      <button className="count-unit-remove"
                                        onClick={() => handleRemoveCountUnit(cu.id)}>✕</button>
                                    </span>
                                  ))}
                                  {addingUnitToItem === item.id ? (
                                    <span style={{ display: 'flex', gap: '0.3rem', alignItems: 'center' }}>
                                      <select className="input"
                                        style={{ fontSize: '0.7rem', padding: '0.2rem 0.4rem', width: 'auto' }}
                                        value={selectedUnitId}
                                        onChange={e => setSelectedUnitId(e.target.value)}
                                        autoFocus>
                                        <option value="">unit...</option>
                                        {itemUnits.map(u => (
                                          <option key={u.id} value={u.id}>{u.name}</option>
                                        ))}
                                      </select>
                                      <button className="btn btn-primary btn-sm"
                                        onClick={() => handleAddCountUnit(item.id)}
                                        disabled={!selectedUnitId}>Add</button>
                                      <button className="btn btn-ghost btn-sm"
                                        onClick={() => setAddingUnitToItem(null)}>✕</button>
                                    </span>
                                  ) : (
                                    <button className="count-unit-add"
                                      onClick={() => openAddUnit(item)}>+ unit</button>
                                  )}
                                </div>
                              </div>
                            </div>
                            <button className="btn btn-ghost btn-sm"
                              style={{ color: 'var(--text-muted)', flexShrink: 0 }}
                              onClick={() => handleRemoveProduct(item.id)}>✕</button>
                          </div>

                          {/* + after each item */}
                          <InlineAddButton
                            sectionId={section.id} insertAfterIdx={itemIdx}
                            addingTo={addingTo} setAddingTo={setAddingTo}
                            onAdd={handleAddProduct} />
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
                  <input className="input" placeholder="e.g. Walk-in Cooler, Dry Storage"
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
                    onClick={() => { setShowAddSection(false); setNewSectionName('') }}>
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <button className="btn btn-secondary add-section-btn"
              onClick={() => setShowAddSection(true)}>
              + Add Section
            </button>
          )}
        </div>

        {/* Locations panel */}
        {showLocations && (
          <div className="detail-side">
            <div className="card">
              <div className="card-header">
                <h2 className="card-title">Locations</h2>
                <button className="btn btn-ghost btn-sm" onClick={() => setShowLocations(false)}>✕</button>
              </div>
              <div className="location-list">
                {locations.map(loc => {
                  const isAssigned = assignedLocationIds.has(loc.store_guid)
                  return (
                    <div key={loc.store_guid} className="location-row">
                      <span className="location-name">{loc.location_name}</span>
                      <button
                        className={`btn btn-sm ${isAssigned ? 'btn-ghost' : 'btn-secondary'}`}
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
