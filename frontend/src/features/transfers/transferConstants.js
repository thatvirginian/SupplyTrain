// transferConstants.js: transfer statuses and reasons (match transfer_routes.py / the DB CHECKs)

export const TRANSFER_STATUS_BADGE = {
  open:      'badge-warning',
  sent:      'badge-info',
  received:  'badge-success',
  cancelled: 'badge-error',
}

export const TRANSFER_REASONS = [
  { value: 'shortage',  label: 'Ran short' },
  { value: 'catering',  label: 'Catering' },
  { value: 'event',     label: 'Event' },
  { value: 'overstock', label: 'Overstock' },
  { value: 'other',     label: 'Other' },
]
export const reasonLabel = (r) => TRANSFER_REASONS.find(x => x.value === r)?.label || ''

export const capitalize = (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : ''
