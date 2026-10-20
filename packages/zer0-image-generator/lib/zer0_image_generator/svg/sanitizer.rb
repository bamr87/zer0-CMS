# frozen_string_literal: true

require "rexml/document"

module Zer0ImageGenerator
  # SVG toolkit — the sanitizer, deterministic local renderer and rasterizer
  # chain ported from preview_generator.py's "SVG toolkit" section. The Python
  # keeps these as module globals in one file; the Ruby port splits them across
  # sanitizer.rb / local_renderer.rb / rasterizer.rb but they remain one
  # namespace and share the geometry contract defined here.
  module Svg
    SVG_NS = "http://www.w3.org/2000/svg"
    XLINK_NS = "http://www.w3.org/1999/xlink"

    # Banner geometry for SVG-producing providers (claude, local). Every SVG
    # is squashed into this frame by sanitize_svg, and the rasterizer exports
    # at exactly these pixel dimensions. This is a shared cross-slice contract.
    SVG_WIDTH = 1536
    SVG_HEIGHT = 1024

    # Raised when model-produced SVG is unusable (unparseable, wrong root,
    # or carrying a rejected DOCTYPE/ENTITY). Mirrors Python's SvgError.
    class SvgError < StandardError; end

    module Sanitizer
      # Elements deleted outright: active content (script/iframe/audio/video),
      # the XML/HTML escape hatch (foreignObject) and raster payloads (<image>).
      BANNED_SVG_ELEMENTS = %w[script foreignObject iframe audio video image].freeze

      # url() references that are NOT #-local (i.e. not url(#id), url('#id') or
      # url("#id")). Anything else — url(http://…), url(data:…) — is external
      # and gets neutralized to "none". Case-insensitive, matches Python's
      # re.compile(r"url\(\s*(?!#|'#|\"#)[^)]*\)", re.I).
      URL_REF = /url\(\s*(?!#|'#|"#)[^)]*\)/i

      # DOCTYPE/ENTITY sniff run on the RAW text before parsing. Entity
      # declarations enable billion-laughs expansion and external-reference
      # attacks; a legit banner SVG needs neither, so reject rather than clean.
      DOCTYPE_RE = /<!\s*(DOCTYPE|ENTITY)/i

      IMPORT_RE = /@import[^;]*;?/i

      module_function

      # Element/attribute local name — the part after "}" in a Clark-notation
      # tag. REXML already exposes local names via #name, so this only exists
      # for the raw-string comparisons that mirror Python's _localname.
      def localname(tag)
        i = tag.rindex("}")
        i ? tag[(i + 1)..] : tag
      end

      # Neutralize a style/presentation value: drop @import rules, then rewrite
      # every non-local url(...) to "none". Mirrors Python's _scrub_style_text —
      # @import is stripped FIRST so a url() inside it is gone before URL_REF runs.
      def scrub_style_text(value)
        value = value.gsub(IMPORT_RE, "")
        value.gsub(URL_REF, "none")
      end

      # Parse + sanitize model-produced SVG. Raises SvgError when unusable.
      #
      # Strips scripts/foreignObject/external references/event handlers; forces
      # the banner viewBox/width/height. Returns [clean_svg, warnings].
      #
      # NOTE ON BYTE-IDENTITY: unlike render_local_svg, the sanitized *string*
      # is intentionally NOT byte-identical to Python's ElementTree output —
      # REXML and ElementTree serialize namespaces, attribute order and
      # self-closing tags differently. The security contract is what must
      # match: everything the Python strips, this strips, and the forced
      # geometry is identical.
      def sanitize_svg(svg_text)
        warnings = []
        if svg_text =~ DOCTYPE_RE
          raise SvgError, "SVG contains a DOCTYPE/ENTITY declaration (rejected)"
        end

        begin
          # REXML is more lenient about undeclared-prefix errors than
          # ElementTree, but both reject malformed markup. Entity expansion is
          # already precluded — DTDs were rejected above.
          doc = REXML::Document.new(svg_text)
        rescue REXML::ParseException => exc
          raise SvgError, "SVG does not parse: #{exc.message}"
        end

        root = doc.root
        raise SvgError, "SVG does not parse: no root element" if root.nil?
        unless root.name == "svg"
          raise SvgError, "Root element is <#{root.name}>, not <svg>"
        end

        scrub(root, warnings)

        # Force banner geometry. add_attribute overwrites in place when the
        # attribute already exists, matching ET's root.set().
        root.add_attribute("viewBox", "0 0 #{SVG_WIDTH} #{SVG_HEIGHT}")
        root.add_attribute("width", SVG_WIDTH.to_s)
        root.add_attribute("height", SVG_HEIGHT.to_s)

        # Serialize with no reformatting: the default formatter preserves the
        # tree as-is (no pretty-print), which keeps text/whitespace intact.
        out = +""
        REXML::Formatters::Default.new.write(root, out)
        [out, warnings]
      end

      # Depth-first scrub. Mirrors Python's nested scrub(): banned child
      # elements are removed (and NOT recursed into), surviving children are
      # recursed, then this element's attributes and <style> text are cleaned.
      def scrub(element, warnings)
        # Snapshot children — we mutate the tree while iterating. REXML's
        # #elements yields only Element nodes (skips text/comments/CDATA),
        # matching ElementTree's list(element).
        element.elements.to_a.each do |child|
          name = child.name
          if BANNED_SVG_ELEMENTS.include?(name)
            element.delete_element(child)
            warnings << "removed <#{name}>"
            next
          end
          scrub(child, warnings)
        end

        # REXML surfaces namespace declarations (xmlns, xmlns:*) as attributes
        # too, which ElementTree does not — but they never match any removal
        # condition (their local names aren't "on*"/"href", their values are
        # namespace URIs), so processing them is behavior-equivalent.
        element.attributes.each_attribute.to_a.each do |attr|
          local = attr.name # REXML #name is already the local name
          value = attr.value
          if local.downcase.start_with?("on")
            element.attributes.delete(attr)
            warnings << "removed #{local} handler"
          elsif local == "href" && !value.start_with?("#")
            element.attributes.delete(attr)
            warnings << "removed external href"
          elsif value.downcase.include?("url(") || value.downcase.include?("@import")
            # Covers style= AND presentation attributes (fill, stroke, filter,
            # mask, clip-path, …) — url() must stay #-local.
            cleaned = scrub_style_text(value)
            if cleaned != value
              element.attributes[attr.expanded_name] = cleaned
              warnings << "scrubbed url() in #{local}"
            end
          end
        end

        if element.name == "style" && element.text
          cleaned = scrub_style_text(element.text)
          if cleaned != element.text
            element.text = cleaned
            warnings << "scrubbed <style> url()/@import"
          end
        end
      end
    end
  end
end
