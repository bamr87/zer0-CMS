# frozen_string_literal: true

# Rake wrappers around the ABC engine, for `bundle exec rake abc:*`. These call
# the same Zer0Cms::Abc classes as the CLI and the web wizard.
#
#   rake abc:styles
#   rake abc:themes
#   rake abc:new THEME="IT systems" STYLE=isometric-tech-toy OUT=../../drsai

$LOAD_PATH.unshift File.expand_path("../../lib", __dir__)
require "zer0_cms"

namespace :abc do
  desc "List the ABC illustration styles"
  task :styles do
    Zer0Cms::Abc::ArtStyles.default.to_menu["styles"].each do |s|
      puts "#{s['id'].ljust(22)} #{s['name']}"
    end
  end

  desc "List the bundled A–Z lexicons (offline themes)"
  task :themes do
    puts Zer0Cms::Abc::Lexicon.available.join("\n")
  end

  desc "Generate an ABC book: THEME=... [STYLE=...] [SLUG=...] [OUT=...] [PRINT=1]"
  task :new do
    theme = ENV["THEME"] or abort "set THEME=... (see rake abc:themes)"
    wizard = Zer0Cms::Abc::Wizard.new(
      theme: theme, slug: ENV["SLUG"], art_style: ENV["STYLE"],
      palette: ENV["PALETTE"], provider: ENV.fetch("PROVIDER", "auto")
    )
    spec = wizard.run
    wizard.warnings.each { |w| warn "note: #{w}" }

    exporter = Zer0Cms::Abc::JekyllExporter.new(spec, site_root: ENV.fetch("OUT", "."))
    if ENV["PRINT"]
      puts exporter.render_markdown
    else
      result = exporter.export
      puts "wrote #{result.book_path} (#{result.planned_images.length} images planned)"
    end
  end
end
