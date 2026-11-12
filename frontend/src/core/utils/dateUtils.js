// dateUtils.js — consistent date handling across the app
// Fixes the JavaScript UTC midnight bug where '2026-07-01' displays as June 30 in local time

/**
 * Parse a DATE string (YYYY-MM-DD) as local midnight, not UTC midnight.
 * Use for count_date, order_date, expected_date — pure calendar dates with no timezone.
 */
export function parseLocalDate(dateStr) {
  if (!dateStr) return null
  // Take only the date part in case a full timestamp is passed
  const datePart = String(dateStr).slice(0, 10)
  // Append T00:00:00 to force local time interpretation
  return new Date(`${datePart}T00:00:00`)
}

/**
 * Format a DATE string for display — weekday, month, day, year.
 * e.g. "Wednesday, July 1, 2026"
 */
export function formatDate(dateStr) {
  if (!dateStr) return '—'
  return parseLocalDate(dateStr).toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
  })
}

/**
 * Format a DATE string as short — Mon, Jul 1, 2026
 */
export function formatDateShort(dateStr) {
  if (!dateStr) return '—'
  return parseLocalDate(dateStr).toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
  })
}

/**
 * Convert a DATE string to YYYY-MM-DD for use in <input type="date"> defaultValue.
 * Safe — won't shift the date by timezone offset.
 */
export function toDateInputValue(dateStr) {
  if (!dateStr) return ''
  return String(dateStr).slice(0, 10)
}

/**
 * Format a TIMESTAMPTZ for display — these are real UTC timestamps, convert to local.
 * e.g. submitted_at, created_at
 */
export function formatTimestamp(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}
