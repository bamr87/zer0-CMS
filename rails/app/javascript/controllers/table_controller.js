import { Controller } from "@hotwired/stimulus"

// Administrate's clickable index rows, without jQuery: a click (or Enter /
// Space) anywhere on a row that is not itself a control visits the row's URL.
export default class extends Controller {
  visitDataUrl(event) {
    const activating = event.type === "click" || event.key === "Enter" || event.key === " "
    if (!activating || event.target.closest("a, button, input, form")) return

    const url = event.target.closest("tr")?.dataset.url
    if (url && window.getSelection().toString().length === 0) window.Turbo.visit(url)
  }
}
