import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useDebounce } from '../hooks/useDebounce'
import './catalog.css'

export default function ProductCatalog() {
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────────────
  const [products,    setProducts]    = useState([])
  const [categories,  setCategories]  = useState([])
  const [units,       setUnits]       = useState([])
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)

  // Filters
  const [search,       setSearch]       = useState('')
  const [categoryId,   setCategoryId]   = useState('')
  const [productType,  setProductType]  = useState('')
  const [showInactive, setShowInactive] = useState(false)

  // Debounce search — only fires DB query 300ms after user stops typing
  const debouncedSearch = useDebounce(search, 300)

  // Pagination
  const [page,  setPage]  = useState(1)
  const [total, setTotal] = useState(0)
  const PER_PAGE = 50

  // Add product modal
  const [showAdd,     setShowAdd]     = useState(false)
  const [adding,      setAdding]      = useState(false)
  const [newProduct,  setNewProduct]  = useState({
    name: '', product_type: 'ingredient', base_unit_id: '',
    category_id: '', internal_name: '', notes: ''
  })

  // ── Data fetching ──────────────────────────────────────────────────────────
  const fetchCategories = useCallback(async () => {
    try {
      const [catRes, unitRes] = await Promise.all([
        axios.get('/api/categories'),
        axios.get('/api/units'),
      ])
      setCategories(catRes.data)
      // Default base_unit_id to 'each' or first unit
      const each = unitRes.data.find(u => u.name === 'each')
      setUnits(unitRes.data)
      setNewProduct(p => ({ ...p, base_unit_id: each ? String(each.id) : String(unitRes.data[0]?.id || '') }))
    } catch (e) {
      console.error('Failed to load categories', e)
    }
  }, [])

  const fetchProducts = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { page, per_page: PER_PAGE }
      if (debouncedSearch) params.search       = debouncedSearch
      if (categoryId)      params.category_id  = categoryId
      if (productType)     params.product_type = productType
      if (showInactive)    params.active        = 'false'

      const res = await axios.get('/api/products', { params })
      setProducts(res.data.products)
      setTotal(res.data.total)
    } catch (e) {
      setError('Failed to load products.')
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [debouncedSearch, categoryId, productType, showInactive, page])

  // Fetch categories once on mount
  useEffect(() => { fetchCategories() }, [fetchCategories])

  // Reset to page 1 when any filter changes
  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, categoryId, productType, showInactive])

  // Fetch products when filters or page changes
  useEffect(() => { fetchProducts() }, [fetchProducts])

  // ── Add product ────────────────────────────────────────────────────────────
  const handleAdd = async () => {
    if (!newProduct.name.trim()) return
    setAdding(true)
    try {
      const res = await axios.post('/api/products', newProduct)
      setShowAdd(false)
      setNewProduct({
        name: '', product_type: 'ingredient', base_unit_id: '',
        category_id: '', internal_name: '', notes: ''
      })
      navigate(`/products/${res.data.id}`)
    } catch (e) {
      console.error('Failed to create product', e)
    } finally {
      setAdding(false)
    }
  }

  // ── Derived ────────────────────────────────────────────────────────────────
  const pages      = Math.ceil(total / PER_PAGE)
  const typeLabels = {
    ingredient: 'Ingredient',
    commissary: 'Commissary',
    menu_item:  'Menu Item',
  }
  const typeBadge = {
    ingredient: 'badge-info',
    commissary: 'badge-warning',
    menu_item:  'badge-success',
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="page">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Products</h1>
          <p className="page-subtitle">{total} products</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
          + Add Product
        </button>
      </div>

      {/* Filters */}
      <div className="filter-bar">
        <input
          className="input filter-search"
          placeholder="Search products..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />

        <select
          className="input filter-select"
          value={categoryId}
          onChange={e => setCategoryId(e.target.value)}
        >
          <option value="">All Categories</option>
          {categories.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <select
          className="input filter-select"
          value={productType}
          onChange={e => setProductType(e.target.value)}
        >
          <option value="">All Types</option>
          <option value="ingredient">Ingredient</option>
          <option value="commissary">Commissary</option>
          <option value="menu_item">Menu Item</option>
        </select>

        <label className="filter-toggle">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={e => setShowInactive(e.target.checked)}
          />
          Show inactive
        </label>
      </div>

      {/* Error */}
      {error && <div className="alert alert-error">{error}</div>}

      {/* Table */}
      {loading ? (
        <div className="spinner">Loading products...</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Category</th>
                  <th>Type</th>
                  <th>Base Unit</th>
                  <th>Vendor Codes</th>
                  <th>Recipe</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {products.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                      No products found.
                    </td>
                  </tr>
                ) : products.map(p => (
                  <tr
                    key={p.id}
                    className="row-link"
                    onClick={() => navigate(`/products/${p.id}`)}
                  >
                    <td>
                      <span className="product-name">{p.name}</span>
                      {p.internal_name && p.internal_name !== p.name && (
                        <span className="product-internal">{p.internal_name}</span>
                      )}
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>
                      {p.category_name || '—'}
                    </td>
                    <td>
                      <span className={`badge ${typeBadge[p.product_type]}`}>
                        {typeLabels[p.product_type]}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                      {p.base_unit}
                    </td>
                    <td>
                      {p.vendor_ref_count > 0
                        ? <span className="badge badge-success">{p.vendor_ref_count} active</span>
                        : <span className="badge badge-neutral">None</span>
                      }
                    </td>
                    <td>
                      {p.has_recipe
                        ? <span className="badge badge-success">Yes</span>
                        : <span className="badge badge-neutral">No</span>
                      }
                    </td>
                    <td>
                      <span className={`badge ${p.active ? 'badge-success' : 'badge-error'}`}>
                        {p.active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {pages > 1 && (
            <div className="pagination">
              <button
                className="btn btn-ghost"
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
              >
                ← Prev
              </button>
              <span className="pagination-info">
                Page {page} of {pages}
              </span>
              <button
                className="btn btn-ghost"
                disabled={page === pages}
                onClick={() => setPage(p => p + 1)}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}

      {/* Add Product Modal */}
      {showAdd && (
        <div className="modal-overlay" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Add Product</h2>
              <button className="btn btn-ghost" onClick={() => setShowAdd(false)}>✕</button>
            </div>

            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">Name *</label>
                <input
                  className="input"
                  placeholder="e.g. Chicken Breast"
                  value={newProduct.name}
                  onChange={e => setNewProduct(p => ({ ...p, name: e.target.value }))}
                  autoFocus
                />
              </div>

              <div className="form-group">
                <label className="form-label">Internal Name</label>
                <input
                  className="input"
                  placeholder="Optional alternate name"
                  value={newProduct.internal_name}
                  onChange={e => setNewProduct(p => ({ ...p, internal_name: e.target.value }))}
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Type *</label>
                  <select
                    className="input"
                    value={newProduct.product_type}
                    onChange={e => setNewProduct(p => ({ ...p, product_type: e.target.value }))}
                  >
                    <option value="ingredient">Ingredient</option>
                    <option value="commissary">Commissary</option>
                    <option value="menu_item">Menu Item</option>
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Base Unit *</label>
                  <select
                    className="input"
                    value={newProduct.base_unit_id}
                    onChange={e => setNewProduct(p => ({ ...p, base_unit_id: e.target.value }))}
                  >
                    <option value="">Select unit...</option>
                    {units.map(u => (
                      <option key={u.id} value={String(u.id)}>{u.display} ({u.name})</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Category</label>
                <select
                  className="input"
                  value={newProduct.category_id}
                  onChange={e => setNewProduct(p => ({ ...p, category_id: e.target.value }))}
                >
                  <option value="">Select category...</option>
                  {categories.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Notes</label>
                <textarea
                  className="input"
                  rows={2}
                  placeholder="Optional notes"
                  value={newProduct.notes}
                  onChange={e => setNewProduct(p => ({ ...p, notes: e.target.value }))}
                />
              </div>
            </div>

            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={handleAdd}
                disabled={adding || !newProduct.name.trim()}
              >
                {adding ? 'Creating...' : 'Create Product'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
