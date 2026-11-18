// =============================================================================
// features/usage/pages/ParCheckPage.jsx      URL: /usage/par-check   (Usage > Par Check)
// =============================================================================
// The usage windows read from the other side: is each order day's par about
// right? For every window: the par its order was made with, what the store
// stocked up to (start count + regular orders received), what it used
// (regular) and what was LEFT at the next count. A par that always leaves a
// lot behind is more than that order day needs; one that runs out is tight.
// Per order day: medians and the lowest left over of the last 4 usual
// windows (windows with extra orders count; they are marked).
// Filters / loading shared with the Usage Report: ../components/UsageFilters.jsx
// Data: GET /api/usage/par-check (backend/features/usage/usage_routes.py)
// =============================================================================
import { useState, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useUsageReport, UsageFilterBar, UsageStatus, groupByCategory,
  fmtCovers, SHORT_DAY, SOURCES,
} from '../components/UsageFilters.jsx'
import '../../../core/styles/shared-ui.css'
import './UsagePage.css'
import './ParCheckPage.css'

const pct = (a, b) => (a === null || a === undefined || !b) ? null : Math.round((a / b) * 100)

export default function ParCheckPage() {
  const navigate = useNavigate()
  const f = useUsageReport('/api/usage/par-check')
  const { data, qty, unitOf } = f
  const [open, setOpen] = useState(new Set())

  const toggle = (pid) => setOpen(prev => {
    const n = new Set(prev)
    if (n.has(pid)) n.delete(pid); else n.add(pid)
    return n
  })

  const groups = groupByCategory(data?.products)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Par Check</h1>
          <p className="page-subtitle">
            {data
              ? <>{data.location_name} · {SOURCES.find(x => x.value === data.source)?.label.toLowerCase()} · what each order day's par left over at the next count</>
              : "Is each order day's par about right? What was left at the next count"}
          </p>
        </div>
      </div>

      <UsageFilterBar f={f} />
      <UsageStatus f={f} navigate={navigate} />

      {data && data.products.length > 0 && (
        <div className="table-wrap">
          <table className="usage-table parcheck-table">
            <thead>
              <tr>
                <th>Product</th>
                <th title="The order made on this day's count has to cover these days">Order day</th>
                <th className="usage-num" title="The par the latest of these orders was made with">Par</th>
                <th className="usage-num" title="Start count + regular orders received (median). Below par = the store ordered less than the par asked for">Stocked to</th>
                <th className="usage-num" title="Regular usage (actual − extra orders), median">Used</th>
                <th className="usage-num" title="Left at the next count, median">Left over</th>
                <th className="usage-num" title="The least that was left at the next count: how close it came to running out">Lowest left</th>
                <th className="usage-num" title="Windows that ended at 0">Ran out</th>
              </tr>
            </thead>
            <tbody>
              {groups.map(g => [
                <tr key={`cat-${g.name}`} className="usage-category-row"><td colSpan={8}>{g.name}</td></tr>,
                ...g.items.map(p => {
                  const isOpen = open.has(p.product_id)
                  const days = p.by_order_day.length ? p.by_order_day : [null]
                  return (
                    <Fragment key={p.product_id}>
                      {days.map((d, i) => (
                        <tr key={d ? d.order_day : 'none'}
                          className={`row-link ${i === days.length - 1 ? 'parcheck-last' : 'parcheck-inner'}`}
                          onClick={() => toggle(p.product_id)}>
                          {i === 0 && (
                            <td rowSpan={days.length}>
                              <span className="usage-caret">{isOpen ? '▾' : '▸'}</span>
                              <span className="usage-product">{p.product_name}</span>
                              <div className="usage-sub">{unitOf(p)} · {p.windows.length} window{p.windows.length === 1 ? '' : 's'}</div>
                            </td>
                          )}
                          {d === null ? (
                            <td colSpan={7} className="usage-sub">no usual windows yet</td>
                          ) : (
                            <>
                              <td>
                                <b>{SHORT_DAY[d.order_day]}</b> <span className="usage-chip-covers">{d.covers}</span>
                                {d.windows < 4 && <span className="usage-chip-n" title={`Only ${d.windows} window${d.windows === 1 ? '' : 's'} so far`}>({d.windows})</span>}
                                {d.with_extra > 0 && <span className="usage-tag" title={`${d.with_extra} of these windows had extra orders (catering leftovers sit in the next count)`}>extra ×{d.with_extra}</span>}
                              </td>
                              <td className="usage-num">{qty(p, d.par)}</td>
                              <td className={`usage-num ${d.par !== null && d.stocked_to < d.par ? 'usage-diff' : ''}`}>{qty(p, d.stocked_to)}</td>
                              <td className="usage-num">{qty(p, d.used)}</td>
                              <td className="usage-num">{qty(p, d.left)}</td>
                              <td className="usage-num usage-strong">
                                {qty(p, d.lowest_left)}
                                {pct(d.lowest_left, d.par) !== null && d.lowest_left > 0 &&
                                  <span className="parcheck-pct">{pct(d.lowest_left, d.par)}% of par</span>}
                              </td>
                              <td className={`usage-num ${d.ran_out ? 'usage-neg' : 'usage-muted'}`}>
                                {d.ran_out ? `${d.ran_out} of ${d.windows}` : '—'}
                              </td>
                            </>
                          )}
                        </tr>
                      ))}

                      {isOpen && (
                        <tr className="usage-detail-row">
                          <td colSpan={8}>
                            <ParWindows p={p} qty={qty} navigate={navigate} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                }),
              ])}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ParWindows({ p, qty, navigate }) {
  return (
    <table className="usage-windows parcheck-windows">
      <thead>
        <tr>
          <th title="Counts are end of day: the Monday count to the Wednesday count covers Tue → Wed">Days covered</th>
          <th>Order day</th>
          <th className="usage-num">Par</th>
          <th className="usage-num">Start</th>
          <th className="usage-num">+ Regular received</th>
          <th className="usage-num">= Stocked to</th>
          <th className="usage-num">Used</th>
          <th className="usage-num">Left over</th>
        </tr>
      </thead>
      <tbody>
        {p.windows.map(w => (
          <tr key={w.start_date} className={w.usual ? '' : 'usage-off'}>
            <td>
              {fmtCovers(w)}
              {!w.usual && <span className="usage-tag" title="A count was missed or added: not used for the order-day numbers">unusual</span>}
              {w.extra > 0 && <span className="usage-tag" title="Extra orders came in this window">extra {qty(p, w.extra)}</span>}
            </td>
            <td>{SHORT_DAY[w.order_day]}</td>
            <td className="usage-num">{qty(p, w.par)}</td>
            <td className="usage-num">
              <a className="usage-link" onClick={() => w.start_inventory_id && navigate(`/inventory/${w.start_inventory_id}`)}>{qty(p, w.start)}</a>
            </td>
            <td className="usage-num">{w.received_regular ? qty(p, w.received_regular) : '—'}</td>
            <td className={`usage-num ${w.par !== null && w.stocked_to < w.par ? 'usage-diff' : ''}`}
              title={w.par !== null && w.stocked_to < w.par ? 'Stocked below par: the store ordered less than the par asked for' : undefined}>
              {qty(p, w.stocked_to)}
            </td>
            <td className="usage-num">{qty(p, w.used)}</td>
            <td className={`usage-num usage-strong ${w.left <= 0 ? 'usage-neg' : ''}`}>
              <a className="usage-link" onClick={() => w.end_inventory_id && navigate(`/inventory/${w.end_inventory_id}`)}>{qty(p, w.left)}</a>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
