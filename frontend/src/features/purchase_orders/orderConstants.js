// orderConstants.js: reasons for unscheduled orders (match unscheduled_order_routes.py / the DB CHECK)

export const ORDER_REASONS = [
  { value: 'catering', label: 'Catering' },
  { value: 'event',    label: 'Event' },
  { value: 'special',  label: 'Special request' },
  { value: 'other',    label: 'Other' },
]

export const orderReasonLabel = (r) => ORDER_REASONS.find(x => x.value === r)?.label || 'Other'
