import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["title", "description", "titleCount", "descCount", "body", "preview"]
  static values = { previewUrl: String }

  connect() {
    this.refreshCounts()
  }

  refreshCounts() {
    if (this.hasTitleTarget && this.hasTitleCountTarget) {
      const n = this.titleTarget.value.length
      this.titleCountTarget.textContent = `${n} / 60`
      this.titleCountTarget.classList.toggle("seo-warn", n < 30 || n > 60)
    }
    if (this.hasDescriptionTarget && this.hasDescCountTarget) {
      const n = this.descriptionTarget.value.length
      this.descCountTarget.textContent = `${n} / 160`
      this.descCountTarget.classList.toggle("seo-warn", n < 70 || n > 160)
    }
  }

  async refreshPreview() {
    if (!this.hasPreviewTarget || !this.hasPreviewUrlValue || !this.hasBodyTarget) return
    const token = document.querySelector('meta[name="csrf-token"]')?.content
    const body = new URLSearchParams({ markdown: this.bodyTarget.value })
    const response = await fetch(this.previewUrlValue, {
      method: "POST",
      headers: { "X-CSRF-Token": token, "Content-Type": "application/x-www-form-urlencoded" },
      body
    })
    if (!response.ok) return
    this.previewTarget.innerHTML = await response.text()
  }
}
