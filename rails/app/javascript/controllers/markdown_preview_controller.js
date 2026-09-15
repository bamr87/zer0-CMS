import { Controller } from "@hotwired/stimulus"

// Live markdown preview: waits for a pause in typing, cancels any request
// still in flight, and renders the server's sanitized HTML.
export default class extends Controller {
  static targets = ["source", "output"]
  static values = { url: String, delay: { type: Number, default: 350 } }

  disconnect() {
    clearTimeout(this.timer)
    this.request?.abort()
  }

  queue() {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.render(), this.delayValue)
  }

  async render() {
    if (!this.hasSourceTarget || !this.hasOutputTarget || !this.urlValue) return

    this.request?.abort()
    this.request = new AbortController()
    const token = document.querySelector('meta[name="csrf-token"]')?.content
    try {
      const response = await fetch(this.urlValue, {
        method: "POST",
        headers: { "X-CSRF-Token": token, "Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html" },
        body: new URLSearchParams({ markdown: this.sourceTarget.value }),
        signal: this.request.signal,
        credentials: "same-origin"
      })
      if (response.ok) this.outputTarget.innerHTML = await response.text()
    } catch (error) {
      if (error.name !== "AbortError") console.warn("markdown preview failed", error)
    }
  }
}
