// =============================================================================
// features/usage/pages/ParCheckPage.jsx      URL: /usage/par-check   (Usage > Par Check)
// =============================================================================
// The usage windows read from the other side: is each order day's par about
// right? For every window: the par its order was made with, what the store
// stocked up to (start count + regular orders received), what it used
// (regular) and what was LEFT at the next count. A par that always leaves a
// lot behind is more than that order day needs; one that runs out is tight.
// Per order day: medians and the lowest left over of the last 4 usual
// windows (windows with extra orders count; they are marked). Only real
// windows on the current count days: windows joined from an older, more
// frequent schedule span several deliveries and are left out. Clicking the product
// opens every window (newest first); clicking an order-day row opens only
// that day's windows.
// Filters / loading shared with the Usage Report: ../components/UsageFilters.jsx
// Data: GET /api/usage/par-check (backend/features/usage/usage_routes.py)
// =============================================================================
import { useState, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useUsageReport, UsageFilterBar, UsageStatus, groupByCategory,
  fmtCovers, fmtCountDays, SHORT_DAY, SOURCES,
} from '../components/UsageFilters.jsx'
import '../../../core/styles/shared-ui.css'
import './UsagePage.css'
import './ParCheckPage.css'

const pct = (a, b) => (a === null || a === undefined || !b) ? null : Math.round((a / b) * 100)

export default function ParCheckPage() {
  const navigate = useNavigate()
  const f = useUsageReport('/api/usage/par-check')
  const { data, qty, unitOf } = f
  // product id -> 'all' (every window, by date) or an order day (only that day's windows)
  const [open, setOpen] = useState({})

  const show = (pid, what) => setOpen(prev => {
    const n = { ...prev }
    if (n[pid] === what) delete n[pid]; else n[pid] = what
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
                  const what = open[p.product_id]
                  const isOpen = what !== undefined
                  const days = p.by_order_day.length ? p.by_order_day : [null]
                  return (
                    <Fragment key={p.product_id}>
                      {days.map((d, i) => (
                        <tr key={d ? d.order_day : 'none'}
                          className={`row-link ${i === days.length - 1 ? 'parcheck-last' : 'parcheck-inner'} ${d && what === d.order_day ? 'is-active' : ''}`}
                          title={d ? `Click to see only the ${d.order_day} windows` : undefined}
                          onClick={() => show(p.product_id, d ? d.order_day : 'all')}>
                          {i === 0 && (
                            <td rowSpan={days.length} className="parcheck-product"
                              title="Click to see every window, newest first"
                              onClick={e => { e.stopPropagation(); show(p.product_id, 'all') }}>
                              <span className="usage-caret">{isOpen ? '▾' : '▸'}</span>
                              <span className="usage-product">{p.product_name}</span>
                              <div className="usage-sub" title="Current count days: counted on these days in at least 2 of the last 3 weeks">
                                {unitOf(p)} · counted {fmtCountDays(p.count_days)}
                              </div>
                            </td>
                          )}
                          {d === null ? (
                            <td colSpan={7} className="usage-sub">no windows on the current count days yet</td>
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
                            <ParWindows p={p} qty={qty} navigate={navigate} day={what === 'all' ? null : what}
                              onShowAll={() => show(p.product_id, 'all')} />
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

// day = null: every window, newest first. day = 'Monday': only that order day's windows.
function ParWindows({ p, qty, navigate, day, onShowAll }) {
  const d = day && p.by_order_day.find(x => x.order_day === day)
  const windows = day ? p.windows.filter(w => w.order_day === day) : p.windows
  return (
    <table className="usage-windows parcheck-windows">
      <thead>
        <tr>
          <th title="Counts are end of day: the Monday count to the Wednesday count covers Tue → Wed">Days covered</th>
          <th className="usage-num">Par</th>
          <th className="usage-num">Start</th>
          <th className="usage-num">+ Regular received</th>
          <th className="usage-num">= Stocked to</th>
          <th className="usage-num">Used</th>
          <th className="usage-num">Left over</th>
        </tr>
      </thead>
      <tbody>
        {day && (
          <tr className="usage-day-row">
            <td colSpan={7}>
              {SHORT_DAY[day]} order
              {d && <> · covers {d.covers} · par <b>{qty(p, d.par)}</b> · lowest left <b>{qty(p, d.lowest_left)}</b></>}
              <a className="usage-link usage-day-all" onClick={onShowAll}>show all windows</a>
              <span className="usage-day-n">{windows.length} window{windows.length === 1 ? '' : 's'}</span>
            </td>
          </tr>
        )}
        {windows.map(w => (
          <tr key={w.start_date} className={w.usual ? '' : 'usage-off'}>
            <td>
              {fmtCovers(w)}
              {!day && <span className="usage-chip-covers parcheck-day">{SHORT_DAY[w.order_day]} order</span>}
              {!w.usual && <span className="usage-tag" title="Not the usual length for this order day (a missed or extra count): not used for the order-day numbers">unusual</span>}
              {w.extra > 0 && <span className="usage-tag" title="Extra orders came in this window">extra {qty(p, w.extra)}</span>}
            </td>
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
        {p.joined_hidden > 0 && (
          <tr className="usage-day-row usage-day-note">
            <td colSpan={7}>
              {p.joined_hidden} older window{p.joined_hidden === 1 ? '' : 's'} from a more frequent schedule not shown here:
              joined windows span several deliveries, so they say nothing about the current par. The Usage Report shows them.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  )
}
