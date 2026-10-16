import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["panel"]

  toggle() {
    this.panelTarget.classList.toggle("open")
    document.body.classList.toggle("nav-open")
  }

  close() {
    this.panelTarget.classList.remove("open")
    document.body.classList.remove("nav-open")
  }
}
