# frozen_string_literal: true

module StudioHelper
  # A saved render as a thumbnail card. The SVG is inlined from the database —
  # these are parametric pieces, a few KB to a few hundred KB, and the studio is
  # a local single-user tool, so inline beats round-tripping through a file.
  def render_card(render)
    link_to studio_render_path(render), class: "card pad-0", style: "display:block; text-decoration:none; color:inherit;" do
      body = content_tag(:div, class: "preview-frame", style: "min-height:120px; aspect-ratio: 3/2;") do
        render.svg.present? ? raw(studio_scaled_svg(render.svg)) : content_tag(:span, "no svg", class: "faint")
      end
      meta = content_tag(:div, style: "padding:.5rem .7rem;") do
        safe_join([
          content_tag(:div, render.generator, class: "mono", style: "font-size:.82rem; font-weight:600;"),
          content_tag(:div, render.slug, class: "faint mono", style: "font-size:.72rem;"),
          (render.favorite ? content_tag(:span, "★ favorite", class: "badge", style: "margin-top:.3rem;") : "".html_safe)
        ])
      end
      safe_join([body, meta])
    end
  end

  # Strip the fixed 1536×1024 width/height so the SVG scales to its container
  # via viewBox; the sanitizer guarantees a viewBox is present. Leaves the
  # rest of the markup untouched.
  def studio_scaled_svg(svg)
    svg.sub(/<svg\b[^>]*?>/) do |tag|
      tag.gsub(/\s(width|height)="[^"]*"/, "").sub("<svg", '<svg style="width:100%;height:auto;"')
    end
  end
end
