import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useDebounce } from '../hooks/useDebounce'
import './catalog.css'
import './sheet-templates.css'
import './comm-template.css'

export default function CommOrderTemplateDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()

  const [template,        setTemplate]        = useState(null)
  const [sections,        setSections]        = useState([])  // local sortable copy
  const [loading,         setLoading]         = useState(true)
  const [error,           setError]           = useState(null)
  const [saving,          setSaving]          = useState(false)
  const [saved,           setSaved]           = useState(false)
  const [orderDirty,      setOrderDirty]      = useState(false)
  const [savingOrder,     setSavingOrder]     = useState(false)
  const [editing,         setEditing]         = useState(false)
  const [editForm,        setEditForm]        = useState({})

  // Section management
  const [showAddSection,  setShowAddSection]  = useState(false)
  const [newSectionName,  setNewSectionName]  = useState('')
  const [addingSec,       setAddingSec]       = useState(false)
  const [editingSection,  setEditingSection]  = useState(null)
  const [editSectionName, setEditSectionName] = useState('')

  // Product search
  const [addingToSection,  setAddingToSection]  = useState(null)
  const [productSearch,    setProductSearch]    = useState('')
  const [productResults,   setProductResults]   = useState([])
  const debouncedSearch = useDebounce(productSearch, 300)

  // Drag state
  const dragItem      = useRef(null)  // { type: 'section'|'item', sectionIdx, itemIdx }
  const dragOverItem  = useRef(null)

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchTemplate = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get(`/api/comm-order-templates/${id}`)
      setTemplate(res.data)
      setSections(res.data.sections || [])
      setEditForm({ name: res.data.name, notes: res.data.notes || '' })
      setOrderDirty(false)
    } catch (e) {
      setError('Template not found.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchTemplate() }, [fetchTemplate])

  useEffect(() => {
    if (!debouncedSearch || debouncedSearch.length < 2) {
      setProductResults([])
      return
    }
    axios.get('/api/products', { params: { search: debouncedSearch, per_page: 8 } })
      .then(res => setProductResults(res.data.products))
      .catch(() => setProductResults([]))
  }, [debouncedSearch])

  // ── Template edit ──────────────────────────────────────────────────────────
  const handleSaveTemplate = async () => {
    setSaving(true)
    try {
      await axios.put(`/api/comm-order-templates/${id}`, editForm)
      setEditing(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      fetchTemplate()
    } catch (e) {
      console.error('Failed to save', e)
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async () => {
    try {
      await axios.post(`/api/comm-order-templates/${id}/toggle-active`)
      fetchTemplate()
    } catch (e) {
      console.error('Failed to toggle', e)
    }
  }

  // ── Save order ─────────────────────────────────────────────────────────────
  const handleSaveOrder = async () => {
    setSavingOrder(true)
    try {
      await axios.post(`/api/comm-order-templates/${id}/sort`, {
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
    dragItem.current = { type: 'section', sectionIdx }
    e.dataTransfer.effectAllowed = 'move'
  }

  const onSectionDragOver = (e, sectionIdx) => {
    e.preventDefault()
    dragOverItem.current = { type: 'section', sectionIdx }
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

  // ── Drag and drop — items within and across sections ──────────────────────
  const onItemDragStart = (e, sectionIdx, itemIdx) => {
    dragItem.current = { type: 'item', sectionIdx, itemIdx }
    e.dataTransfer.effectAllowed = 'move'
    e.stopPropagation()
  }

  const onItemDragOver = (e, sectionIdx, itemIdx) => {
    e.preventDefault()
    e.stopPropagation()
    dragOverItem.current = { type: 'item', sectionIdx, itemIdx }
  }

  const onItemDrop = (e, targetSectionIdx, targetItemIdx) => {
    e.preventDefault()
    e.stopPropagation()
    if (dragItem.current?.type !== 'item') return

    const { sectionIdx: fromSectionIdx, itemIdx: fromItemIdx } = dragItem.current

    // Same section same position — no op
    if (fromSectionIdx === targetSectionIdx && fromItemIdx === targetItemIdx) return

    const newSections = sections.map(s => ({ ...s, items: [...(s.items || [])] }))

    // Remove from source
    const [moved] = newSections[fromSectionIdx].items.splice(fromItemIdx, 1)

    // Insert at target
    // If same section and target is after source, account for the removed item
    let insertIdx = targetItemIdx
    if (fromSectionIdx === targetSectionIdx && fromItemIdx < targetItemIdx) {
      insertIdx = targetItemIdx - 1
    }
    newSections[targetSectionIdx].items.splice(insertIdx, 0, moved)

    setSections(newSections)
    setOrderDirty(true)
    dragItem.current = null
  }

  // Drop onto section body (for empty sections or end of list)
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
      await axios.post('/api/comm-order-sections', {
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
      await axios.put(`/api/comm-order-sections/${sectionId}`, { name: editSectionName })
      setEditingSection(null)
      fetchTemplate()
    } catch (e) {
      console.error('Failed to save section', e)
    }
  }

  const handleDeleteSection = async (sectionId) => {
    if (!confirm('Delete this section and all its items?')) return
    try {
      await axios.delete(`/api/comm-order-sections/${sectionId}`)
      fetchTemplate()
    } catch (e) {
      console.error('Failed to delete section', e)
    }
  }

  // ── Products ───────────────────────────────────────────────────────────────
  const handleAddProduct = async (sectionId, product) => {
    try {
      await axios.post(`/api/comm-order-sections/${sectionId}/items`, {
        product_id: product.id,
      })
      setAddingToSection(null)
      setProductSearch('')
      setProductResults([])
      fetchTemplate()
    } catch (e) {
      console.error('Failed to add product', e)
    }
  }

  const handleRemoveProduct = async (itemId) => {
    try {
      await axios.delete(`/api/comm-order-template-items/${itemId}`)
      fetchTemplate()
    } catch (e) {
      console.error('Failed to remove product', e)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading)   return <div className="spinner">Loading...</div>
  if (error)     return <div className="page"><div className="alert alert-error">{error}</div></div>
  if (!template) return null

  return (
    <div className="page">
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button className="btn btn-ghost" onClick={() => navigate('/comm-order-templates')}>← Back</button>
          <div>
            <h1 className="page-title">{template.location_name}</h1>
            <p className="page-subtitle">
              {template.name} · {sections.length} sections ·{' '}
              {sections.reduce((sum, s) => sum + (s.items?.length || 0), 0)} products
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
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
              <button className="btn btn-secondary" onClick={() => setEditing(true)}>Edit</button>
              <button
                className={`btn ${template.active ? 'btn-secondary' : 'btn-primary'}`}
                onClick={handleToggleActive}>
                {template.active ? 'Deactivate' : 'Activate'}
              </button>
            </>
          )}
        </div>
      </div>

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

        {sections.map((section, sectionIdx) => (
          <div
            key={section.id}
            className="card section-card comm-section-draggable"
            draggable
            onDragStart={e => {
              // Only start section drag if not dragging an item
              if (dragItem.current?.type === 'item') return
              onSectionDragStart(e, sectionIdx)
            }}
            onDragOver={e => {
              if (dragItem.current?.type === 'item') return
              onSectionDragOver(e, sectionIdx)
            }}
            onDrop={e => {
              if (dragItem.current?.type === 'item') {
                onSectionBodyDrop(e, sectionIdx)
                return
              }
              onSectionDrop(e, sectionIdx)
            }}
            style={{ marginBottom: '0.75rem', cursor: 'grab' }}
          >
            <div className="card-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span className="drag-handle">⋮⋮</span>
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
                  <h2 className="card-title">{section.name}</h2>
                )}
              </div>
              {editingSection !== section.id && (
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                  <button className="btn btn-ghost btn-sm" onClick={() => {
                    setEditingSection(section.id)
                    setEditSectionName(section.name)
                  }}>Rename</button>
                  <button className="btn btn-ghost btn-sm"
                    onClick={() => setAddingToSection(
                      addingToSection === section.id ? null : section.id
                    )}>
                    + Product
                  </button>
                  <button className="btn btn-ghost btn-sm"
                    style={{ color: 'var(--error)' }}
                    onClick={() => handleDeleteSection(section.id)}>
                    Delete
                  </button>
                </div>
              )}
            </div>

            {addingToSection === section.id && (
              <div className="section-product-search">
                <input className="input" placeholder="Search products..."
                  value={productSearch} autoFocus
                  onChange={e => setProductSearch(e.target.value)} />
                {productResults.length > 0 && (
                  <div className="product-search-results">
                    {productResults.map(p => (
                      <button key={p.id} className="product-search-result"
                        onClick={() => handleAddProduct(section.id, p)}>
                        <span>{p.name}</span>
                        <span className="result-meta">{p.category_name} · {p.base_unit}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {(!section.items || section.items.length === 0) ? (
              <div
                className="comm-empty-drop-zone"
                onDragOver={e => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add('drag-over') }}
                onDragLeave={e => e.currentTarget.classList.remove('drag-over')}
                onDrop={e => { e.currentTarget.classList.remove('drag-over'); onSectionBodyDrop(e, sectionIdx) }}
              >
                Drop products here or click + Product to add
              </div>
            ) : (
              <div className="section-items">
                {section.items.map((item, itemIdx) => (
                  <div
                    key={item.id}
                    className="section-item comm-item-draggable"
                    draggable
                    onDragStart={e => onItemDragStart(e, sectionIdx, itemIdx)}
                    onDragOver={e => onItemDragOver(e, sectionIdx, itemIdx)}
                    onDrop={e => onItemDrop(e, sectionIdx, itemIdx)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1 }}>
                      <span className="drag-handle">⋮⋮</span>
                      <div className="section-item-info">
                        <span className="section-item-name">{item.product_name}</span>
                        <span className="section-item-meta">{item.category} · {item.base_unit}</span>
                      </div>
                    </div>
                    <button className="btn btn-ghost btn-sm"
                      style={{ color: 'var(--text-muted)' }}
                      onClick={() => handleRemoveProduct(item.id)}>✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {showAddSection ? (
          <div className="card">
            <div className="card-body">
              <div className="form-group">
                <label className="form-label">Section Name *</label>
                <input className="input" placeholder="e.g. Proteins, Sauces, Sides"
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
    </div>
  )
}
