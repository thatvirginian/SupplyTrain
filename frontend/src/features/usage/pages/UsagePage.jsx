// =============================================================================
// features/usage/pages/UsagePage.jsx      URL: /usage   (Usage > Usage Report)
// =============================================================================
// Actual usage for one store, count to count (each "window" = from one count to
// the next). Counts are end of day, so a window is labelled by the days it
// covers: Monday count -> Wednesday count = Tue -> Wed.
// Which counts make the windows: order sheets (OH), inventories, or all.
// Per product: the normal regular usage per window (median of the last 4 usual
// windows for that order day), totals for the range, and every window with how
// its number was reached:
//   start + received + transfers in - transfers out - end = actual
//   actual - extra orders = regular
// Ordered (not part of the math) = what the store asked for on the orders
// delivered in the window, regular + extra, before any commissary change.
// Windows use the product's CURRENT count days; older history on more days is
// joined into the same wider windows (exact: counts in between cancel out).
// The click-down groups windows by order day.
// Each received order / transfer / count opens its source.
// Filters / loading shared with Par Check: ../components/UsageFilters.jsx
// Data: GET /api/usage (backend/features/usage/usage_routes.py)
// =============================================================================
import { useState, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useUsageReport, UsageFilterBar, UsageStatus, groupByCategory, groupByOrderDay,
  fmtDay, fmtCovers, fmtCountDays, SHORT_DAY, SOURCES,
} from '../components/UsageFilters.jsx'
import '../../../core/styles/shared-ui.css'
import './UsagePage.css'

const SOURCE_LINK = { order: id => `/orders/${id}`, transfer: id => `/transfers/${id}` }

const COUNTS_AS = {
  received:     '+ received',
  extra:        '− extra order',
  transfer_in:  '+ transfer in',
  transfer_out: '− transfer out',
}

export default function UsagePage() {
  const navigate = useNavigate()
  const f = useUsageReport('/api/usage')
  const { data, qty, unitOf } = f

  const [open,    setOpen]    = useState(new Set())    // product ids expanded
  const [openWin, setOpenWin] = useState(new Set())    // `${pid}:${start}` with sources shown

  const toggle = (setFn, key) => setFn(prev => {
    const n = new Set(prev)
    if (n.has(key)) n.delete(key); else n.add(key)
    return n
  })

  const groups = groupByCategory(data?.products)

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Usage Report</h1>
          <p className="page-subtitle">
            {data
              ? <>{data.location_name} · {SOURCES.find(x => x.value === data.source)?.label.toLowerCase()} · regular = actual − extra orders</>
              : 'What each store used between counts'}
          </p>
        </div>
      </div>

      <UsageFilterBar f={f} />
      <UsageStatus f={f} navigate={navigate} />

      {data && data.products.length > 0 && (
        <div className="table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>Product</th>
                <th title="Per par day (the day of the count and order): median regular usage of the last 4 usual windows that order has to cover">Median per par day</th>
                <th className="usage-num" title="What the store asked for on the orders delivered in these windows (regular + extra), before any commissary change. Not part of the math: received is.">Ordered</th>
                <th className="usage-num">Actual</th>
                <th className="usage-num">Extra orders</th>
                <th className="usage-num">Regular</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {groups.map(g => [
                <tr key={`cat-${g.name}`} className="usage-category-row"><td colSpan={7}>{g.name}</td></tr>,
                ...g.items.map(p => {
                  const isOpen = open.has(p.product_id)
                  return (
                    <Fragment key={p.product_id}>
                      <tr className="row-link" onClick={() => toggle(setOpen, p.product_id)}>
                        <td>
                          <span className="usage-caret">{isOpen ? '▾' : '▸'}</span>
                          <span className="usage-product">{p.product_name}</span>
                          <div className="usage-sub" title="Current count days: counted on these days in at least 2 of the last 3 weeks. Older history is cut to these days.">
                            {unitOf(p)} · counted {fmtCountDays(p.count_days)}
                          </div>
                        </td>
                        <td>
                          {p.normal_by_order_day.length === 0
                            ? <span className="usage-sub">no usual windows yet</span>
                            : p.normal_by_order_day.map(n => (
                              <span key={n.order_day} className="usage-chip"
                                title={`${n.order_day} par: what the ${n.order_day} order has to cover, ${n.covers} (${n.days} day${n.days === 1 ? '' : 's'}). Median of the last ${n.windows} window${n.windows === 1 ? '' : 's'}`}>
                                {SHORT_DAY[n.order_day]} <b>{qty(p, n.median_regular)}</b>
                                <span className="usage-chip-covers">{n.covers}</span>
                                {n.windows < 4 && <span className="usage-chip-n">({n.windows})</span>}
                              </span>
                            ))}
                        </td>
                        <td className="usage-num usage-muted">{p.totals.ordered ? qty(p, p.totals.ordered) : '—'}</td>
                        <td className="usage-num">{qty(p, p.totals.actual)}</td>
                        <td className="usage-num usage-extra">{p.totals.extra ? qty(p, p.totals.extra) : '—'}</td>
                        <td className="usage-num usage-strong">{qty(p, p.totals.regular)}</td>
                        <td>{p.flag_count > 0 && <span className="usage-flag-count" title="Windows with something to check">⚠ {p.flag_count}</span>}</td>
                      </tr>

                      {isOpen && (
                        <tr className="usage-detail-row">
                          <td colSpan={7}>
                            <WindowTable p={p} qty={qty} openWin={openWin}
                              toggleWin={k => toggle(setOpenWin, k)} navigate={navigate} />
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

function WindowTable({ p, qty, openWin, toggleWin, navigate }) {
  return (
    <table className="usage-windows">
      <thead>
        <tr>
          <th title="Counts are end of day: the Monday count to the Wednesday count covers Tue → Wed">Days covered</th>
          <th className="usage-num">Start</th>
          <th className="usage-num" title="What the store asked for on the orders delivered in this window (regular + extra), before any commissary change. Not part of the math: received is.">Ordered</th>
          <th className="usage-num">+ Received</th>
          <th className="usage-num">± Transfers</th>
          <th className="usage-num">− End</th>
          <th className="usage-num">= Actual</th>
          <th className="usage-num">− Extra</th>
          <th className="usage-num">= Regular</th>
        </tr>
      </thead>
      <tbody>
        {groupByOrderDay(p.windows).map(g => {
          const n = p.normal_by_order_day.find(x => x.order_day === g.day)
          return (
            <Fragment key={g.day}>
              <tr className="usage-day-row">
                <td colSpan={9}>
                  {SHORT_DAY[g.day]} order
                  {n && <> · covers {n.covers} · median <b>{qty(p, n.median_regular)}</b></>}
                  <span className="usage-day-n">{g.windows.length} window{g.windows.length === 1 ? '' : 's'}</span>
                </td>
              </tr>
              {g.windows.map(w => {
                const key = `${p.product_id}:${w.start_date}`
                const shown = openWin.has(key)
                const net = w.transfers_in - w.transfers_out
                return (
                  <Fragment key={key}>
                    <tr className={`row-link ${w.usual ? '' : 'usage-off'}`} onClick={() => toggleWin(key)}>
                      <td>
                        <span className="usage-caret">{shown ? '▾' : '▸'}</span>
                        {fmtCovers(w)}
                        {w.skipped_counts > 0 && (
                          <span className="usage-tag usage-tag-join" title={w.flags.find(f => f.code === 'joined')?.text}>
                            joined ×{w.skipped_counts + 1}
                          </span>
                        )}
                        {!w.usual && (
                          <span className="usage-tag" title={w.flags.find(f => f.code.endsWith('_than_usual'))?.text}>
                            {w.flags.some(f => f.code === 'longer_than_usual') ? 'longer' : 'extra count'}
                          </span>
                        )}
                        {w.flags.filter(f => !f.code.endsWith('_than_usual') && f.code !== 'joined').map(f => (
                          <span key={f.code} className="usage-tag usage-tag-warn" title={f.text}>⚠</span>
                        ))}
                      </td>
                      <td className="usage-num">{qty(p, w.start)}</td>
                      <td className={`usage-num usage-muted ${w.ordered !== w.received ? 'usage-diff' : ''}`}
                        title={w.ordered !== w.received ? 'Received differs from what was ordered (commissary change or a returned line)' : undefined}>
                        {w.ordered ? qty(p, w.ordered) : '—'}
                      </td>
                      <td className="usage-num">{w.received ? qty(p, w.received) : '—'}</td>
                      <td className="usage-num">{net ? (net > 0 ? '+' : '−') + qty(p, Math.abs(net)) : '—'}</td>
                      <td className="usage-num">{qty(p, w.end)}</td>
                      <td className="usage-num usage-strong">{qty(p, w.actual)}</td>
                      <td className="usage-num usage-extra">{w.extra ? qty(p, w.extra) : '—'}</td>
                      <td className={`usage-num usage-strong ${w.regular < 0 ? 'usage-neg' : ''}`}>{qty(p, w.regular)}</td>
                    </tr>
                    {shown && (
                      <tr className="usage-sources-row">
                        <td colSpan={9}>
                          <ul className="usage-sources">
                            <li>
                              <span className="usage-src-date">{fmtDay(w.start_date)}</span>
                              <a className="usage-link" onClick={() => w.start_inventory_id && navigate(`/inventory/${w.start_inventory_id}`)}>Start count</a>
                              <span className="usage-src-as">on hand</span>
                              <span className="usage-src-qty">{qty(p, w.start)}</span>
                            </li>
                            {w.sources.map((s, i) => (
                              <li key={i}>
                                <span className="usage-src-date">{fmtDay(s.date)}</span>
                                <a className="usage-link" onClick={() => navigate(SOURCE_LINK[s.type](s.id))}>{s.label}</a>
                                <span className="usage-src-as">{COUNTS_AS[s.counts_as]}</span>
                                <span className="usage-src-qty">{qty(p, s.base_quantity)}</span>
                              </li>
                            ))}
                            <li>
                              <span className="usage-src-date">{fmtDay(w.end_date)}</span>
                              <a className="usage-link" onClick={() => w.end_inventory_id && navigate(`/inventory/${w.end_inventory_id}`)}>End count</a>
                              <span className="usage-src-as">− on hand</span>
                              <span className="usage-src-qty">{qty(p, w.end)}</span>
                            </li>
                            {w.flags.map(f => <li key={f.code} className="usage-src-flag">⚠ {f.text}</li>)}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}
