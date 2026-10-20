import { Controller } from "@hotwired/stimulus"

// Keeps a live log box pinned to the newest line — but only when the user is
// already at the bottom, so scrolling up to read history is not yanked back
// down every time a Turbo Stream appends a chunk.
export default class extends Controller {
  connect() {
    this.pinned = true
    this.onScroll = this.onScroll.bind(this)
    this.element.addEventListener("scroll", this.onScroll)
    this.observer = new MutationObserver(() => this.scroll())
    this.observer.observe(this.element, { childList: true, subtree: true })
    this.scroll()
  }

  disconnect() {
    this.observer?.disconnect()
    this.element.removeEventListener("scroll", this.onScroll)
  }

  onScroll() {
    const { scrollTop, scrollHeight, clientHeight } = this.element
    this.pinned = scrollHeight - scrollTop - clientHeight < 40
  }

  scroll() {
    if (this.pinned) this.element.scrollTop = this.element.scrollHeight
  }
}
