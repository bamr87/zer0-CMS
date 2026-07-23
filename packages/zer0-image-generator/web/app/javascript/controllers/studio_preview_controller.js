import { Controller } from "@hotwired/stimulus"

// Drives the SVG studio's live preview: on any knob change it POSTs the current
// form values and swaps the returned Turbo Frame into the preview pane. It also
// mirrors the knob values into the hidden Save/Sweep forms so those submit
// exactly what is on screen. Debounced so dragging a number field does not fire
// a render per keystroke.
export default class extends Controller {
  static targets = ["form", "frame", "saveFields", "sweepFields"]
  static values = { url: String }

  connect() {
    this.timer = null
    this.render()
  }

  render() {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.submit(), 180)
  }

  async submit() {
    const data = new FormData(this.formTarget)
    this.syncHiddenForms(data)
    try {
      const res = await fetch(this.urlValue, {
        method: "POST",
        headers: { "X-CSRF-Token": this.csrf(), "Accept": "text/vnd.turbo-stream.html, text/html" },
        body: data,
      })
      const html = await res.text()
      // The response is a <turbo-frame id="studio-preview">…. Swap its CONTENTS
      // into our frame rather than replacing the element — replacing it would
      // drop the Stimulus target attribute and break every render after the
      // first.
      const doc = new DOMParser().parseFromString(html, "text/html")
      const fresh = doc.querySelector("#studio-preview")
      if (fresh) this.frameTarget.innerHTML = fresh.innerHTML
    } catch (e) {
      // A failed preview is non-fatal — the user can nudge a knob to retry.
      console.error("preview failed", e)
    }
  }

  // Copy the live knob values into the hidden Save and Sweep forms as fields,
  // so submitting either persists/queues the current on-screen configuration.
  syncHiddenForms(data) {
    for (const target of [this.saveFieldsTarget, this.sweepFieldsTarget]) {
      target.innerHTML = ""
      for (const [key, value] of data.entries()) {
        const input = document.createElement("input")
        input.type = "hidden"
        input.name = key
        input.value = value
        target.appendChild(input)
      }
    }
  }

  reroll() {
    const seed = this.formTarget.querySelector('[name="seed"]')
    if (seed) {
      seed.value = Math.floor(Math.random() * 2_147_483_647)
      this.render()
    }
  }

  sweep() {
    document.getElementById("sweep-form").requestSubmit()
  }

  csrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || ""
  }
}
