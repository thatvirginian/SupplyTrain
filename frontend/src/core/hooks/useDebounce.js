import { useState, useEffect } from 'react'

/**
 * useDebounce
 * Returns a debounced version of the value that only updates
 * after the specified delay has passed without the value changing.
 *
 * @param {any}    value  — the value to debounce
 * @param {number} delay  — delay in milliseconds (default 300)
 */
export function useDebounce(value, delay = 300) {
  const [debouncedValue, setDebouncedValue] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return debouncedValue
}
