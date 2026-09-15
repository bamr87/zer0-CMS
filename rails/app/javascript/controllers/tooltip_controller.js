import { Controller } from "@hotwired/stimulus"

// Administrate's search-filter help popover, shown on hover.
export default class extends Controller {
  static targets = ["popover", "tooltip"]

  connect() {
    this.show = () => this.popoverTarget.showPopover?.()
    this.hide = () => this.popoverTarget.hidePopover?.()
    this.tooltipTarget.addEventListener("mouseenter", this.show)
    this.tooltipTarget.addEventListener("mouseleave", this.hide)
  }

  disconnect() {
    this.tooltipTarget.removeEventListener("mouseenter", this.show)
    this.tooltipTarget.removeEventListener("mouseleave", this.hide)
  }
}
