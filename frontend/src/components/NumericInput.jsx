// NumericInput.jsx — iOS-friendly numeric input
// Uses type="text" + inputMode to reliably trigger numpad on iPad/iPhone

export function NumericInput({ value, onChange, allowDecimals = true, allowNegative = false, ...props }) {
  const handleChange = (e) => {
    let inputValue = e.target.value

    // Normalize commas to periods (European locale iPads)
    inputValue = inputValue.replace(/,/g, '.')

    if (allowNegative) {
      inputValue = inputValue.replace(/[^0-9.-]/g, '')
      inputValue = inputValue.replace(/(?!^)-/g, '')
    } else {
      inputValue = inputValue.replace(/[^0-9.]/g, '')
    }

    if (allowDecimals) {
      // Enforce single decimal point
      inputValue = inputValue.replace(/(\..*?)\..*/g, '$1')
    } else {
      inputValue = inputValue.replace(/\./g, '')
    }

    if (onChange) {
      e.target.value = inputValue
      onChange(e)
    }
  }

  return (
    <input
      {...props}
      type="text"
      inputMode={allowDecimals ? 'decimal' : 'numeric'}
      pattern={allowDecimals ? undefined : '[0-9]*'}
      value={value}
      onChange={handleChange}
    />
  )
}
