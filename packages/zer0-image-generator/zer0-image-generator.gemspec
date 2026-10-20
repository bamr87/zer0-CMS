# frozen_string_literal: true

require_relative "lib/zer0_image_generator/version"

Gem::Specification.new do |spec|
  spec.name        = "zer0-image-generator"
  spec.version     = Zer0ImageGenerator::VERSION
  spec.authors     = ["Amr Abdel"]
  spec.email       = ["amr.abdel@gmail.com"]

  spec.summary     = "AI preview/social images for any Jekyll site — " \
                     "Claude directs and reviews, an image model renders."
  spec.description = "Adds a `jekyll preview-images` command that generates " \
                     "front-matter-wired preview banners for posts and " \
                     "collections. Claude analyzes each article into an art " \
                     "brief and vision-reviews the render; OpenAI (default), " \
                     "xAI, Stability, Gemini, or a free deterministic local " \
                     "template produces the image. The engine is a single " \
                     "vendored Python file, so it also runs standalone " \
                     "without Ruby. Extracted from the zer0-mistakes theme " \
                     "and generalized: collections_dir, front_matter_key, " \
                     "authors_file, and collection auto-discovery make it " \
                     "portable to any Jekyll layout."
  spec.homepage    = "https://github.com/bamr87/zer0-image-generator"
  spec.license     = "MIT"

  spec.metadata = {
    "homepage_uri" => spec.homepage,
    "source_code_uri" => spec.homepage,
    "changelog_uri" => "#{spec.homepage}/blob/main/CHANGELOG.md",
    "bug_tracker_uri" => "#{spec.homepage}/issues",
    "rubygems_mfa_required" => "true",
  }

  spec.files = Dir[
    "lib/**/*.rb",
    "lib/**/*.py",
    "lib/**/*.js", # Playwright SVG→PNG rasterizer fallback (local provider)
    "LICENSE",
    "README.md",
    "CHANGELOG.md",
  ]
  spec.require_paths = ["lib"]

  spec.required_ruby_version = ">= 2.7.0"
  spec.add_dependency "jekyll", ">= 3.9", "< 5.0"

  # The engine itself needs python3 (3.9+) with PyYAML at runtime — checked
  # with an actionable message when the command runs.
  spec.requirements << "Python 3.9+ with PyYAML (python3 -m pip install pyyaml)"
end
