import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'

// ── iOS standalone mode — prevent links opening in Safari ─────────────────────
// When added to iPad home screen, tapping <a> tags can break out of the app.
// This intercepts clicks and keeps navigation inside the standalone window.
if (window.navigator.standalone) {
  document.addEventListener('click', (e) => {
    const link = e.target.closest('a')
    if (link && link.href && link.target !== '_blank') {
      e.preventDefault()
      window.location.href = link.href
    }
  }, false)
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
