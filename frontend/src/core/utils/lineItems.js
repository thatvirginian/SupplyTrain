// lineItems.js: helpers for core/components/LineItemEditor.jsx
/** Lines → API payload: drops lines with no quantity. */
export function linesToPayload(lines) {
  return lines
    .filter(l => parseFloat(l.quantity) > 0)
    .map(l => ({ product_id: l.product_id, quantity: parseFloat(l.quantity), unit_id: l.unit_id || null }))
}
